import streamlit as st
from audio_recorder_streamlit import audio_recorder
import subprocess
import sys
from pathlib import Path
import json
import tempfile
import threading
import signal
import os
import psutil
from dotenv import load_dotenv

load_dotenv()

AUDIO_AGENT_PATH = Path(__file__).parent.parent.parent.parent.joinpath("agents", "audio_agent.py").resolve()
OUTPUT_JSON = Path("transcripts_dataset.json")

def kill_process_tree(pid):
    """Kill a process and all its children"""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        # Terminate children first
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        
        # Terminate parent
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
        
        # Wait for termination
        gone, alive = psutil.wait_procs(children + [parent], timeout=3)
        
        # Force kill any remaining processes
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
                
    except psutil.NoSuchProcess:
        pass
    except Exception as exc:
        st.warning(f"Error killing process tree: {exc}")

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
    if "audio_process" not in st.session_state:
        st.session_state.audio_process = None
    
    # Start/Stop Audio Transcription Button
    st.header("Continuous Transcription")
    if not st.session_state.transcription_running:
        if st.button("Start Audio Transcription", type="primary"):
            try:
                # Start audio agent as subprocess
                process = subprocess.Popen(
                    [sys.executable, str(AUDIO_AGENT_PATH)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setsid if sys.platform != 'win32' else None,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                )
                st.session_state.audio_process = process
                st.session_state.transcription_running = True
                st.success("Audio transcription started.")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to start audio transcription: {exc}")
    else:
        st.info("🔴 Transcription is running...")
        if st.button("Stop Audio Transcription"):
            # Terminate the audio process and all its children
            if st.session_state.audio_process:
                try:
                    pid = st.session_state.audio_process.pid
                    kill_process_tree(pid)
                    st.session_state.audio_process = None
                except Exception as exc:
                    st.warning(f"Error stopping process: {exc}")
                    # Fallback: try force kill
                    try:
                        if st.session_state.audio_process:
                            st.session_state.audio_process.kill()
                            st.session_state.audio_process = None
                    except:
                        pass
            
            st.session_state.transcription_running = False
            st.success("Audio transcription stopped.")
            st.rerun()
    
if __name__ == "__main__":
    main()
