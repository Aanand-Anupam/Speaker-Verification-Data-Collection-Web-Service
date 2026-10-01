import argparse, re
from pathlib import Path
from common.core import *

def register(speaker_id, languages, config=None):
    cfg=load_config(config); sid=speaker_id.strip().upper()
    if not re.fullmatch(r"S\d{3,}",sid): raise ValueError("speaker ID must match S followed by at least three digits (for example S001)")
    langs=[x.lower() for x in languages]
    bad=set(langs)-set(LANGUAGES)
    if bad: raise ValueError(f"unknown language(s): {', '.join(sorted(bad))}")
    if len(set(langs))!=len(langs): raise ValueError("languages must not be repeated")
    meta=project_path(cfg,"metadata"); path=meta/"speakers.csv"; rows=read_rows(path,SPEAKER_COLUMNS)
    row=next((r for r in rows if r["speaker_id"].upper()==sid),None)
    if row is None:
        row={c:"" for c in SPEAKER_COLUMNS}; row.update(speaker_id=sid,consent_status="pending"); rows.append(row)
    for lang in langs: row[lang]="1"
    write_rows(path,rows,SPEAKER_COLUMNS)
    for lang in langs:
        for n in range(1,int(cfg["recording"]["sessions_per_language"])+1):
            (project_path(cfg,"raw")/sid/lang/f"session_{n}").mkdir(parents=True,exist_ok=True)
    return sid

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--speaker-id",required=True); p.add_argument("--languages",nargs="+",required=True); p.add_argument("--config"); a=p.parse_args(); setup_logging()
    try: print(f"Registered {register(a.speaker_id,a.languages,a.config)}")
    except ValueError as e: p.error(str(e))
