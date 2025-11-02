"""
Real-time transcript agent that listens for name mentions, calls GPT-5 chat for
the reply, and renders the answer through ElevenLabs text-to-speech.

This module watches the rolling JSON transcript produced by the AWS streaming
client (see transcribe/aws_test.py). When the configured agent name is spoken,
the agent collects recent context, sends it to GPT for a text reply, and hands
the response to ElevenLabs so you get an audio file. Configuration is entirely
environment-driven so you can plug in custom endpoints, models, or voices.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Deque, Dict, Iterable, List, Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    import requests
except ImportError as exc:  # pragma: no cover - hard failure if dependency missing
    raise SystemExit(
        "The 'requests' package is required. Install it with `pip install requests`."
    ) from exc


# Default ElevenLabs voice/model presets for quick smoke testing.
DEFAULT_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel
DEFAULT_ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"

DATASET_INSTRUCTION_BLOCK = """
SYSTEM CONTRACT — MANDATORY BEHAVIOR

You are an agent connected to a knowledge base ("dataset").
You are *not allowed* to make up or infer facts that are not contained in:
(a) the conversation history, or
(b) the dataset query results provided to you.

RULES:
1. If you receive any user question that might require factual information, names, project details, or external data,
   you MUST first issue a dataset search command.
2. The command format must be **exactly** one of:
     searching {"label": "<Label>", "property": "<property>", "value": "<value>"}
3. Do not write anything else with the searching command — no extra text, punctuation, or explanation.
4. Wait for the dataset results before producing any answer.
5. If the user repeats or clarifies, you may reuse your earlier search results.

EXAMPLES:
User: What is Lina's working on?
Assistant: searching {"label": "Person", "property": "name", "value": "Lina"}

User: Tell me about Project Orion.
Assistant: searching {"label": "Project", "property": "id", "value": "project_orion"}

