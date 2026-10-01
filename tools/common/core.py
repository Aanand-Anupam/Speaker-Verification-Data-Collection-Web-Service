from __future__ import annotations
import csv, logging, re, shutil, subprocess
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = ("english", "hindi", "telugu", "khasi")
SPEAKER_COLUMNS = ["speaker_id", *LANGUAGES, "consent_status", "notes"]
SESSION_COLUMNS = ["session_id", "speaker_id", "session_number", "date", "device_id", "environment", "notes"]
UTTERANCE_COLUMNS = ["utterance_id", "speaker_id", "language", "session_id", "utterance_type", "duration_seconds", "sample_rate", "channels", "raw_path", "processed_path", "quality_status", "notes"]

def load_config(path=None):
    p = Path(path) if path else ROOT / "config.yaml"
    with p.open(encoding="utf-8") as f: cfg = yaml.safe_load(f) or {}
    cfg["_root"] = p.resolve().parent
    return cfg

def project_path(cfg, key): return Path(cfg["_root"]) / cfg["paths"][key]
def relpath(path, cfg):
    try: return Path(path).resolve().relative_to(Path(cfg["_root"]).resolve()).as_posix()
    except ValueError: return Path(path).as_posix()

def read_rows(path, columns):
    p=Path(path)
    if not p.exists(): return []
    with p.open(newline="",encoding="utf-8-sig") as f:
        return [{c: row.get(c, "") or "" for c in columns} for row in csv.DictReader(f)]

def write_rows(path, rows, columns):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def parse_filename(path):
    stem=Path(path).stem
    m=re.fullmatch(r"(?P<speaker>[A-Za-z0-9-]+)_(?P<language>english|hindi|telugu|khasi)_S(?P<session>\d+)_(?P<utterance>U\d+|SP\d+)",stem,re.I)
    if not m: return None
    d=m.groupdict(); d["speaker"]=d["speaker"].upper(); d["language"]=d["language"].lower(); d["session_number"]=int(d["session"]); d["utterance_type"]="spontaneous" if d["utterance"].upper().startswith("SP") else "read"
    return d

def audio_info(path):
    import soundfile as sf
    info=sf.info(str(path))
    return {"duration_seconds": float(info.duration), "sample_rate": int(info.samplerate), "channels": int(info.channels), "format": info.format, "subtype": info.subtype}

def ffmpeg_path(): return shutil.which("ffmpeg")

def setup_logging(): logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
