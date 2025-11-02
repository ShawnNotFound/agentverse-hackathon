# aws_test.py — AgentVerse
import asyncio
import json
import sounddevice as sd
from pathlib import Path

from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.model import AudioEvent, TranscriptEvent

AWS_REGION = "eu-west-2"
LANGUAGE_CODE = "en-GB"
SAMPLE_RATE = 16000
MEDIA_ENCODING = "pcm"

client = TranscribeStreamingClient(region=AWS_REGION)
DATASET_PATH = Path("transcripts_dataset.json")
TRANSCRIPT_DATA = []


def load_existing_dataset():
    """Populate in-memory dataset if a previous run left data on disk."""
    if not DATASET_PATH.exists():
        return
    try:
        TRANSCRIPT_DATA.extend(json.loads(DATASET_PATH.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        print("⚠️ Existing dataset file is not valid JSON; starting fresh.")


def persist_dataset():
    """Write the accumulated transcript data to disk."""
    try:
        DATASET_PATH.write_text(json.dumps(TRANSCRIPT_DATA, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"⚠️ Unable to write dataset: {exc}")


def resolve_speaker(result, alternative):
    """Try to determine which speaker produced the alternative."""
    items = getattr(alternative, "items", None) or []
    for item in items:
        speaker = getattr(item, "speaker", None)
        if speaker:
            return speaker
    channel_id = getattr(result, "channel_id", None)
    if channel_id:
        return f"channel_{channel_id}"
    return "Unknown"


def add_dataset_entry(result, alternative, transcript_text):
    """Persist the transcript text along with timing and speaker data."""
    speaker = resolve_speaker(result, alternative)
    entry = {
        "speaker": speaker,
        "transcript": transcript_text
    }
    TRANSCRIPT_DATA.append(entry)
    persist_dataset()
    return speaker


load_existing_dataset()

async def mic_audio_generator():
    """Yields audio chunks for streaming."""
    sd.default.samplerate = SAMPLE_RATE
    sd.default.channels = 1
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='int16',
        blocksize=int(SAMPLE_RATE * 0.1)
    ) as stream:
        print("🎙️ Streaming audio… (Ctrl-C to stop)")
        while True:
            data, _ = stream.read(int(SAMPLE_RATE * 0.1))
            # AudioEvent expects raw PCM bytes; no base64 encoding
            yield AudioEvent(audio_chunk=data if isinstance(data, bytes) else bytes(data))

async def transcribe_stream():
    stream = await client.start_stream_transcription(
        language_code=LANGUAGE_CODE,
        media_sample_rate_hz=SAMPLE_RATE,
        media_encoding=MEDIA_ENCODING,
        show_speaker_label=True
    )

    # Task: send audio
    async def send_audio():
        async for audio_event in mic_audio_generator():
            await stream.input_stream.send_audio_event(audio_chunk=audio_event.audio_chunk)
        await stream.input_stream.end_stream()

    # Task: receive output
    async def process_events():
        async for event in stream.output_stream:
            # print(f"Event received: {event}")
            # Transcript events
            if isinstance(event, TranscriptEvent) and event.transcript is not None:
                for result in event.transcript.results or []:
                    if result.is_partial:
                        continue
                    for alt in result.alternatives or []:
                        transcript_text = (alt.transcript or "").strip()
                        if not transcript_text:
                            continue
                        speaker = add_dataset_entry(result, alt, transcript_text)
                        print(f"🗣️ {speaker}: {transcript_text}")
            # Speaker label events (if provided by the service/library)
            speaker_labels = getattr(event, "speaker_labels", None)
            if speaker_labels and hasattr(speaker_labels, "segments"):
                for seg in speaker_labels.segments:
                    spkr = getattr(seg, "speaker_label", "Unknown")
                    st = getattr(seg, "start_time", 0.0) or 0.0
                    en = getattr(seg, "end_time", st or 0.0)
                    print(f"➤ {spkr} spoke from {st:.2f}s to {en:.2f}s")

    # Run both tasks concurrently
    await asyncio.gather(send_audio(), process_events())

async def main():
    await transcribe_stream()

if __name__ == "__main__":
    asyncio.run(main())
