import os
import json
import subprocess
import sys
from pathlib import Path
import importlib.util
from dotenv import load_dotenv
import streamlit as st


from PyPDF2 import PdfReader
from docx import Document

from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests

load_dotenv()

# Paths and config
HERE = Path(__file__).parent
AGENTS_TEXT_AGENT = Path(__file__).parent.joinpath("..", "agents", "text_agent.py").resolve()
OUTPUT_JSON = Path("text_agent_output.json")
GRAPH_VIEWER_PATH = HERE.joinpath("agentverse-streamlit-app", "pages", "graph_viewer.py")
AUDIO_VIEWER_MODULE_PATH = HERE.joinpath("agentverse-streamlit-app", "pages", "audio_viewer.py")

CLIENT_SECRETS_FILE = HERE.joinpath("agentverse-streamlit-app", "client_secrets.json")

SCOPES = [
	"openid",
	"https://www.googleapis.com/auth/userinfo.email",
	"https://www.googleapis.com/auth/userinfo.profile",
]


def load_client_config():
	# First, allow configuration via environment variables so secrets are not
	# stored in the repository. Set these in your shell or use a secret manager:
	#   GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI
	client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or os.environ.get("CLIENT_ID")
	client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or os.environ.get("CLIENT_SECRET")
	redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI") or "http://localhost:8501/"
	if client_id and client_secret:
		return {
			"web": {
				"client_id": client_id,
				"client_secret": client_secret,
				"redirect_uris": [redirect_uri],
				"auth_uri": "https://accounts.google.com/o/oauth2/auth",
				"token_uri": "https://oauth2.googleapis.com/token",
			}
		}

	# # Fallback to reading the client_secrets.json file (for compatibility).

	if CLIENT_SECRETS_FILE.exists():
		try:
			return json.loads(CLIENT_SECRETS_FILE.read_text(encoding="utf-8"))
		except Exception:
			return None
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


def load_graph_viewer_module():
	spec = importlib.util.spec_from_file_location("graph_viewer", str(GRAPH_VIEWER_PATH))
	graph_viewer = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(graph_viewer)
	return graph_viewer

def load_audio_viewer_module():
	spec = importlib.util.spec_from_file_location("audio_viewer", str(AUDIO_VIEWER_MODULE_PATH))
	audio_viewer = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(audio_viewer)
	return audio_viewer

st.set_page_config(page_title="Agentverse", layout="wide")

def _rerun_compat():
	"""Try to programmatically rerun the Streamlit script in a version-compatible way."""
	try:
		st.rerun()
	except AttributeError:
		try:
			st.experimental_rerun()
		except Exception:
			st.warning("Please refresh the page manually.")

# Initialize active page in session state
if "active_page" not in st.session_state:
	st.session_state.active_page = "Chat"

# Authentication section
params = st.query_params

if "user" not in st.session_state:
	st.session_state.user = None

if "messages" not in st.session_state:
	st.session_state.messages = []

# Comment out OAuth callback handling for testing if required 
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

# Sidebar navigation (only show if logged in)
if st.session_state.user:
	with st.sidebar:
		st.header("Navigation")
		if st.button("💬 Chat", use_container_width=True, type="primary" if st.session_state.active_page == "Chat" else "secondary"):
			st.session_state.active_page = "Chat"
			_rerun_compat()
		
		if st.button("🎤 Audio Agent", use_container_width=True, type="primary" if st.session_state.active_page == "Audio" else "secondary"):
			st.session_state.active_page = "Audio"
			_rerun_compat()
		
		if st.button("🕸️ Knowledge Graph", use_container_width=True, type="primary" if st.session_state.active_page == "Graph" else "secondary"):
			st.session_state.active_page = "Graph"
			_rerun_compat()
		
		st.divider()
		st.subheader("Account")
		st.write(f"**Name:** {st.session_state.user.get('name')}")
		st.write(f"**Email:** {st.session_state.user.get('email')}")
		if st.button("Logout", use_container_width=True):
			st.session_state.user = None
			st.session_state.active_page = "Chat"
			st.query_params.clear()
			_rerun_compat()

