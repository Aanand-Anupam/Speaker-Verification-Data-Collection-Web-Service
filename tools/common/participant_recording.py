"""Participant identity and browser-recording helpers.

Participant names and roll numbers stay in the private mapping file. Audio and
the processing pipeline only use internally assigned speaker IDs.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
import threading
import random
from pathlib import Path

import soundfile as sf

from common.core import LANGUAGES, SPEAKER_COLUMNS, load_config, project_path, read_rows, write_rows
from register_speaker import register as register_speaker

PARTICIPANT_COLUMNS = ["roll_number", "name", "speaker_id"]
ROLL_RE = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,64}$")
SPEAKER_RE = re.compile(r"^S(\d{3,})$", re.I)

TOPICS = [
    "Describe a usual day in your life.",
    "Talk about a place where you feel comfortable.",
    "Describe a meal you enjoy and how it is prepared.",
    "Tell a story about a memorable journey.",
    "Describe a person who has taught you something useful.",
    "Talk about a hobby or activity you enjoy.",
    "Describe the weather you like most.",
    "Explain how you would welcome a visitor to your area.",
    "Talk about a celebration or festival you enjoy.",
    "Describe something you learned recently.",
    "Talk about a book, film, or story you remember.",
    "Describe how you like to spend a free afternoon.",
    "Talk about a useful object you use every day.",
    "Describe a sound that reminds you of a place or event.",
    "Talk about a small goal you hope to achieve.",
    "Describe a game or sport you have played or watched.",
    "Explain how you would make a simple favorite drink.",
    "Talk about a time you helped someone.",
    "Describe a local place you would recommend visiting.",
    "Talk about a skill you would like to learn.",
    "Describe what you do when you need to relax.",
    "Talk about a memorable day with friends or family.",
    "Describe a plant or animal you find interesting.",
    "Explain how you organize your study or work tasks.",
]


def normalized_roll(value: str) -> str:
    value = " ".join(str(value).strip().split())
    if not ROLL_RE.fullmatch(value):
        raise ValueError("Enter a roll number of 1–64 characters without slashes or control characters.")
    return value.casefold()


def validate_wav_payload(payload: bytes, max_duration: float | None = None) -> float:
    """Validate a complete WAV upload and return its duration in seconds."""
    if not payload or len(payload) > 10 * 1024 * 1024:
        raise ValueError("The recording is empty or exceeds the 10 MB upload limit.")
    try:
        info = sf.info(io.BytesIO(payload))
        if info.format != "WAV" or info.subtype != "PCM_16":
            raise ValueError("Recording must be 16-bit PCM WAV.")
        if info.samplerate != 16000 or info.channels != 1:
            raise ValueError("Recording must be mono at 16,000 Hz.")
        audio, _ = sf.read(io.BytesIO(payload), dtype="float32", always_2d=True)
        duration = len(audio) / info.samplerate
        if not duration:
            raise ValueError("Recording has no audio samples.")
        if max_duration is not None and duration > max_duration + 0.05:
            raise ValueError(f"Recording exceeds the {max_duration:g}-second limit.")
        return duration
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Upload is not a readable WAV recording.") from exc


class ParticipantStore:
    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path else None
        self.cfg = load_config(config_path)
        self.lock = threading.RLock()
        self.tokens: dict[str, str] = {}

    @property
    def mapping_path(self):
        return Path(self.cfg["_root"]) / self.cfg["paths"]["participant_mapping"]

    def participant(self, name: str, roll_number: str) -> dict:
        name = " ".join(str(name).strip().split())
        if not name or len(name) > 200 or any(ord(ch) < 32 for ch in name):
            raise ValueError("Enter a name of 1–200 characters.")
        roll = " ".join(str(roll_number).strip().split())
        norm = normalized_roll(roll)
        with self.lock:
            rows = read_rows(self.mapping_path, PARTICIPANT_COLUMNS)
            row = next((r for r in rows if normalized_roll(r["roll_number"]) == norm), None)
            existing = row is not None
            if row is None:
                sid = self._next_speaker_id(rows)
                row = {"roll_number": roll, "name": name, "speaker_id": sid}
                rows.append(row)
            else:
                sid = row["speaker_id"]
                # Keep the latest spelling of the provided name for that roll number.
                row["name"] = name
            write_rows(self.mapping_path, rows, PARTICIPANT_COLUMNS)
            register_speaker(sid, [], self.config_path)
            token = secrets.token_urlsafe(32)
            self.tokens[token] = sid
            return {"token": token, "existing": existing}

    def _next_speaker_id(self, participants) -> str:
        used = set()
        for row in participants:
            m = SPEAKER_RE.fullmatch(row.get("speaker_id", ""))
            if m: used.add(int(m.group(1)))
        speakers = read_rows(project_path(self.cfg, "metadata") / "speakers.csv", SPEAKER_COLUMNS)
        for row in speakers:
            m = SPEAKER_RE.fullmatch(row.get("speaker_id", ""))
            if m: used.add(int(m.group(1)))
        raw = project_path(self.cfg, "raw")
        if raw.exists():
            for entry in raw.iterdir():
                m = SPEAKER_RE.fullmatch(entry.name)
                if m: used.add(int(m.group(1)))
        n = 1
        while n in used: n += 1
        return f"S{n:03d}"

    def speaker_for_token(self, token: str) -> str:
        try: return self.tokens[token]
        except KeyError as exc: raise ValueError("Participant session expired. Enter your name and roll number again.") from exc

    def logout(self, token: str) -> None:
        self.tokens.pop(token, None)

    def recording_path(self, speaker_id: str, language: str, session_number: int, utterance_id: str) -> Path:
        if language not in LANGUAGES or session_number not in (1, 2, 3):
            raise ValueError("Unsupported language or session.")
        if not re.fullmatch(r"(?:U\d{2,}|SP\d{2,})", utterance_id):
            raise ValueError("Invalid utterance identifier.")
        raw = project_path(self.cfg, "raw")
        return raw / speaker_id / language / f"session_{session_number}" / f"{speaker_id}_{language}_S{session_number}_{utterance_id}.wav"

    def session_plan(self, token: str, language: str, session_number: int) -> dict:
        sid = self.speaker_for_token(token)
        if language not in LANGUAGES or session_number not in (1, 2, 3):
            raise ValueError("Choose one of the listed languages and sessions 1, 2, or 3.")
        if session_number in (1, 2):
            script = Path(self.cfg["_root"]) / self.cfg["paths"].get("scripts", "scripts") / language / f"session_{session_number}.txt"
            sentences = script.read_text(encoding="utf-8").splitlines() if script.exists() else []
            if any("TODO" in line.upper() or "PLACEHOLDER" in line.upper() for line in sentences):
                sentences = []
            sentences = [line.strip() for line in sentences if line.strip()]
            prompts = [{"utterance_id": f"U{i:02d}", "text": sentence} for i, sentence in enumerate(sentences, 1)]
            ready = bool(prompts)
            message = "" if ready else f"A validated {language.title()} script is not available yet. Please ask the researcher before recording this language."
        else:
            count = int(self.cfg["recording"]["spontaneous_utterances_per_session"])
            prompts = [{"utterance_id": f"SP{i:02d}", "text": "Speak naturally in the selected language about this topic:", "topic": random.choice(TOPICS)} for i in range(1, count + 1)]
            ready = bool(prompts)
            message = ""
        root = project_path(self.cfg, "raw") / sid / language / f"session_{session_number}"
        for prompt in prompts:
            target = self.recording_path(sid, language, session_number, prompt["utterance_id"])
            prompt["completed"] = target.exists()
            prompt["conflict"] = not target.exists() and any(target.with_suffix(ext).exists() for ext in self.cfg["audio"]["supported_extensions"] if ext.lower() != ".wav")
            prompt["status"] = "complete" if prompt["completed"] else "conflict" if prompt["conflict"] else "missing"
        root.mkdir(parents=True, exist_ok=True)
        return {"ready": ready, "message": message, "language": language, "session": session_number, "max_duration_seconds": int(self.cfg["recording"].get("spontaneous_max_duration_seconds", 20)) if session_number == 3 else None, "prompts": prompts}

    def accept_upload(self, token, language, session_number, utterance_id, payload) -> dict:
        sid = self.speaker_for_token(token)
        plan = self.session_plan(token, language, session_number)
        prompt = next((p for p in plan["prompts"] if p["utterance_id"] == utterance_id), None)
        if not prompt or not plan["ready"]:
            raise ValueError("This utterance is not part of the selected session script.")
        if prompt["completed"] or prompt["conflict"]:
            raise FileExistsError("A recording already exists for this utterance; it will not be overwritten.")
        max_duration = plan["max_duration_seconds"]
        duration = validate_wav_payload(payload, max_duration=max_duration)
        target = self.recording_path(sid, language, session_number, utterance_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as f:
                f.write(payload)
        except FileExistsError:
            raise FileExistsError("A recording already exists for this utterance; it will not be overwritten.")
        # Add the language to dataset metadata only once a valid recording exists.
        register_speaker(sid, [language], self.config_path)
        return {"duration_seconds": duration, "filename": target.name}
