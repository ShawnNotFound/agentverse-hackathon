import streamlit as st
from audio_recorder_streamlit import audio_recorder
import subprocess
import sys
from pathlib import Path
import json
import tempfile
import threading
from dotenv import load_dotenv

load_dotenv()

AUDIO_AGENT_PATH = Path(__file__).parent.parent.parent.parent.joinpath("agents", "audio_agent.py").resolve()
OUTPUT_JSON = Path("transcripts_dataset.json")

def main():
    """Main function to display Audio Agent interface"""
    st.title("🎤 Audio Agent - Live Transcription")
    
    # Debug: Show the resolved path
    st.caption(f"Audio agent path: {AUDIO_AGENT_PATH}")
    if not AUDIO_AGENT_PATH.exists():
        st.error(f"Audio agent script not found at: {AUDIO_AGENT_PATH}")
        return
    
    st.write("Start the audio transcription service to capture and transcribe speech in real-time.")
    
    # Initialize session state
    if "transcriptions" not in st.session_state:
        st.session_state.transcriptions = []
    if "transcription_running" not in st.session_state:
        st.session_state.transcription_running = False
    
    # Start/Stop Audio Transcription Button
    st.header("Continuous Transcription")
    if not st.session_state.transcription_running:
        if st.button("Start Audio Transcription", type="primary"):
            try:
                # Run audio agent in background thread
                def run_audio_agent():
                    subprocess.run([sys.executable, str(AUDIO_AGENT_PATH)], check=True)
                
                thread = threading.Thread(target=run_audio_agent, daemon=True)
                thread.start()
                st.session_state.transcription_running = True
                st.success("Audio transcription started.")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to start audio transcription: {exc}")
    else:
        st.info("🔴 Transcription is running...")
        if st.button("Stop Audio Transcription"):
            st.session_state.transcription_running = False
            st.success("Audio transcription stopped.")
            st.rerun()
    
if __name__ == "__main__":
    main()
