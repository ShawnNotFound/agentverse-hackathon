import os
import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests

# Paths and config
HERE = Path(__file__).parent
AGENTS_TEXT_AGENT = Path(__file__).parent.joinpath("..", "agents", "text_agent.py").resolve()
OUTPUT_JSON = Path("text_agent_output.json")

CLIENT_SECRETS_FILE = HERE.joinpath("agentverse-streamlit-app", "client_secrets.json")

# SCOPES = ["openid", "email", "profile"]
SCOPES = [
	"openid",
	# Use the explicit userinfo scopes Google returns for profile/email
	"https://www.googleapis.com/auth/userinfo.email",
	"https://www.googleapis.com/auth/userinfo.profile",
]


def load_client_config():
	if CLIENT_SECRETS_FILE.exists():
		return json.loads(CLIENT_SECRETS_FILE.read_text(encoding="utf-8"))
	return None


def login_flow():
	client_config = load_client_config()
	if not client_config:
		st.error("Google client_secrets.json not found in frontend/agentverse-streamlit-app/. Please add it.")
		return None

	flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri="http://localhost:8501/")
	auth_url, state = flow.authorization_url(prompt="consent", include_granted_scopes="true", access_type="offline")
	# Persist the state so we can validate it when Google redirects back.
	# Streamlit session_state survives until the user closes the browser tab.
	try:
		st.session_state["oauth_state"] = state
	except Exception:
		# If session_state isn't available for some reason, continue without storing.
		pass
	return auth_url, state


def exchange_code_for_user(code: str, state: str):
	client_config = load_client_config()
	flow = Flow.from_client_config(client_config, scopes=SCOPES, state=state, redirect_uri="http://localhost:8501/")
	flow.fetch_token(code=code)
	credentials = flow.credentials
	# verify id token and extract user info
	idinfo = id_token.verify_oauth2_token(credentials.id_token, grequests.Request(), client_config["web"]["client_id"])
	return {"name": idinfo.get("name"), "email": idinfo.get("email")}


st.set_page_config(page_title="Agentverse Chat", layout="wide")

st.title("Agentverse — Chat with Text Agent")


def _rerun_compat():
	"""Try to programmatically rerun the Streamlit script in a version-compatible way.

	Tries in order:
	- call st.experimental_rerun() if present
	- raise Streamlit's internal RerunException from known import paths
	- if none available, instruct the user to refresh manually
	"""
	# Preferred API
	if hasattr(st, "experimental_rerun"):
		try:
			st.experimental_rerun()
			return
		except Exception:
			# fall through to internal approach
			pass

	# Fallback: attempt to import and raise the internal RerunException
	for import_path in (
		"streamlit.runtime.scriptrunner.script_runner",
		"streamlit.report_thread",
	):
		try:
			mod = __import__(import_path, fromlist=["RerunException"]) 
			RerunException = getattr(mod, "RerunException")
			raise RerunException()
		except Exception:
			continue

	# Last resort: tell the user to refresh
	st.warning("Unable to programmatically rerun Streamlit for this environment — please refresh the page manually.")

# Authentication section
# Use the stable `st.query_params` property instead of the deprecated
# `st.experimental_get_query_params()` which was removed after 2024-04-11.
params = st.query_params

if "user" not in st.session_state:
	st.session_state.user = None

if "messages" not in st.session_state:
	st.session_state.messages = []