Do not encapsulate the searching command in quotes "" or code blocks ``` ```.
Never respond conversationally (“I’m not sure”, “let me check”) before a search.
If you fail to use `searching {...}` when required, your output is invalid and will be discarded.
"""
# --------------------------------------------------------------------------- #
# Data model and helpers
# --------------------------------------------------------------------------- #


@dataclass
class TranscriptSegment:
    """Represents a single transcript entry emitted by the AWS streaming client."""

    speaker: str
    transcript: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TranscriptSegment":
        return cls(
            speaker=str(payload.get("speaker", "Unknown")),
            transcript=str(payload.get("transcript", "")).strip(),
            start_time=payload.get("start_time"),
            end_time=payload.get("end_time"),
            raw=payload,
        )


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logging.warning("Invalid float for %s=%s; using default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.warning("Invalid integer for %s=%s; using default %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    logging.warning("Invalid boolean for %s=%s; using default %s", name, raw, default)
    return default


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class AgentConfig:
    agent_name: str
    system_prompt: str
    transcript_path: Path
    poll_interval: float
    history_size: int
    response_delay: float
    trigger_phrases: List[str]

    gpt_base_url: str
    gpt_api_key: str
    gpt_model: str
    gpt_timeout: float

    elevenlabs_api_key: Optional[str]
    elevenlabs_voice_id: str
    elevenlabs_model_id: str
    elevenlabs_base_url: str
    elevenlabs_audio_format: str
    elevenlabs_output_dir: Path
    dataset_base_url: Optional[str]
    dataset_timeout: float
    dataset_enabled: bool

    @property
    def elevenlabs_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @classmethod
    def from_env(cls) -> "AgentConfig":
        agent_name = os.getenv("AGENT_NAME", "C8")
        system_prompt = os.getenv(
            "AGENT_SYSTEM_PROMPT",
            (
                "You are {agent_name}, an empathetic and technically capable teammate. "
                "Reply conversationally in plain English. Offer actionable insights when "
                "appropriate, but stay concise unless asked for detail."
            ).format(agent_name=agent_name),
        )

        transcript_path = Path(
            os.getenv("TRANSCRIPT_DATASET_PATH", "transcribe/transcripts_dataset.json")
        )
        poll_interval = _env_float("TRANSCRIPT_POLL_INTERVAL", 1.0)
        history_size = _env_int("AGENT_HISTORY_SIZE", 24)
        response_delay = _env_float("AGENT_RESPONSE_DELAY_SECONDS", 1.2)
        trigger_phrases = _split_csv(os.getenv("AGENT_TRIGGER_PHRASES"))

        gpt_base_url = os.getenv("GPT_API_BASE", os.getenv("OPENAI_BASE_URL", "https://api.openai.com"))
        gpt_api_key = os.getenv("GPT_API_KEY", os.getenv("OPENAI_API_KEY", ""))
        gpt_model = os.getenv("GPT_MODEL", "gpt-5")
        gpt_timeout = _env_float("GPT_REQUEST_TIMEOUT", 45.0)

        elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
        elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_ELEVENLABS_VOICE_ID)
        elevenlabs_model_id = os.getenv("ELEVENLABS_MODEL_ID", DEFAULT_ELEVENLABS_MODEL_ID)
        elevenlabs_base_url = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")
        elevenlabs_audio_format = os.getenv("ELEVENLABS_AUDIO_FORMAT", "mp3")
        elevenlabs_output_dir = Path(
            os.getenv("ELEVENLABS_AUDIO_OUTPUT_DIR", "live_chating/audio_responses")
        )

        dataset_enabled = _env_bool("DATASET_ENABLE", True)
        dataset_base_url = os.getenv("DATASET_BASE_URL", "http://localhost:8080")
        if not dataset_enabled:
            dataset_base_url = None
        dataset_timeout = _env_float("DATASET_TIMEOUT", 15.0)

        if dataset_base_url:
            system_prompt = (
                f"{DATASET_INSTRUCTION_BLOCK}\n\n"
                "Follow the dataset search protocol strictly before answering.\n\n"
                f"{system_prompt}"
            )
        else:
            dataset_enabled = False

        normalized_dataset_base = dataset_base_url.rstrip("/") if dataset_base_url else None

        return cls(
            agent_name=agent_name,
            system_prompt=system_prompt,
            transcript_path=transcript_path,
            poll_interval=poll_interval,
            history_size=history_size,
            response_delay=response_delay,
            trigger_phrases=trigger_phrases,
            gpt_base_url=gpt_base_url.rstrip("/"),
            gpt_api_key=gpt_api_key,
            gpt_model=gpt_model,
            gpt_timeout=gpt_timeout,
            elevenlabs_api_key=elevenlabs_api_key,
            elevenlabs_voice_id=elevenlabs_voice_id,
            elevenlabs_model_id=elevenlabs_model_id,
            elevenlabs_base_url=elevenlabs_base_url.rstrip("/"),
            elevenlabs_audio_format=elevenlabs_audio_format,
            elevenlabs_output_dir=elevenlabs_output_dir,
            dataset_base_url=normalized_dataset_base,
            dataset_timeout=dataset_timeout,
            dataset_enabled=dataset_enabled,
        )


# --------------------------------------------------------------------------- #
# Transcript watcher
# --------------------------------------------------------------------------- #


class TranscriptWatcher:
    """Polls the JSON transcript dataset for new utterances."""

    def __init__(self, dataset_path: Path, poll_interval: float = 1.0) -> None:
        self.dataset_path = dataset_path
        self.poll_interval = poll_interval
        self._last_length = 0

    async def stream(self) -> AsyncGenerator[TranscriptSegment, None]:
        logging.info("Monitoring transcript file: %s", self.dataset_path)
        while True:
            try:
                raw_text = self.dataset_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                logging.debug("Transcript file not found yet. Waiting…")
                await asyncio.sleep(self.poll_interval)
                continue
            except OSError as exc:
                logging.error("Unable to read transcript file: %s", exc)
                await asyncio.sleep(self.poll_interval)
                continue

            raw_text = raw_text.strip()
            if not raw_text:
                await asyncio.sleep(self.poll_interval)
                continue

            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                logging.warning("Transcript file contains invalid JSON; retrying shortly.")
                await asyncio.sleep(self.poll_interval)
                continue

            if not isinstance(payload, list):
                logging.warning("Transcript dataset is not an array. Ignoring.")
                await asyncio.sleep(self.poll_interval)
                continue

            if len(payload) < self._last_length:
                logging.info("Transcript dataset truncated (likely reset). Restarting stream.")
                self._last_length = 0

            if len(payload) > self._last_length:
                new_entries = payload[self._last_length :]
                self._last_length = len(payload)
                for entry in new_entries:
                    segment = TranscriptSegment.from_dict(entry)
                    if segment.transcript:
                        yield segment

            await asyncio.sleep(self.poll_interval)


# --------------------------------------------------------------------------- #
# GPT client
# --------------------------------------------------------------------------- #


class GPTClient:
    """Minimal client for GPT-style chat completions."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        if not self.api_key:
            logging.error("GPT_API_KEY missing; cannot call the chat endpoint.")
            return None

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        def _request() -> Optional[str]:
            response = requests.post(
                self.chat_url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                logging.error("GPT response contained no choices.")
                return None
            message = choices[0].get("message") or {}
            content = message.get("content", "")
            return content.strip()

        try:
            return await asyncio.to_thread(_request)
        except requests.RequestException as exc:
            logging.exception("GPT request failed: %s", exc)
            return None


# --------------------------------------------------------------------------- #
# ElevenLabs TTS client
# --------------------------------------------------------------------------- #


class ElevenLabsTTSClient:
    """Minimal ElevenLabs text-to-speech helper."""

    def __init__(self, config: AgentConfig) -> None:
        self.base_url = config.elevenlabs_base_url.rstrip("/")
        self.api_key = config.elevenlabs_api_key or ""
        self.voice_id = config.elevenlabs_voice_id
        self.model_id = config.elevenlabs_model_id
        self.audio_format = config.elevenlabs_audio_format
        self.output_dir = config.elevenlabs_output_dir

        if config.elevenlabs_enabled:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            logging.info("ElevenLabs audio output directory: %s", self.output_dir)

    async def synthesize(self, text: str) -> Optional[Path]:
        if not text:
            return None
        if not (self.api_key and self.voice_id):
            logging.warning("ElevenLabs credentials or voice ID missing; skipping TTS.")
            return None

        url = f"{self.base_url}/v1/text-to-speech/{self.voice_id}"
        payload: Dict[str, Any] = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.4,
                "similarity_boost": 0.7,
            },
        }
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": f"audio/{self.audio_format}",
        }

        def _request() -> Optional[Path]:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type.lower():
                logging.error("ElevenLabs returned error payload: %s", response.text)
                return None

            filename = f"{int(time.time() * 1000)}.{self.audio_format}"
            output_path = self.output_dir / filename
            output_path.write_bytes(response.content)
            logging.info("Saved ElevenLabs audio to %s", output_path)
            return output_path

        try:
            return await asyncio.to_thread(_request)
        except requests.RequestException as exc:
            logging.exception("ElevenLabs TTS call failed: %s", exc)
            return None


