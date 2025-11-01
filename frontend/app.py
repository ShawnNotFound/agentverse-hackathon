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

SCOPES = ["openid", "email", "profile"]


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

# Authentication section
params = st.experimental_get_query_params()

if "user" not in st.session_state:
	st.session_state.user = None

if "messages" not in st.session_state:
	st.session_state.messages = []

if params.get("code"):
	code = params.get("code")[0]
	state = params.get("state", [""])[0]
	try:
		user = exchange_code_for_user(code, state)
		st.session_state.user = user
		# Clean query params by reloading without params
		st.experimental_set_query_params()
		st.success(f"Logged in as {user.get('name')}")
	except Exception as exc:
		st.error(f"Login failed: {exc}")

col1, col2 = st.columns([1, 3])

with col1:
	st.header("Account")
	if st.session_state.user:
		st.write(f"**Name:** {st.session_state.user.get('name')}  ")
		st.write(f"**Email:** {st.session_state.user.get('email')}  ")
		if st.button("Logout"):
			st.session_state.user = None
			st.experimental_rerun()
	else:
		st.write("You are not logged in.")
		auth = login_flow()
		if auth:
			auth_url, state = auth
			st.markdown(f'<a href="{auth_url}"><button>Login with Google</button></a>', unsafe_allow_html=True)
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
		st.experimental_rerun()

	# small note about identity tracking
	if st.session_state.user:
		st.caption(f"Requests are associated with {st.session_state.user.get('email')}")
	else:
		st.caption("You can log in with Google to associate messages with your identity.")

