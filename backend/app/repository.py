from __future__ import annotations

import csv
import json
import random
import re
import threading
import uuid
from pathlib import Path

from .settings import Settings

PARTICIPANT_COLUMNS = ["participant_uuid", "roll_number", "roll_number_normalized", "name", "speaker_id"]
SPEAKER_COLUMNS = ["speaker_id", "english", "hindi", "telugu", "khasi", "consent_status", "notes"]
SESSION_COLUMNS = ["session_id", "speaker_id", "session_number", "date", "device_id", "environment", "notes"]
ASSIGNMENT_COLUMNS = ["speaker_id", "language", "session_number", "utterance_number", "utterance_id", "sentence_id", "sentence_text", "status", "raw_path", "storage_path"]
SID_RE = re.compile(r"^S(\d{3,})$", re.I)


def _read_csv(path: Path):
    if not path.exists(): return []
    with path.open(encoding="utf-8-sig", newline="") as stream: return list(csv.DictReader(stream))


def _write_csv(path: Path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)


def _roll(value: str):
    clean = " ".join(str(value).strip().split())
    if not clean or len(clean) > 64 or any(ord(ch) < 32 for ch in clean) or "/" in clean or "\\" in clean:
        raise ValueError("Enter a roll number of 1–64 characters without path separators.")
    return clean, clean.casefold()


class LocalRepository:
    """Small file-backed metadata provider for local development."""
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.private = settings.path("participant_mapping").parent
        self.participants_path = settings.path("participant_mapping")
        self.assignments_path = self.private / "session_assignments.json"
        self.common_prompts_path = self.private / "common_prompts.json"

    def _participants(self):
        rows = _read_csv(self.participants_path)
        for row in rows:
            roll, normalized = _roll(row.get("roll_number", ""))
            row["roll_number"] = roll
            row["roll_number_normalized"] = row.get("roll_number_normalized") or normalized
            row["participant_uuid"] = row.get("participant_uuid") or str(uuid.uuid5(uuid.NAMESPACE_URL, "speaker-dataset:" + normalized))
        return rows

    