# --------------------------------------------------------------------------- #
# Dataset client
# --------------------------------------------------------------------------- #


class DatasetClient:
    """Simple wrapper around the Neo4j Flask API described in Dataset_README."""

    def __init__(self, config: AgentConfig) -> None:
        self.base_url = (config.dataset_base_url or "").rstrip("/")
        self.timeout = config.dataset_timeout
        self.enabled = config.dataset_enabled and bool(self.base_url)
        if self.enabled:
            logging.info("Dataset client enabled with base URL: %s", self.base_url)

    async def query(self, payload: Dict[str, Any]) -> str:
        if not self.enabled:
            logging.warning("Dataset search attempted but client is disabled.")
            return "Dataset search is disabled."
        url = f"{self.base_url}/query"
        
        logging.info("Sending dataset query to %s with payload: %s", url, json.dumps(payload))

        def _request() -> str:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            try:
                data = response.json()
                logging.info("Dataset query successful: %s", json.dumps(data, indent=2))
            except ValueError:
                logging.info("Dataset query returned non-JSON response: %s", response.text)
                return response.text
            return json.dumps(data, indent=2)

        try:
            return await asyncio.to_thread(_request)
        except requests.RequestException as exc:
            logging.exception("Dataset query failed: %s", exc)
            return f"Dataset query failed: {exc}"


