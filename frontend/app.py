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
AUDIO_AGENT_PATH = Path(__file__).parent.joinpath("..", "agents", "audio_agent.py").resolve()

CLIENT_SECRETS_FILE = HERE.joinpath("agentverse-streamlit-app", "client_secrets.json")

SCOPES = [
	"openid",
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
	try:
		st.session_state["oauth_state"] = state
	except Exception:
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
	"""Try to programmatically rerun the Streamlit script in a version-compatible way."""
	try:
		st.rerun()
	except AttributeError:
		try:
			st.experimental_rerun()
		except Exception:
			st.warning("Please refresh the page manually.")


# Authentication section
params = st.query_params

if "user" not in st.session_state:
	st.session_state.user = None

if "messages" not in st.session_state:
	st.session_state.messages = []

# Handle OAuth callback
if "code" in params:
	code = params["code"]
	returned_state = params.get("state", "")
	stored_state = st.session_state.get("oauth_state")
	
	if stored_state and stored_state != returned_state:
		st.error("Login failed: OAuth state mismatch. Please try signing in again.")
		st.session_state.pop("oauth_state", None)
	else:
		try:
			user = exchange_code_for_user(code, returned_state)
			st.session_state.user = user
			st.session_state.pop("oauth_state", None)
			
			# Clear query params - FIXED VERSION
			st.query_params.clear()
			st.success(f"Logged in as {user.get('name')}")
			_rerun_compat()
			
		except Exception as exc:
			msg = str(exc)
			if "invalid_grant" in msg.lower() or "malformed" in msg.lower():
				st.error("Login failed: received an invalid or malformed auth code.")
				
				with st.expander("Debug Information"):
					try:
						code_preview = (code[:8] + "...") if code else "(empty)"
						st.info(f"Code preview: {code_preview} (length={len(code) if code else 0})")
					except:
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
					except:
						pass
				
				st.markdown("""
				**Try these steps:**
				1. Close all other tabs with this app
				2. Use an incognito/private window
				3. Verify redirect URI in Google Cloud Console is exactly `http://localhost:8501/`
				4. Remove app access from your Google Account and retry
				5. Check that your `client_secrets.json` is valid
				""")
				
				st.session_state.pop("oauth_state", None)
				
				if st.button("Clear and Retry Login"):
					st.query_params.clear()
					st.session_state.pop("oauth_state", None)
					_rerun_compat()
			else:
				st.error(f"Login failed: {exc}")
				if st.button("Retry login"):
					st.query_params.clear()
					st.session_state.pop("oauth_state", None)
					_rerun_compat()

col1, col2 = st.columns([1, 3])

with col1:
	st.header("Account")
	if st.button("Start Audio Transcription"):
		try:
			subprocess.run([sys.executable, str(AUDIO_AGENT_PATH)], check=True)
			st.success("Audio transcription started.")
		except Exception as exc:
			st.error(f"Failed to start audio transcription: {exc}")

	if st.session_state.user:
		st.write(f"**Name:** {st.session_state.user.get('name')}")
		st.write(f"**Email:** {st.session_state.user.get('email')}")
		if st.button("Logout"):
			st.session_state.user = None
			st.query_params.clear()
			_rerun_compat()
	else:
		st.write("You are not logged in.")
		auth = login_flow()
		if auth:
			auth_url, state = auth
			st.link_button("Login with Google", auth_url)
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
		st.session_state.messages.append({"role": "user", "text": user_input})

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
		_rerun_compat()

	if st.session_state.user:
		st.caption(f"Requests are associated with {st.session_state.user.get('email')}")
	else:
		st.caption("You can log in with Google to associate messages with your identity.")