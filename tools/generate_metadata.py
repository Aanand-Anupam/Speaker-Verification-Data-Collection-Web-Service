import argparse
from common.core import *
from quality_check import QUALITY_COLUMNS

def generate(config=None):
    cfg=load_config(config); raw=project_path(cfg,"raw"); processed=project_path(cfg,"processed"); meta=project_path(cfg,"metadata"); meta.mkdir(parents=True,exist_ok=True)
    speakers=read_rows(meta/"speakers.csv",SPEAKER_COLUMNS); byid={x["speaker_id"].upper():x for x in speakers}
    old_utterances=read_rows(meta/"utterances.csv",UTTERANCE_COLUMNS)
    old_notes={(r.get("speaker_id"),r.get("language"),r.get("utterance_id"),r.get("raw_path")):r.get("notes","") for r in old_utterances}
    sessions=read_rows(meta/"sessions.csv",SESSION_COLUMNS); old_sessions={x["session_id"]:x for x in sessions}
    quality={x["file_path"]:x.get("status","") for x in read_rows(meta/"quality_report.csv",QUALITY_COLUMNS)}
    utterances=[]; found_sessions=set()
    for p in sorted(raw.rglob("*") if raw.exists() else []):
        if not p.is_file(): continue
        d=parse_filename(p)
        if not d: continue
        sid=d["speaker"]; lang=d["language"]; num=d["session_number"]; sess=f"{sid}_SESS{num:02d}"; found_sessions.add(sess)
        sr=ch=duration=""
        try:
            inf=audio_info(p); duration=inf["duration_seconds"]; sr=inf["sample_rate"]; ch=inf["channels"]
        except Exception: pass
        proc=processed/p.relative_to(raw).with_suffix(".wav")
        if sid not in byid:
            row={c:"" for c in SPEAKER_COLUMNS}; row.update(speaker_id=sid,consent_status="pending"); byid[sid]=row
        byid[sid][lang]="1"
        raw_rel=relpath(p,cfg)
        utterances.append(dict(utterance_id=p.stem,speaker_id=sid,language=lang,session_id=sess,utterance_type=d["utterance_type"],duration_seconds=duration,sample_rate=sr,channels=ch,raw_path=raw_rel,processed_path=relpath(proc,cfg) if proc.exists() else "",quality_status=quality.get(relpath(proc,cfg),""),notes=old_notes.get((sid,lang,p.stem,raw_rel),"")))
    # A raw record is the canonical utterance row; stable ID/path key makes refresh idempotent.
    unique={ (r["speaker_id"],r["language"],r["utterance_id"],r["raw_path"]):r for r in utterances }
    for sess in sorted(found_sessions):
        if sess not in old_sessions:
            bits=sess.rsplit("_SESS",1); old_sessions[sess]={c:"" for c in SESSION_COLUMNS}; old_sessions[sess].update(session_id=sess,speaker_id=bits[0],session_number=int(bits[1]))
    write_rows(meta/"speakers.csv",list(byid.values()),SPEAKER_COLUMNS)
    write_rows(meta/"sessions.csv",list(old_sessions.values()),SESSION_COLUMNS)
    write_rows(meta/"utterances.csv",list(unique.values()),UTTERANCE_COLUMNS)
    return len(unique)

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--config"); a=p.parse_args(); print(f"Utterance rows: {generate(a.config)}")
