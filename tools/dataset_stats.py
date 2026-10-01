import argparse, itertools
from collections import Counter, defaultdict
from common.core import *

def generate(config=None):
    cfg=load_config(config); meta=project_path(cfg,"metadata"); sp=read_rows(meta/"speakers.csv",SPEAKER_COLUMNS); utt=read_rows(meta/"utterances.csv",UTTERANCE_COLUMNS); quality=read_rows(meta/"quality_report.csv",["file_path","status"]); qmap={x["file_path"]:x["status"] for x in quality}
    durations=[]; bylang=defaultdict(list); sp_lang=Counter(); utter_lang=Counter()
    for row in sp:
        for lang in LANGUAGES:
            if row.get(lang,"").strip().lower() in ("1","true","yes","y"): sp_lang[lang]+=1
    for r in utt:
        lang=r.get("language",""); utter_lang[lang]+=1
        try: d=float(r["duration_seconds"]); durations.append(d); bylang[lang].append(d)
        except (ValueError,TypeError): pass
    combinations=Counter()
    for r in sp:
        present=tuple(l for l in LANGUAGES if r.get(l,"").strip().lower() in ("1","true","yes","y"))
        if present: combinations[" + ".join(present)]+=1
    recording_per=Counter(r.get("speaker_id","") for r in utt)
    statuses=Counter(qmap.get(r.get("processed_path", ""),"") for r in utt)
    rows=[]
    def add(metric,dimension,value): rows.append({"metric":metric,"dimension":dimension,"value":value})
    add("total_speakers","all",len(sp)); add("total_utterances","all",len(utt)); add("total_duration_seconds","all",sum(durations)); add("number_of_sessions","all",len(read_rows(meta/"sessions.csv",SESSION_COLUMNS)))
    for l in LANGUAGES:
        add("speakers_per_language",l,sp_lang[l]); add("utterances_per_language",l,utter_lang[l]); add("duration_per_language_seconds",l,sum(bylang[l]))
    for combination,count in combinations.items(): add("multilingual_overlap",combination,count)
    for speaker,count in recording_per.items(): add("recordings_per_speaker",speaker,count)
    for name,val in (("average_utterance_duration_seconds",sum(durations)/len(durations) if durations else 0),("min_utterance_duration_seconds",min(durations) if durations else 0),("max_utterance_duration_seconds",max(durations) if durations else 0)): add(name,"all",val)
    for status in ("PASS","WARNING","FAIL"): add("quality_recordings",status,statuses[status])
    write_rows(meta/"dataset_statistics.csv",rows,["metric","dimension","value"])
    lines=["Dataset statistics",f"Speakers: {len(sp)}",f"Utterances: {len(utt)}",f"Total duration (seconds): {sum(durations):.2f}","Speakers by language: "+", ".join(f"{l}={sp_lang[l]}" for l in LANGUAGES),"Multilingual overlap: "+", ".join(f"{k}={v}" for k,v in combinations.items())]
    (meta/"dataset_report.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return rows

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--config"); a=p.parse_args(); generate(a.config); print("Wrote dataset statistics")
