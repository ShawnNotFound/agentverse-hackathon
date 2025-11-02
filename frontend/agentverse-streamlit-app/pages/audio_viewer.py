import streamlit as st
import subprocess
import sys
from pathlib import Path
import threading
import os
import psutil
from dotenv import load_dotenv
import time
import pygame
import json

load_dotenv()

AUDIO_AGENT_PATH = Path(__file__).parent.parent.parent.parent.joinpath("agents/transcribe/", "audio_agent.py").resolve()
AUDIO_RESPONSES_DIR = Path(__file__).parent.parent.parent.parent.joinpath("agents/live_chating/audio_responses/").resolve()
OUTPUT_JSON = Path(__file__).parent.parent.parent / "transcripts_dataset.json"

# Ensure audio responses directory exists
if not AUDIO_RESPONSES_DIR.exists():
    AUDIO_RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

def kill_process_tree(pid):
    """Kill a process and all its children"""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
        
        gone, alive = psutil.wait_procs(children + [parent], timeout=3)
        
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
                
    except psutil.NoSuchProcess:
        pass
    except Exception as exc:
        st.warning(f"Error killing process tree: {exc}")

def monitor_and_play_audio(stop_event):
    """Monitor audio responses directory and play new files automatically"""
    try:
        # Initialize pygame mixer in this thread
        pygame.mixer.quit()  # Quit any existing mixer
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
        print(f"Audio monitor started. Watching: {AUDIO_RESPONSES_DIR}")
    except Exception as e:
        print(f"Failed to initialize pygame mixer: {e}")
        return
    
    # Track files we've already seen
    seen_files = set(AUDIO_RESPONSES_DIR.glob("*.mp3"))
    print(f"Initial files seen: {len(seen_files)}")
    
    while not stop_event.is_set():
        try:
            # Get current files
            current_files = set(AUDIO_RESPONSES_DIR.glob("*.mp3"))
            
            # Find new files
            new_files = current_files - seen_files
            
            if new_files:
                print(f"Found {len(new_files)} new audio file(s)")
                # Sort by modification time and play the newest
                for audio_file in sorted(new_files, key=lambda f: f.stat().st_mtime):
                    try:
                        print(f"Playing audio: {audio_file}")
                        
                        # Ensure file is fully written (wait a bit)
                        time.sleep(0.2)
                        
                        # Load and play the audio file
                        pygame.mixer.music.load(str(audio_file))
                        pygame.mixer.music.play()
                        
                        # Wait for playback to finish
                        while pygame.mixer.music.get_busy() and not stop_event.is_set():
                            pygame.time.Clock().tick(10)
                        
                        print(f"Finished playing: {audio_file}")
                        
                        # Small delay before deletion
                        time.sleep(0.1)
                        
                        # Delete the file after playing
                        audio_file.unlink()
                        print(f"Deleted: {audio_file}")
                        
                    except Exception as e:
                        print(f"Error playing {audio_file}: {e}")
                        # Still remove from seen files even if play failed
                
                # Update seen files
                seen_files = set(AUDIO_RESPONSES_DIR.glob("*.mp3"))
            
            time.sleep(0.3)  # Check every 300ms
            
        except Exception as exc:
            print(f"Monitor error: {exc}")
            time.sleep(1)
    
    # Cleanup
    try:
        pygame.mixer.quit()
        print("Audio monitor stopped")
    except:
        pass

def load_transcripts():
    """Load transcripts from the dataset JSON file"""
    # Try to resolve the absolute path
    transcript_path = OUTPUT_JSON.resolve()
    
    print(f"DEBUG: Looking for transcripts at: {transcript_path}")
    print(f"DEBUG: File exists: {transcript_path.exists()}")
    
    if not transcript_path.exists():
        print("DEBUG: Transcript file does not exist yet")
        return []
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"DEBUG: File content length: {len(content)} bytes")
            if not content.strip():
                print("DEBUG: File is empty")
                return []
            data = json.loads(content)
            print(f"DEBUG: Loaded {len(data) if isinstance(data, list) else 0} transcripts")
            return data if isinstance(data, list) else []
    except json.JSONDecodeError as e:
        print(f"DEBUG: JSON decode error: {e}")
        return []
    except IOError as e:
        print(f"DEBUG: IO error: {e}")
        return []

