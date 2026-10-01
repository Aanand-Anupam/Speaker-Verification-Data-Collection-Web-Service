"""Import the earlier local participant mapping into Supabase without changing speaker IDs."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.settings import Settings
from backend.app.repository import SupabaseRepository


def import_participants(path=None, settings=None):
    settings = settings or Settings.from_env(); settings.storage_backend = "supabase"; settings.validate()
    source = Path(path) if path else settings.path("participant_mapping")
    if not source.exists(): raise FileNotFoundError(f"Participant mapping not found: {source}")
    repo = SupabaseRepository(settings); imported = returning = 0
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            name = (row.get("name") or "").strip(); roll = (row.get("roll_number") or "").strip(); speaker_id = (row.get("speaker_id") or "").strip().upper()
            if not (name and roll and speaker_id): raise ValueError("Each mapping row must have name, roll_number, and speaker_id columns with values.")
            result = repo.client.rpc("import_local_participant", {"p_name": name, "p_roll_number": roll, "p_speaker_id": speaker_id}).execute().data
            if isinstance(result, list): result = result[0]
            if result.get("is_returning"): returning += 1
            else: imported += 1
    return {"imported": imported, "already_present": returning}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate the old private roll-number mapping to Supabase")
    parser.add_argument("--file", help="Optional local participants.csv path")
    args = parser.parse_args()
    print(import_participants(args.file))
