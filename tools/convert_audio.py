import argparse, logging, subprocess, shutil
from common.core import *
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x,**kw): return x

def convert(config=None, force=False):
    cfg=load_config(config); raw=project_path(cfg,"raw"); dest=project_path(cfg,"processed"); supported={x.lower() for x in cfg["audio"]["supported_extensions"]}; files=sorted(p for p in raw.rglob("*") if p.is_file() and p.suffix.lower() in supported)
    exe=ffmpeg_path()
    converted=failed=skipped=0
    for src in tqdm(files,desc="Converting audio"):
        target=dest/src.relative_to(raw).with_suffix(".wav"); target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and not force: skipped+=1; continue
        if not exe and src.suffix.lower()==".wav":
            try:
                info=audio_info(src)
                if info["sample_rate"]==int(cfg["audio"]["sample_rate"]) and info["channels"]==int(cfg["audio"]["channels"]) and info["subtype"]=="PCM_16":
                    shutil.copy2(src,target); converted+=1; continue
            except Exception: pass
        if not exe:
            logging.error("FFmpeg is required to convert %s. Install FFmpeg and reopen the terminal.",src); failed+=1; continue
        cmd=[exe,"-nostdin","-v","error","-y" if force else "-n","-i",str(src),"-ac",str(cfg["audio"]["channels"]),"-ar",str(cfg["audio"]["sample_rate"]),"-sample_fmt","s16","-c:a","pcm_s16le",str(target)]
        try:
            result=subprocess.run(cmd,capture_output=True,text=True)
            if result.returncode: logging.error("Conversion failed for %s: %s",src,result.stderr.strip()); failed+=1
            else: converted+=1
        except Exception as e: logging.exception("Conversion failed for %s",src); failed+=1
    return {"converted":converted,"failed":failed,"skipped":skipped}

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--config"); p.add_argument("--force",action="store_true"); a=p.parse_args(); setup_logging()
    try: print(convert(a.config,a.force))
    except RuntimeError as e: p.error(str(e))