def display_transcript_ui():
    """Display transcripts in a nice UI"""
    st.subheader("💬 Live Conversation")
    
    # Show file path for debugging
    st.caption(f"📁 Transcript file: {OUTPUT_JSON.resolve()}")
    
    # Filter controls
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        filter_option = st.selectbox(
            "Filter",
            ["All Messages", "Agent (C8) Only", "Users Only"],
            key="transcript_filter"
        )
    with col2:
        max_messages = st.slider("Max messages to show", 10, 100, 50, key="max_messages")
    with col3:
        if st.button("🗑️ Clear", key="clear_transcripts"):
            try:
                if OUTPUT_JSON.exists():
                    OUTPUT_JSON.write_text("[]", encoding="utf-8")
                    st.success("Transcripts cleared!")
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to clear: {e}")
    
    # Load and filter transcripts
    transcripts = load_transcripts()
    
    # Debug info
    if transcripts:
        st.caption(f"✅ Loaded {len(transcripts)} total transcript(s)")
    else:
        st.caption(f"⚠️ No transcripts found in file")
    
    agent_name = os.getenv("AGENT_NAME", "C8")
    
    if filter_option == "Agent (C8) Only":
        transcripts = [t for t in transcripts if t.get("speaker") == agent_name]
    elif filter_option == "Users Only":
        transcripts = [t for t in transcripts if t.get("speaker") != agent_name]
    
    # Limit messages
    transcripts = transcripts[-max_messages:]
    
    # Display count
    st.caption(f"📊 Showing {len(transcripts)} message(s)")
    
    # Custom CSS for better styling
    st.markdown("""
    <style>
    .message-container {
        margin: 12px 0;
        padding: 16px;
        border-radius: 12px;
        animation: fadeIn 0.3s;
    }
    .agent-message {
        background: linear-gradient(135deg, #1e3a5f 0%, #2c5282 100%);
        border-left: 4px solid #4ECDC4;
        box-shadow: 0 2px 8px rgba(78, 205, 196, 0.2);
    }
    .user-message {
        background: linear-gradient(135deg, #2d2d2d 0%, #3a3a3a 100%);
        border-left: 4px solid #FF6B6B;
        box-shadow: 0 2px 8px rgba(255, 107, 107, 0.2);
    }
    .speaker-name {
        font-weight: 600;
        font-size: 14px;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .agent-speaker {
        color: #4ECDC4;
    }
    .user-speaker {
        color: #FF6B6B;
    }
    .message-text {
        color: #e8e8e8;
        font-size: 15px;
        line-height: 1.6;
        word-wrap: break-word;
    }
    .speaker-icon {
        font-size: 18px;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: #888;
    }
    .empty-state-icon {
        font-size: 64px;
        margin-bottom: 16px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Display transcripts
    if not transcripts:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-state-icon">💭</div>
            <h3>No messages yet</h3>
            <p>Start the audio transcription to see the conversation appear here.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Create a container with max height and scrolling
        with st.container():
            for idx, entry in enumerate(reversed(transcripts)):
                speaker = entry.get("speaker", "Unknown")
                transcript = entry.get("transcript", "")
                
                # Escape HTML in transcript text
                transcript = transcript.replace("<", "&lt;").replace(">", "&gt;")
                
                is_agent = speaker == agent_name
                
                if is_agent:
                    st.markdown(f"""
                    <div class="message-container agent-message">
                        <div class="speaker-name agent-speaker">
                            <span class="speaker-icon">🤖</span>
                            <span>{speaker}</span>
                        </div>
                        <div class="message-text">{transcript}</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="message-container user-message">
                        <div class="speaker-name user-speaker">
                            <span class="speaker-icon">👤</span>
                            <span>{speaker}</span>
                        </div>
                        <div class="message-text">{transcript}</div>
                    </div>
                    """, unsafe_allow_html=True)

def main():
    """Main function to display Audio Agent interface"""
    st.title("🎤 Audio Agent - Live Transcription")
    
    st.caption(f"Audio agent path: {AUDIO_AGENT_PATH}")
    st.caption(f"Audio responses dir: {AUDIO_RESPONSES_DIR}")
    
    if not AUDIO_AGENT_PATH.exists():
        st.error(f"Audio agent script not found at: {AUDIO_AGENT_PATH}")
        return
    
    # Initialize session state
    if "transcription_running" not in st.session_state:
        st.session_state.transcription_running = False
    if "audio_process" not in st.session_state:
        st.session_state.audio_process = None
    if "monitor_thread" not in st.session_state:
        st.session_state.monitor_thread = None
    if "stop_event" not in st.session_state:
        st.session_state.stop_event = None
    
    # Start/Stop Audio Transcription Button
    st.header("🎙️ Transcription Control")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if not st.session_state.transcription_running:
            if st.button("▶️ Start Audio Transcription", type="primary", use_container_width=True):
                try:
                    # Ensure audio responses directory exists
                    AUDIO_RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
                    
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
                    
                    # Create stop event for thread communication
                    stop_event = threading.Event()
                    st.session_state.stop_event = stop_event
                    
                    # Give process a moment to start
                    time.sleep(0.5)
                    
                    # Start audio monitoring thread
                    monitor_thread = threading.Thread(target=monitor_and_play_audio, args=(stop_event,), daemon=True)
                    monitor_thread.start()
                    st.session_state.monitor_thread = monitor_thread
                    
                    st.success("✅ Audio transcription started!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to start audio transcription: {exc}")
        else:
            st.success("🔴 Transcription Active")
    
    with col2:
        if st.session_state.transcription_running:
            if st.button("⏹️ Stop Audio Transcription", type="secondary", use_container_width=True):
                # Signal the monitor thread to stop
                if st.session_state.stop_event:
                    st.session_state.stop_event.set()
                
                if st.session_state.audio_process:
                    try:
                        pid = st.session_state.audio_process.pid
                        kill_process_tree(pid)
                        st.session_state.audio_process = None
                    except Exception as exc:
                        st.warning(f"Error stopping process: {exc}")
                        try:
                            if st.session_state.audio_process:
                                st.session_state.audio_process.kill()
                                st.session_state.audio_process = None
                        except:
                            pass
                
                st.session_state.transcription_running = False
                st.session_state.monitor_thread = None
                st.session_state.stop_event = None
                st.success("⏹️ Audio transcription stopped.")
                st.rerun()
    
    st.divider()
    
    # Display transcripts
    display_transcript_ui()
    
    # Auto-refresh when transcription is running
    if st.session_state.transcription_running:
        time.sleep(2)
        st.rerun()

if __name__ == "__main__":
    main()
