import argparse, csv, json, logging
from pathlib import Path
from common.core import *

def validate(config=None):
    cfg=load_config(config); raw=project_path(cfg,"raw"); allowed={x.lower() for x in cfg["audio"]["supported_extensions"]}; out=[]
    files=sorted(p for p in raw.rglob("*") if p.is_file() and p.name!=".gitkeep") if raw.exists() else []
    for p in files:
        issues=[]; info={}; ext=p.suffix.lower(); parsed=parse_filename(p)
        if ext not in allowed: issues.append("UNSUPPORTED_FORMAT")
        if not parsed: issues.append("SUSPICIOUS_FILENAME")
        else:
            parts=[x.lower() for x in p.relative_to(raw).parts]
            if len(parts)<4 or parts[0]!=parsed["speaker"].lower() or parts[1]!=parsed["language"] or parts[2]!=f"session_{parsed['session_number']}": issues.append("DIRECTORY_MISMATCH")
        readable=False
        try:
            if ext==".wav" or ext==".flac":
                import soundfile as sf
                info=audio_info(p)
                with sf.SoundFile(str(p)) as audio:
                    while audio.read(65536,dtype="float32").size: pass
                readable=True
            elif ffmpeg_path():
                probe=subprocess.run([ffmpeg_path(),"-v","error","-i",str(p),"-f","null","-"],capture_output=True,text=True)
                if probe.returncode: issues.append("DECODE_ERROR")
                else:
                    # ffprobe is usually installed alongside FFmpeg; use it for metadata.
                    exe=shutil.which("ffprobe")
                    if exe:
                        probe=subprocess.run([exe,"-v","error","-select_streams","a:0","-show_entries","stream=sample_rate,channels:format=duration","-of","json",str(p)],capture_output=True,text=True,check=True)
                        metadata=json.loads(probe.stdout); streams=metadata.get("streams",[]); duration=metadata.get("format",{}).get("duration")
                        if not streams or duration is None: issues.append("METADATA_UNAVAILABLE")
                        else:
                            info={"duration_seconds":float(duration),"sample_rate":int(streams[0]["sample_rate"]),"channels":int(streams[0]["channels"])}; readable=True
                    else: issues.append("METADATA_UNAVAILABLE")
            else: issues.append("FFMPEG_UNAVAILABLE")
        except Exception as e: issues.append("UNREADABLE: "+str(e))
        size=p.stat().st_size
        if size==0: issues.append("ZERO_LENGTH")
        if info.get("duration_seconds",0)<=0 and readable: issues.append("ZERO_DURATION")
        if not readable: status="INVALID"
        elif issues: status="WARNING"
        else: status="VALID"
        out.append({"file_path":relpath(p,cfg),"readable":str(readable).lower(),"format":ext.lstrip("."),"duration_seconds":info.get("duration_seconds",""),"sample_rate":info.get("sample_rate",""),"channels":info.get("channels",""),"file_size_bytes":size,"status":status,"issues":";".join(issues)})
    path=project_path(cfg,"metadata")/"audio_validation_report.csv"; write_rows(path,out,["file_path","readable","format","duration_seconds","sample_rate","channels","file_size_bytes","status","issues"])
    return out

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--config"); a=p.parse_args(); setup_logging(); rows=validate(a.config); print(f"Files discovered: {len(rows)}; valid: {sum(r['status']=='VALID' for r in rows)}; warnings: {sum(r['status']=='WARNING' for r in rows)}; invalid: {sum(r['status']=='INVALID' for r in rows)}")
