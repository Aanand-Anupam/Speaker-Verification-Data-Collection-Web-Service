"""Advance Supabase ID allocation beyond IDs already present in local data."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.repository import SupabaseRepository
from backend.app.settings import Settings
from tools.common.core import SPEAKER_COLUMNS, read_rows

SID = re.compile(r"^S(\d{3,})$", re.I)


def advance(settings=None):
    settings = settings or Settings.from_env(); settings.storage_backend = "supabase"; settings.validate()
    values = []
    for row in read_rows(settings.path("metadata") / "speakers.csv", SPEAKER_COLUMNS):
        match = SID.fullmatch(row.get("speaker_id", ""))
        if match: values.append(int(match.group(1)))
    raw = settings.path("raw")
    if raw.exists():
        for directory in raw.iterdir():
            match = SID.fullmatch(directory.name)
            if match: values.append(int(match.group(1)))
    mapping = settings.path("participant_mapping")
    for row in read_rows(mapping, ["speaker_id"]):
        match = SID.fullmatch(row.get("speaker_id", ""))
        if match: values.append(int(match.group(1)))
    maximum = max(values, default=0)
    if maximum: SupabaseRepository(settings).client.rpc("advance_speaker_id_sequence", {"p_minimum": maximum}).execute()
    return maximum


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prevent cloud Speaker ID collisions with existing local data")
    parser.parse_args()
    maximum = advance()
    print(f"Supabase Speaker ID sequence advanced beyond local S{maximum:03d}" if maximum else "No existing local Speaker IDs were found; Supabase will begin at S001.")
