from __future__ import annotations

import re
from pathlib import Path

from .settings import Settings

PLACEHOLDER_RE = re.compile(r"\b(TODO|PLACEHOLDER|SUPPLY NATIVE|NATIVE-REVIEWED)\b", re.I)


class PromptUnavailable(ValueError): pass


def load_prompts(settings: Settings, language: str, session_number: int) -> list[dict]:
    if language not in settings.languages: raise ValueError("Unsupported language.")
    if session_number not in (1, 2): raise ValueError("Choose Session 1 or Session 2.")
    scripts = settings.path("scripts") / language
    if session_number == 1:
        path = scripts / "session_1.txt"
        if not path.exists(): raise PromptUnavailable(f"No Session 1 script is available for {language}.")
        sentences = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(sentences) != settings.utterances_per_session:
            raise PromptUnavailable(f"{language.title()} Session 1 must contain exactly {settings.utterances_per_session} sentences.")
        if any(PLACEHOLDER_RE.search(line) for line in sentences):
            raise PromptUnavailable(f"The {language.title()} Session 1 script needs native-reviewed sentences before collection.")
        return [{"sentence_id": f"C{i:02d}", "sentence_text": text} for i, text in enumerate(sentences, 1)]

    path = scripts / "session_2_pool.txt"
    if not path.exists(): raise PromptUnavailable(f"No Session 2 sentence pool is available for {language}.")
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        parts = line.split("\t", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise PromptUnavailable(f"{path.name} must contain sentence_id<TAB>sentence on each line.")
        entries.append({"sentence_id": parts[0].strip(), "sentence_text": parts[1].strip()})
    if not 100 <= len(entries) <= 150:
        raise PromptUnavailable(f"{language.title()} Session 2 pool must contain 100–150 sentences.")
    ids = [entry["sentence_id"] for entry in entries]
    texts = [entry["sentence_text"].casefold() for entry in entries]
    if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
        raise PromptUnavailable(f"{language.title()} Session 2 pool has duplicate IDs or sentence text.")
    if any(PLACEHOLDER_RE.search(entry["sentence_text"]) for entry in entries):
        raise PromptUnavailable(f"The {language.title()} Session 2 pool needs native-reviewed sentences before collection.")
    return entries