if params.get("code"):
	code = params.get("code")[0]
	returned_state = params.get("state", [""])[0]
	# Validate state against stored session state (if present)
	stored_state = st.session_state.get("oauth_state")
	if stored_state and stored_state != returned_state:
		st.error("Login failed: OAuth state mismatch. Please try signing in again.")
		# clear stored state to force a fresh login next time
		st.session_state.pop("oauth_state", None)
	else:
		try:
			user = exchange_code_for_user(code, returned_state)
			st.session_state.user = user
			# clear stored oauth_state
			st.session_state.pop("oauth_state", None)
			# Clean query params by reloading without params
			st.experimental_set_query_params()
			st.success(f"Logged in as {user.get('name')}")
		except Exception as exc:
			# Provide a more actionable error message for common causes
			msg = str(exc)
			if "invalid_grant" in msg or "Malformed auth code" in msg:
				st.error("Login failed: received an invalid or malformed auth code. Possible causes: you copied the code manually, the code was modified by the browser, or the code expired.")
				# Show extra debug hints that are safe (no secrets): code length, state, client config shape
				try:
					code_preview = (code[:8] + "...") if code else "(empty)"
					st.info(f"Code preview: {code_preview} (length={len(code) if code else 0})")
				except Exception:
					pass
				try:
					client_cfg = load_client_config()
					if client_cfg is None:
						st.info("client_secrets.json missing or unreadable")
					else:
						st.info(f"client_secrets contains keys: {list(client_cfg.keys())}")
						web = client_cfg.get("web") or client_cfg.get("installed")
						if web:
							st.info(f"client_id: {web.get('client_id')}")
							uris = web.get('redirect_uris') or web.get('redirect_uri') or []
							st.info(f"configured redirect_uris: {uris}")
				except Exception:
					pass
				st.write("Try these steps:\n- Close other tabs for this app and try again.\n- Use an incognito window.\n- Ensure the redirect URI in the Google Cloud Console is exactly `http://localhost:8501/` (including trailing slash).\n- If you've previously authorized the app, remove its access from your Google Account and retry.")
				# Clear stored state to force a fresh login on next attempt
				st.session_state.pop("oauth_state", None)
				if st.button("Retry login"):
					st.session_state.pop("oauth_state", None)
					_rerun_compat()
			else:
				st.error(f"Login failed: {exc}")
				# expose a retry option for other errors as well
				if st.button("Retry login"):
					st.session_state.pop("oauth_state", None)
					_rerun_compat()

col1, col2 = st.columns([1, 3])

with col1:
	st.header("Account")
	if st.session_state.user:
		st.write(f"**Name:** {st.session_state.user.get('name')}  ")
		st.write(f"**Email:** {st.session_state.user.get('email')}  ")
		if st.button("Logout"):
			st.session_state.user = None
			# st.experimental_rerun()
			_rerun_compat()
	else:
		st.write("You are not logged in.")
		auth = login_flow()
		if auth:
			auth_url, state = auth
			st.markdown(f'<a href="{auth_url}"><button>Login with Google</button></a>', unsafe_allow_html=True)
			# Use a same-tab navigation button (onclick) so Streamlit session_state remains the
			# same browser session. Opening the auth URL in a different tab can cause an
			# OAuth state mismatch because Streamlit session_state is tab-scoped.
			##btn_html = f"<button onclick=\"window.location.href='{auth_url}'\">Login with Google</button>"
			##st.markdown(btn_html, unsafe_allow_html=True)
		else:
			st.info("Place your Google OAuth client_secrets.json at `frontend/agentverse-streamlit-app/client_secrets.json`.")

with col2:
	st.header("Chat")

	def render_messages():
		for m in st.session_state.messages:
			role = m.get("role")
			text = m.get("text")
			if role == "user":
				st.markdown(f"<div style='background:#e6f2ff;padding:10px;border-radius:10px;margin:8px 0'>**You:** {text}</div>", unsafe_allow_html=True)
			else:
				st.markdown(f"<div style='background:#f1f1f1;padding:10px;border-radius:10px;margin:8px 0'>**Assistant:** {text}</div>", unsafe_allow_html=True)

	render_messages()

	user_input = st.text_input("Message", key="user_input")
	if st.button("Send") and user_input:
		# append user message
		st.session_state.messages.append({"role": "user", "text": user_input})

		# call text agent script (uses GENAI_API_KEY env var)
		try:
			subprocess.run([sys.executable, str(AGENTS_TEXT_AGENT), user_input], check=True)
			if OUTPUT_JSON.exists():
				data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
				assistant_text = data.get("text_output", "")
			else:
				assistant_text = "(no response, text_agent did not produce output)"
		except Exception as exc:
			assistant_text = f"Error running text agent: {exc}"

		st.session_state.messages.append({"role": "assistant", "text": assistant_text})
		# re-render
		_rerun_compat()

	# small note about identity tracking
	if st.session_state.user:
		st.caption(f"Requests are associated with {st.session_state.user.get('email')}")
	else:
		st.caption("You can log in with Google to associate messages with your identity.")