# Main content area
if not st.session_state.user:
	st.title("Agentverse — Chat with Text Agent")
	col1, col2 = st.columns([1, 1])
	with col1:
		st.subheader("Please log in to continue")
		auth = login_flow()
		if auth:
			auth_url, state = auth
			st.link_button("Login with Google", auth_url)
		else:
			st.info("Place your Google OAuth client_secrets.json at `frontend/agentverse-streamlit-app/client_secrets.json`.")
elif st.session_state.active_page == "Chat":
	st.title("💬 Chat with Text Agent")
	
	def render_messages():
		for m in st.session_state.messages:
			role = m.get("role")
			text = m.get("text")
			if role == "user":
				st.markdown(f"""
				<div style='display: flex; justify-content: flex-end; margin: 8px 0;'>
					<div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
					color: white; padding: 12px 16px; border-radius: 18px; max-width: 70%; 
					box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);'>
					{text}
					</div>
				</div>
				""", unsafe_allow_html=True)
			else:
				st.markdown(f"""
				<div style='display: flex; justify-content: flex-start; margin: 8px 0;'>
					<div style='background: #2d2d2d; color: white; padding: 12px 16px; 
					border-radius: 18px; max-width: 70%; 
					box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);'>
					{text}
					</div>
				</div>
				""", unsafe_allow_html=True)

	render_messages()

	user_input = st.text_input("Message", key="user_input")
	if st.button("Send") and user_input:
		st.session_state.messages.append({"role": "user", "text": user_input})

		try:
			result = subprocess.run(
				[sys.executable, str(AGENTS_TEXT_AGENT), user_input], 
				check=True,
				capture_output=True,
				text=True
			)
			if OUTPUT_JSON.exists():
				data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
				assistant_text = data.get("text_output", "")
			else:
				assistant_text = "(no response, text_agent did not produce output)"
		except subprocess.CalledProcessError as exc:
			assistant_text = f"Error running text agent:\n\nSTDOUT: {exc.stdout}\n\nSTDERR: {exc.stderr}"
		except Exception as exc:
			# fallback to subprocess and capture output for diagnostics
			try:
				proc = subprocess.run([sys.executable, str(AGENTS_TEXT_AGENT), user_input], capture_output=True, text=True)
				if proc.returncode == 0:
					# try read json output first
					if OUTPUT_JSON.exists():
						data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
						assistant_text = data.get("text_output", proc.stdout.strip())
					else:
						assistant_text = proc.stdout.strip() or proc.stderr.strip() or f"Subprocess exited with {proc.returncode}"
				else:
					assistant_text = f"Error running text agent (subprocess exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
			except Exception as exc2:
				assistant_text = f"Error running text agent: {exc} ; fallback failed: {exc2}"

		st.session_state.messages.append({"role": "assistant", "text": assistant_text})
		_rerun_compat()


	uploaded_file = st.file_uploader("Upload a file", type=["pdf", "txt", "docx"])

	def extract_text(file):
		if file.type == "application/pdf":
			reader = PdfReader(file)
			return "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
		elif file.type == "text/plain":
			return file.read().decode("utf-8")
		elif file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
			doc = Document(file)
			return "\n".join(p.text for p in doc.paragraphs)
		else:
			return ""

	if st.button("Send File") and uploaded_file:
		with st.spinner("Extracting text..."):
			raw_text = extract_text(uploaded_file)
			if raw_text:
				st.subheader("📃 Extracted Text")
				st.write(raw_text)

				# Save to JSON
				output = {"filename": uploaded_file.name, "extracted_text": raw_text}
				with open("file_text_output.json", "w", encoding="utf-8") as f:
					json.dump(output, f, indent=2)
				st.success("Text sent to the database")
			else:
				st.error("Could not extract text from the uploaded file.")


	st.caption(f"Requests are associated with {st.session_state.user.get('email')}")

elif st.session_state.active_page == "Audio":
	try:
		audio_viewer = load_audio_viewer_module()
		audio_viewer.main()
	except Exception as e:
		st.error(f"Error loading audio viewer: {e}")
		st.info("Make sure `agentverse-streamlit-app/pages/audio_viewer.py` exists and contains a `main()` function.")

elif st.session_state.active_page == "Graph":
	try:
		graph_viewer = load_graph_viewer_module()
		graph_viewer.main()
	except Exception as e:
		st.error(f"Error loading graph viewer: {e}")
		st.info("Make sure `pages/graph_viewer.py` exists and contains a `main()` function.")

