import argparse, numpy as np
from common.core import *
QUALITY_COLUMNS=["file_path","duration_seconds","sample_rate","channels","rms_energy","peak_amplitude","silence_ratio","clipping_ratio","status","flags"]

def check(config=None):
    import soundfile as sf
    cfg=load_config(config); root=project_path(cfg,"processed"); q=cfg["quality"]; results=[]
    for p in sorted(root.rglob("*.wav")) if root.exists() else []:
        flags=[]; channels=""
        try:
            y,sr=sf.read(str(p),dtype="float32",always_2d=True); mono=y.mean(axis=1); dur=len(mono)/sr
            channels=int(y.shape[1])
            rms=float(np.sqrt(np.mean(mono**2))) if len(mono) else 0.; peak=float(np.max(np.abs(mono))) if len(mono) else 0.
            silence=float(np.mean(np.abs(mono)<0.01)) if len(mono) else 1.; clipping=float(np.mean(np.abs(mono)>=q["clipping_peak"])) if len(mono) else 0.
            if dur<float(q["min_duration_seconds"]): flags.append("TOO_SHORT")
            if dur>float(q["max_duration_seconds"]): flags.append("TOO_LONG")
            if rms<float(q["min_rms"]): flags.append("LOW_ENERGY")
            if silence>float(q["max_silence_ratio"]): flags.append("HIGH_SILENCE")
            if clipping>float(q["clipping_ratio"]): flags.append("CLIPPING")
            if sr!=int(cfg["audio"]["sample_rate"]): flags.append("WRONG_SAMPLE_RATE")
            if channels!=int(cfg["audio"]["channels"]): flags.append("WRONG_CHANNELS")
            status="FAIL" if any(x in flags for x in ("UNREADABLE","WRONG_SAMPLE_RATE","WRONG_CHANNELS","TOO_SHORT")) else "WARNING" if flags else "PASS"
        except Exception:
            dur=sr=rms=peak=silence=clipping=""; flags=["UNREADABLE"]; status="FAIL"
        results.append(dict(file_path=relpath(p,cfg),duration_seconds=dur,sample_rate=sr,channels=channels,rms_energy=rms,peak_amplitude=peak,silence_ratio=silence,clipping_ratio=clipping,status=status,flags=";".join(flags)))
    write_rows(project_path(cfg,"metadata")/"quality_report.csv",results,QUALITY_COLUMNS); return results

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--config"); a=p.parse_args(); setup_logging(); r=check(a.config); print(f"Quality checked: {len(r)}; failures: {sum(x['status']=='FAIL' for x in r)}")