def register_participant(self, name, roll_number):
    name = " ".join(str(name).strip().split())
    roll, _ = _roll(roll_number)

    if not name or len(name) > 200 or any(ord(ch) < 32 for ch in name):
        raise ValueError("Enter a name of 1–200 characters.")

    result = self.client.rpc(
        "register_participant",
        {"p_name": name, "p_roll_number": roll}
    ).execute()

    data = self._one(result)

    # PostgreSQL JSONB results may arrive as a JSON string.
    if isinstance(data, str):
        data = json.loads(data)

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Unexpected registration response type: {type(data).__name__}"
        )

    required = {"participant_id", "speaker_id", "is_returning"}
    if not required.issubset(data):
        raise RuntimeError(
            "Registration response is missing required fields."
        )

    return {
        "participant_id": str(data["participant_id"]),
        "speaker_id": data["speaker_id"],
        "is_returning": bool(data["is_returning"]),
    }

    def _next_speaker_id(self, participants):
        used = set()
        for row in participants: self._add_sid(used, row.get("speaker_id", ""))
        for row in _read_csv(self.settings.path("metadata") / "speakers.csv"): self._add_sid(used, row.get("speaker_id", ""))
        raw = self.settings.path("raw")
        if raw.exists():
            for path in raw.iterdir(): self._add_sid(used, path.name)
        number = 1
        while number in used: number += 1
        return f"S{number:03d}"

    @staticmethod
    def _add_sid(used, value):
        match = SID_RE.fullmatch(str(value))
        if match: used.add(int(match.group(1)))

    def participant(self, participant_id: str):
        return next((row for row in self._participants() if row["participant_uuid"] == participant_id), None)

    def ensure_assignment(self, participant_id: str, language: str, session_number: int, prompt_pool: list[dict]):
        with self.lock:
            person = self.participant(participant_id)
            if not person: raise ValueError("Participant record was not found.")
            all_assignments = self._assignments()
            key = self._key(participant_id, language, session_number)
            if key not in all_assignments:
                if session_number == 1:
                    common = json.loads(self.common_prompts_path.read_text(encoding="utf-8")) if self.common_prompts_path.exists() else {}
                    if language not in common:
                        common[language] = prompt_pool
                        self.private.mkdir(parents=True, exist_ok=True)
                        self.common_prompts_path.write_text(json.dumps(common, ensure_ascii=False, indent=2), encoding="utf-8")
                    selected = common[language]
                else:
                    selected = random.SystemRandom().sample(prompt_pool, self.settings.utterances_per_session)
                all_assignments[key] = [{"utterance_number": i, "sentence_id": prompt["sentence_id"], "sentence_text": prompt["sentence_text"], "status": "missing", "storage_path": ""} for i, prompt in enumerate(selected, 1)]
                self._save_assignments(all_assignments)
            self._ensure_session_row(person["speaker_id"], session_number)
            result = []
            for row in all_assignments[key]:
                item = dict(row)
                path = self.audio_path(person["speaker_id"], language, session_number, item["utterance_number"])
                if path.exists(): item["status"] = "completed"
                item.update(speaker_id=person["speaker_id"], language=language, session_number=session_number, utterance_id=f"U{item['utterance_number']:02d}", raw_path=path.relative_to(self.settings.project_root).as_posix())
                result.append(item)
            self._write_assignment_metadata()
            return result

    def _assignments(self):
        if not self.assignments_path.exists(): return {}
        return json.loads(self.assignments_path.read_text(encoding="utf-8"))

    def _save_assignments(self, data):
        self.private.mkdir(parents=True, exist_ok=True)
        self.assignments_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _key(participant_id, language, session_number): return f"{participant_id}|{language}|{session_number}"

    def audio_path(self, speaker_id, language, session_number, utterance_number):
        return self.settings.path("raw") / speaker_id / language / f"session_{session_number}" / f"{speaker_id}_{language}_S{session_number}_U{utterance_number:02d}.wav"

    def mark_uploaded(self, participant_id, language, session_number, utterance_number, storage_path, duration_seconds):
        with self.lock:
            person = self.participant(participant_id)
            assignments = self._assignments(); key = self._key(participant_id, language, session_number)
            row = next((item for item in assignments.get(key, []) if item["utterance_number"] == utterance_number), None)
            if not row: raise ValueError("Assigned utterance was not found.")
            row["status"] = "completed"; row["storage_path"] = storage_path; row["duration_seconds"] = duration_seconds
            self._save_assignments(assignments)
            self._ensure_speaker_row(person["speaker_id"], language)
            self._write_assignment_metadata()

    def _ensure_speaker_row(self, speaker_id, language=None):
        path = self.settings.path("metadata") / "speakers.csv"; rows = _read_csv(path)
        row = next((item for item in rows if item.get("speaker_id", "").upper() == speaker_id.upper()), None)
        if row is None:
            row = {key: "" for key in SPEAKER_COLUMNS}; row.update(speaker_id=speaker_id, consent_status="pending"); rows.append(row)
        if language: row[language] = "1"
        _write_csv(path, rows, SPEAKER_COLUMNS)

    def _ensure_session_row(self, speaker_id, session_number):
        path = self.settings.path("metadata") / "sessions.csv"; rows = _read_csv(path); session_id = f"{speaker_id}_SESS{session_number:02d}"
        if not any(row.get("session_id") == session_id for row in rows):
            rows.append({"session_id": session_id, "speaker_id": speaker_id, "session_number": session_number, "date": "", "device_id": "", "environment": "", "notes": ""})
        _write_csv(path, rows, SESSION_COLUMNS)

    def _write_assignment_metadata(self):
        participants = self._participants(); by_uuid = {row["participant_uuid"]: row for row in participants}; assignments = self._assignments(); out = []
        for key, rows in assignments.items():
            participant_id, language, session = key.split("|"); person = by_uuid.get(participant_id)
            if not person: continue
            for item in rows:
                path = self.audio_path(person["speaker_id"], language, int(session), item["utterance_number"])
                out.append({"speaker_id": person["speaker_id"], "language": language, "session_number": int(session), "utterance_number": item["utterance_number"], "utterance_id": f"U{item['utterance_number']:02d}", "sentence_id": item["sentence_id"], "sentence_text": item["sentence_text"], "status": "completed" if path.exists() else item["status"], "raw_path": path.relative_to(self.settings.project_root).as_posix(), "storage_path": item.get("storage_path", "")})
        _write_csv(self.settings.path("metadata") / "recording_assignments.csv", out, ASSIGNMENT_COLUMNS)


