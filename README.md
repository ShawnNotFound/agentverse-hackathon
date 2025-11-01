# Agentverse Streamlit Chat

This repository includes a minimal Streamlit web UI that lets users log in with Google (OAuth 2.0), send messages to a text agent, and view the agent's response.

Key pieces
- `frontend/app.py` - Streamlit app. Shows "Login with Google" button, chat UI, and forwards messages to `agents/text_agent.py`.
- `agents/text_agent.py` - Refactored text agent with `generate_text(prompt)` and CLI entrypoint; writes `text_agent_output.json`.
- `requirements.txt` - lists required Python packages (Streamlit and Google auth libs added).

Quick setup
1. Create a Google OAuth client (Web application) in Google Cloud Console.
   - Set the authorized redirect URI to `http://localhost:8501/` (for local Streamlit runs).
   - Download the JSON and save it as `frontend/agentverse-streamlit-app/client_secrets.json`.

2. Install Python deps
   python -m pip install -r requirements.txt

3. Set the GenAI API key for the text agent as an environment variable:
   export GENAI_API_KEY="your_genai_api_key"

4. Run the Streamlit app from repository root:
   streamlit run frontend/app.py

5. Click "Login with Google" and complete the consent flow. After redirect back to the app, you'll be logged in. Type into the chat box and press Send.

Notes and assumptions
- The app implements a server-side OAuth flow using `google-auth-oauthlib`. The `client_secrets.json` must contain the web client credentials (the file Google gives you for web apps).
- This setup assumes you register `http://localhost:8501/` as the OAuth redirect URI in Google Cloud Console.
- The text agent uses the `google.genai` library (existing in the repo). Ensure the `GENAI_API_KEY` env var is set.

Security
- Never commit `client_secrets.json` or API keys to source control. Keep them local or in a secure secret manager.

If you want, I can:
- Add a client-side Google Identity button instead of server-side OAuth.
- Improve the chat UI with nicer bubbles and history persistence.