@dataclass
class DatasetSearchCommand:
    text: str
    payload: Dict[str, Any]

# --------------------------------------------------------------------------- #
# Conversation agent
# --------------------------------------------------------------------------- #


class TranscriptAgent:
    def __init__(
        self,
        config: AgentConfig,
        gpt_client: Optional[GPTClient],
        tts_client: Optional[ElevenLabsTTSClient] = None,
        dataset_client: Optional[DatasetClient] = None,
    ) -> None:
        self.config = config
        self.gpt_client = gpt_client
        self.tts_client = tts_client
        self.dataset_client = dataset_client

        self.agent_name = config.agent_name
        self._agent_name_lower = config.agent_name.lower()
        self._triggers = [phrase.lower() for phrase in config.trigger_phrases]
        self.history: Deque[TranscriptSegment] = deque(maxlen=config.history_size)
        self._response_task: Optional[asyncio.Task[None]] = None

    async def consume(self, watcher: TranscriptWatcher, stop_event: asyncio.Event) -> None:
        try:
            async for segment in watcher.stream():
                await self.handle_segment(segment)
                if stop_event.is_set():
                    break
        except asyncio.CancelledError:
            logging.debug("Transcript consumption cancelled.")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._response_task

    async def handle_segment(self, segment: TranscriptSegment) -> None:
        self.history.append(segment)
        logging.debug("%s: %s", segment.speaker, segment.transcript)

        if self._should_trigger(segment.transcript):
            logging.info("Trigger detected for %s (speaker=%s).", self.agent_name, segment.speaker)
            await self._schedule_response()

    def _should_trigger(self, transcript: str) -> bool:
        lowered = transcript.lower()
        if self._agent_name_lower in lowered:
            return True
        return any(phrase in lowered for phrase in self._triggers)

    async def _schedule_response(self) -> None:
        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._response_task

        self._response_task = asyncio.create_task(self._respond_after_delay())

    async def _respond_after_delay(self) -> None:
        try:
            await asyncio.sleep(self.config.response_delay)
            await self._generate_response()
        except asyncio.CancelledError:
            logging.debug("Deferred response cancelled before execution.")

    async def _generate_response(self) -> None:
        history_snapshot = list(self.history)
        if not history_snapshot:
            logging.debug("No history available when attempting to respond.")
            return

        messages = self._build_prompt(history_snapshot)
        if not messages:
            logging.debug("Prompt construction produced no messages; skipping response.")
            return

        if not self.gpt_client:
            logging.error("GPT client not configured; cannot generate response.")
            return

        response_text = await self.gpt_client.chat_completion(messages)
        if not response_text:
            logging.warning("GPT returned no content; skipping TTS.")
            return

        search_command: Optional[DatasetSearchCommand] = None
        if self.dataset_client and self.dataset_client.enabled:
            search_command = self._extract_search_command(response_text)
            if search_command:
                logging.info("Extracted dataset search command: %s", search_command.text)

        messages_for_followup = list(messages)
        dataset_result: Optional[str] = None

        if search_command and self.dataset_client:
            logging.info("%s initiating dataset search: %s", self.agent_name, search_command.text)
            self.history.append(
                TranscriptSegment(
                    speaker=self.agent_name,
                    transcript=search_command.text,
                    start_time=None,
                    end_time=None,
                    raw={"generated": True, "dataset_query": search_command.payload},
                )
            )

            dataset_result = await self.dataset_client.query(search_command.payload)
            logging.info("Dataset result received: %s", dataset_result[:200] if dataset_result else "None")
            
            messages_for_followup.append({"role": "assistant", "content": search_command.text})
            messages_for_followup.append(
                {
                    "role": "system",
                    "content": f"Dataset search results:\n{dataset_result}",
                }
            )

            response_text = await self.gpt_client.chat_completion(messages_for_followup)
            if not response_text:
                logging.warning("GPT returned no content after dataset search; skipping TTS.")
                return

        logging.info("%s reply: %s", self.agent_name, response_text)
        self.history.append(
            TranscriptSegment(
                speaker=self.agent_name,
                transcript=response_text,
                start_time=None,
                end_time=None,
                raw={"generated": True, "dataset_result": dataset_result} if dataset_result else {"generated": True},
            )
        )

        if self.tts_client:
            audio_path = await self.tts_client.synthesize(response_text)
            if audio_path:
                logging.debug("Audio response saved to %s", audio_path)

    def _build_prompt(self, history: Iterable[TranscriptSegment]) -> List[Dict[str, str]]:
        lines: List[str] = []
        for segment in history:
            start = segment.start_time
            end = segment.end_time
            timing = ""
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                timing = f"[{start:.2f}-{end:.2f}] "
            lines.append(f"{timing}{segment.speaker}: {segment.transcript}")

        if not lines:
            return []

        conversation_log = "\n".join(lines)
        user_prompt = (
            f"{conversation_log}\n\n"
            f"Respond as {self.agent_name} to the latest request that references you. "
            "Keep the answer natural, brief, and helpful."
        )

        return [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _extract_search_command(self, text: str) -> Optional[DatasetSearchCommand]:
        if not text:
            return None
        
        # First, remove code blocks from the entire text
        cleaned_text = text.strip()
        
        # Handle multi-line code blocks (``` or more backticks)
        lines = cleaned_text.split('\n')
        cleaned_lines = []
        in_code_block = False
        
        for line in lines:
            stripped = line.strip()
            # Check if line starts with backticks (code block delimiter)
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                continue
            # Skip language identifiers after opening code blocks
            if not in_code_block or stripped not in ('json', 'javascript', 'python', ''):
                cleaned_lines.append(line)
        
        # Rejoin the cleaned content
        cleaned_text = '\n'.join(cleaned_lines).strip()
        
        # Also handle inline code blocks (single backticks around entire content)
        if cleaned_text.startswith('`') and cleaned_text.endswith('`'):
            cleaned_text = cleaned_text[1:-1].strip()
        
        # Now look for the searching prefix
        prefix = "searching"
        text_lower = cleaned_text.lower().strip()
        
        if prefix not in text_lower:
            return None
            
        # Find the start of the JSON payload
        start_idx = cleaned_text.lower().find(prefix) + len(prefix)
        remainder = cleaned_text[start_idx:].strip()
        
        if not remainder:
            logging.warning("Search command found but no JSON payload")
            return None
        
        try:
            payload = json.loads(remainder)
        except json.JSONDecodeError as e:
            logging.warning("Unable to parse dataset search payload: %s (Error: %s)", remainder, e)
            return None
            
        if not isinstance(payload, dict):
            logging.warning("Dataset search payload must be an object: %s", remainder)
            return None
        return DatasetSearchCommand(text=text, payload=payload)


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


async def _run() -> None:
    config = AgentConfig.from_env()

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    watcher = TranscriptWatcher(config.transcript_path, config.poll_interval)

    gpt_client: Optional[GPTClient] = None
    if config.gpt_api_key and config.gpt_base_url:
        gpt_client = GPTClient(
            base_url=config.gpt_base_url,
            api_key=config.gpt_api_key,
            model=config.gpt_model,
            timeout=config.gpt_timeout,
        )

    tts_client = ElevenLabsTTSClient(config) if config.elevenlabs_enabled else None
    dataset_client = DatasetClient(config) if config.dataset_enabled else None
    agent = TranscriptAgent(config, gpt_client, tts_client, dataset_client)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logging.info("Shutdown signal received. Stopping agent.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    consumer_task = asyncio.create_task(agent.consume(watcher, stop_event))
    await stop_event.wait()
    consumer_task.cancel()
    with suppress(asyncio.CancelledError):
        await consumer_task


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