class SupabaseRepository:
    """Metadata provider backed by the private Supabase PostgreSQL project."""
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        if client is None:
            from supabase import create_client
            client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        self.client = client

    @staticmethod
    def _one(result):
        data = result.data
        if isinstance(data, list): return data[0] if data else None
        return data

    def register_participant(self, name, roll_number):
        name = " ".join(str(name).strip().split()); roll, _ = _roll(roll_number)
        if not name or len(name) > 200 or any(ord(ch) < 32 for ch in name): raise ValueError("Enter a name of 1–200 characters.")
        data = self._one(self.client.rpc("register_participant", {"p_name": name, "p_roll_number": roll}).execute())
        if not data: raise RuntimeError("Participant registration returned no record.")
        return {"participant_id": str(data["participant_id"]), "speaker_id": data["speaker_id"], "is_returning": bool(data["is_returning"])}

    def participant(self, participant_id):
        return self._one(self.client.table("participants").select("participant_id,speaker_id").eq("participant_id", participant_id).limit(1).execute())

    def ensure_assignment(self, participant_id, language, session_number, prompt_pool):
        prompts = prompt_pool if session_number == 1 else random.SystemRandom().sample(prompt_pool, self.settings.utterances_per_session)
        payload = [{"utterance_number": i, **prompt} for i, prompt in enumerate(prompts, 1)]
        result = self.client.rpc("assign_session_prompts", {"p_participant_id": participant_id, "p_language": language, "p_session_number": session_number, "p_prompts": payload}).execute().data
        if isinstance(result, str): result = json.loads(result)
        if isinstance(result, dict) and "assign_session_prompts" in result: result = result["assign_session_prompts"]
        rows = result if isinstance(result, list) else []
        person = self.participant(participant_id)
        for row in rows:
            row["speaker_id"] = person["speaker_id"]; row["language"] = language; row["session_number"] = session_number
            row["utterance_id"] = f"U{int(row['utterance_number']):02d}"
            row["raw_path"] = f"data/raw/{person['speaker_id']}/{language}/session_{session_number}/{person['speaker_id']}_{language}_S{session_number}_{row['utterance_id']}.wav"
        return rows

    def mark_uploaded(self, participant_id, language, session_number, utterance_number, storage_path, duration_seconds):
        self.client.table("utterances").update({"status": "completed", "storage_path": storage_path, "duration_seconds": duration_seconds}).eq("participant_id", participant_id).eq("language", language).eq("session_number", session_number).eq("utterance_number", utterance_number).execute()

    def completed_rows(self):
        return [row for row in self.all_utterances() if row.get("status") == "completed"]

    def all_utterances(self):
        rows = []; offset = 0
        while True:
            batch = self.client.table("utterances").select("participant_id,speaker_id,language,session_number,utterance_number,sentence_id,sentence_text,status,storage_path,duration_seconds,created_at").range(offset, offset + 999).execute().data or []
            rows.extend(batch)
            if len(batch) < 1000: break
            offset += 1000
        return rows

    def participant_speakers(self):
        return self.client.table("participants").select("speaker_id").execute().data or []

    def sessions(self):
        return self.client.table("sessions").select("speaker_id,session_number,created_at").execute().data or []
