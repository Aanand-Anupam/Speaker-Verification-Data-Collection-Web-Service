from __future__ import annotations

from .audio import validate_recording
from .prompts import load_prompts
from .security import issue_token
from .settings import Settings


class CollectionService:
    def __init__(self, settings: Settings, repository, storage):
        self.settings = settings; self.repository = repository; self.storage = storage

    def register(self, name, roll_number):
        participant = self.repository.register_participant(name, roll_number)
        return {"access_token": issue_token(participant["participant_id"], self.settings.app_secret_key), "token_type": "bearer", "is_returning": participant["is_returning"]}

    def session(self, participant_id, language, session_number):
        if session_number not in (1, 2): raise ValueError("The study has exactly two sessions.")
        if language not in self.settings.languages: raise ValueError("Unsupported language.")
        pool = load_prompts(self.settings, language, session_number)
        rows = self.repository.ensure_assignment(participant_id, language, session_number, pool)
        return {"language": language, "session_number": session_number, "total": self.settings.utterances_per_session, "max_duration_seconds": self.settings.max_utterance_duration_seconds, "utterances": [{"utterance_number": int(row["utterance_number"]), "utterance_id": row.get("utterance_id", f"U{int(row['utterance_number']):02d}"), "sentence_id": row["sentence_id"], "text": row.get("sentence_text", row.get("text", "")), "status": row["status"]} for row in rows]}

    def upload(self, participant_id, language, session_number, utterance_number, payload):
        if session_number not in (1, 2): raise ValueError("The study has exactly two sessions.")
        if language not in self.settings.languages: raise ValueError("Unsupported language.")
        if not 1 <= utterance_number <= self.settings.utterances_per_session: raise ValueError("Utterance number must be between 1 and 10.")
        person = self.repository.participant(participant_id)
        if not person: raise ValueError("Participant record was not found.")
        prompts = load_prompts(self.settings, language, session_number)
        assignments = self.repository.ensure_assignment(participant_id, language, session_number, prompts)
        assignment = next((row for row in assignments if int(row["utterance_number"]) == utterance_number), None)
        if assignment is None: raise ValueError("This utterance has not been assigned.")
        if assignment["status"] == "completed": raise FileExistsError("This utterance is already complete and cannot be overwritten.")
        duration = validate_recording(payload, self.settings.max_utterance_duration_seconds)
        key = self.storage.put(person["speaker_id"], language, session_number, utterance_number, payload)
        self.repository.mark_uploaded(participant_id, language, session_number, utterance_number, key, duration)
        return {"uploaded": True, "duration_seconds": duration}
