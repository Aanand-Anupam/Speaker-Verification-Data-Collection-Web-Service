"""Download completed Supabase recordings and privacy-safe metadata locally."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.repository import SPEAKER_COLUMNS, SESSION_COLUMNS, ASSIGNMENT_COLUMNS, SupabaseRepository
from backend.app.settings import Settings
from backend.app.storage import SupabaseAudioStorage
from tools.common.core import read_rows, write_rows


def sync(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    settings.storage_backend = "supabase"
    settings.validate()
    repository = SupabaseRepository(settings)
    storage = SupabaseAudioStorage(settings, repository.client)
    utterances = repository.all_utterances()
    completed = [row for row in utterances if row.get("status") == "completed"]
    raw_root = settings.path("raw"); raw_root.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = 0
    for row in completed:
        key = row.get("storage_path")
        if not key: continue
        target = raw_root / row["speaker_id"] / row["language"] / f"session_{row['session_number']}" / f"{row['speaker_id']}_{row['language']}_S{row['session_number']}_U{int(row['utterance_number']):02d}.wav"
        if target.exists():
            skipped += 1
            continue
        payload = storage.download(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream: stream.write(payload)
        downloaded += 1

    metadata = settings.path("metadata"); metadata.mkdir(parents=True, exist_ok=True)
    existing_speakers = {row["speaker_id"]: row for row in read_rows(metadata / "speakers.csv", SPEAKER_COLUMNS)}
    speakers = {}
    for row in completed:
        sid = row["speaker_id"]
        speaker = dict(existing_speakers.get(sid, {column: "" for column in SPEAKER_COLUMNS}))
        speaker["speaker_id"] = sid; speaker[row["language"]] = "1"
        if not speaker.get("consent_status"): speaker["consent_status"] = "pending"
        speakers[sid] = speaker
    write_rows(metadata / "speakers.csv", list(speakers.values()) + [row for sid, row in existing_speakers.items() if sid not in speakers], SPEAKER_COLUMNS)

    old_sessions = {row["session_id"]: row for row in read_rows(metadata / "sessions.csv", SESSION_COLUMNS)}
    for row in repository.sessions():
        sid = row["speaker_id"]; number = int(row["session_number"]); session_id = f"{sid}_SESS{number:02d}"
        if session_id not in old_sessions:
            old_sessions[session_id] = {"session_id": session_id, "speaker_id": sid, "session_number": number, "date": (row.get("created_at") or "")[:10], "device_id": "", "environment": "", "notes": ""}
    write_rows(metadata / "sessions.csv", list(old_sessions.values()), SESSION_COLUMNS)

    assignment_rows = []
    for row in utterances:
        sid = row["speaker_id"]; lang = row["language"]; number = int(row["session_number"]); utterance_no = int(row["utterance_number"])
        assignment_rows.append({"speaker_id": sid, "language": lang, "session_number": number, "utterance_number": utterance_no, "utterance_id": f"U{utterance_no:02d}", "sentence_id": row["sentence_id"], "sentence_text": row["sentence_text"], "status": row["status"], "raw_path": f"data/raw/{sid}/{lang}/session_{number}/{sid}_{lang}_S{number}_U{utterance_no:02d}.wav", "storage_path": row.get("storage_path") or ""})
    write_rows(metadata / "recording_assignments.csv", assignment_rows, ASSIGNMENT_COLUMNS)
    return {"completed_cloud_recordings": len(completed), "downloaded": downloaded, "already_present": skipped, "assignments_synced": len(assignment_rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Supabase recordings and metadata to data/raw and data/metadata")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without downloading files")
    args = parser.parse_args()
    if args.dry_run:
        cfg = Settings.from_env(); cfg.storage_backend = "supabase"; cfg.validate()
        repo = SupabaseRepository(cfg); rows = repo.all_utterances()
        print(f"Cloud utterance assignments: {len(rows)}; completed: {sum(row.get('status') == 'completed' for row in rows)}")
    else:
        print(sync())
