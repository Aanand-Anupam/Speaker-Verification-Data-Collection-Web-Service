from __future__ import annotations

from pathlib import Path

from .settings import Settings


class LocalAudioStorage:
    def __init__(self, settings: Settings): self.settings = settings

    def put(self, speaker_id, language, session_number, utterance_number, payload):
        filename = f"{speaker_id}_{language}_S{session_number}_U{utterance_number:02d}.wav"
        target = self.settings.path("raw") / speaker_id / language / f"session_{session_number}" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream: stream.write(payload)
        except FileExistsError: raise FileExistsError("A recording already exists for this utterance; it will not be overwritten.")
        return target.relative_to(self.settings.project_root).as_posix()


class SupabaseAudioStorage:
    def __init__(self, settings: Settings, client):
        self.settings = settings; self.client = client

    def object_path(self, speaker_id, language, session_number, utterance_number):
        filename = f"{speaker_id}_{language}_S{session_number}_U{utterance_number:02d}.wav"
        return f"{speaker_id}/{language}/session_{session_number}/{filename}"

    def put(self, speaker_id, language, session_number, utterance_number, payload):
        key = self.object_path(speaker_id, language, session_number, utterance_number)
        bucket = self.client.storage.from_(self.settings.supabase_bucket)
        try:
            bucket.upload(key, payload, file_options={"content-type": "audio/wav", "upsert": "false"})
            return key
        except Exception as exc:
            # A network retry is idempotent only if the already-stored object is byte-identical.
            try: existing = bucket.download(key)
            except Exception: raise RuntimeError("Audio upload to Supabase failed. Please retry.") from exc
            if bytes(existing) == payload: return key
            raise FileExistsError("A recording already exists for this utterance; it will not be overwritten.") from exc

    def download(self, key): return bytes(self.client.storage.from_(self.settings.supabase_bucket).download(key))
