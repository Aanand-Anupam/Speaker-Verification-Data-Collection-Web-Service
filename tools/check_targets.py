import argparse
from common.core import *

def check(config=None):
    cfg=load_config(config); rows=read_rows(project_path(cfg,"metadata")/"speakers.csv",SPEAKER_COLUMNS); result=[]
    for lang,spec in cfg["languages"].items():
        count=sum(r.get(lang,"").strip().lower() in ("1","true","yes","y") for r in rows)
        target=spec["target"]
        if isinstance(target,list): status="TARGET_REACHED" if int(target[0])<=count<=int(target[1]) else "INCOMPLETE" if count<int(target[0]) else "ABOVE_RANGE"
        else: status="TARGET_REACHED" if count>=int(target) else "INCOMPLETE"
        label=f"{target[0]}-{target[1]}" if isinstance(target,list) else str(target)
        result.append({"language":lang,"current":count,"target":label,"status":status})
    write_rows(project_path(cfg,"metadata")/"target_status.csv",result,["language","current","target","status"]); return result

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--config"); a=p.parse_args();
    for r in check(a.config): print(f"{r['language']:<10} {r['current']:>4} / {r['target']:<7} {r['status']}")
