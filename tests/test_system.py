import io, json, shutil, subprocess, sys, tempfile, threading, wave
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from common.core import load_config, parse_filename, audio_info
import validate_audio
from register_speaker import register
from check_targets import check
from generate_metadata import generate
from pipeline import run
from common.participant_recording import ParticipantStore, validate_wav_payload
from recording_server import RecordingHandler

def config_at(tmp):
    source=Path(__file__).resolve().parents[1]/"config.yaml"
    cfg=tmp/"config.yaml"; cfg.write_text(source.read_text(encoding="utf-8"),encoding="utf-8")
    shutil.copytree(source.parent/"scripts",tmp/"scripts")
    return cfg

def wav_bytes(rate=16000,channels=1,duration=0.25):
    import soundfile as sf
    count=int(rate*duration)
    data=np.sin(np.arange(count)*0.05).astype("float32")*0.25
    if channels > 1: data=np.column_stack([data]*channels)
    buffer=io.BytesIO(); sf.write(buffer,data,rate,format="WAV",subtype="PCM_16")
    return buffer.getvalue()

def wav(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),"wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes((np.sin(np.arange(8000)*0.05)*12000).astype("int16").tobytes())

def test_config_and_filename():
    assert load_config()["audio"]["sample_rate"]==16000
    d=parse_filename("S001_english_S2_SP01.wav")
    assert d["session_number"]==2 and d["utterance_type"]=="spontaneous"
    assert parse_filename("bad.wav") is None

def test_validate_m4a_metadata_and_placeholder_filter(tmp_path, monkeypatch):
    cfg=config_at(tmp_path)
    raw=tmp_path/"data/raw"
    source=raw/"S001/english/session_1/S001_english_S1_U01.m4a"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    (raw/".gitkeep").touch()
    monkeypatch.setattr(validate_audio,"ffmpeg_path",lambda:"ffmpeg")
    monkeypatch.setattr(validate_audio.shutil,"which",lambda name:"ffprobe" if name=="ffprobe" else None)
    def fake_run(command,**kwargs):
        if command[0]=="ffprobe":
            output=json.dumps({"streams":[{"sample_rate":"48000","channels":1}],"format":{"duration":"9.727854"}})
            return subprocess.CompletedProcess(command,0,output,"")
        return subprocess.CompletedProcess(command,0,"","")
    monkeypatch.setattr(validate_audio.subprocess,"run",fake_run)
    rows=validate_audio.validate(cfg)
    assert len(rows)==1
    assert rows[0]["status"]=="VALID"
    assert rows[0]["duration_seconds"]==9.727854
    assert rows[0]["sample_rate"]==48000
    assert rows[0]["channels"]==1

def test_register_duplicate_and_language_validation(tmp_path):
    cfg=config_at(tmp_path)
    assert register("S001",["english","hindi"],cfg)=="S001"
    register("S001",["english"],cfg)
    rows=(tmp_path/"data/metadata/speakers.csv").read_text(encoding="utf-8")
    assert rows.count("S001") == 1
    try: register("S002",["french"],cfg)
    except ValueError: pass
    else: assert False

def test_paths_audio_targets_and_metadata_dedupe(tmp_path):
    cfg=config_at(tmp_path); register("S001",["english"],cfg)
    source=tmp_path/"data/raw/S001/english/session_1/S001_english_S1_U01.wav"; wav(source)
    assert audio_info(source)["sample_rate"]==16000
    assert generate(cfg)==1 and generate(cfg)==1
    assert len((tmp_path/"data/metadata/utterances.csv").read_text(encoding="utf-8").splitlines())==2
    result=check(cfg); english=next(r for r in result if r["language"]=="english")
    assert english["current"]==1

def test_synthetic_pilot_pipeline(tmp_path):
    cfg=config_at(tmp_path); register("S002",["english","telugu"],cfg)
    wav(tmp_path/"data/raw/S002/english/session_1/S002_english_S1_U01.wav")
    wav(tmp_path/"data/raw/S002/telugu/session_1/S002_telugu_S1_SP01.wav")
    summary=run(cfg)
    assert summary["files_discovered"]==2 and summary["converted"]==2
    assert summary["utterances"]==2
    assert (tmp_path/"data/metadata/dataset_statistics.csv").exists()

def test_participant_id_generation_and_duplicate_roll(tmp_path):
    cfg=config_at(tmp_path); store=ParticipantStore(cfg)
    first=store.participant("A Person", "23CS001")
    sid=store.speaker_for_token(first["token"])
    assert sid=="S001"
    again=store.participant("A Person", " 23cs001 ")
    assert again["existing"] is True
    assert store.speaker_for_token(again["token"])==sid
    another=store.participant("Another Person", "23CS002")
    assert store.speaker_for_token(another["token"])=="S002"
    private=(tmp_path/"data/private/participants.csv").read_text(encoding="utf-8")
    assert "23CS001" in private and "A Person" in private
    speakers=(tmp_path/"data/metadata/speakers.csv").read_text(encoding="utf-8")
    assert "23CS001" not in speakers and "A Person" not in speakers

def test_recording_paths_and_upload_validation(tmp_path):
    cfg=config_at(tmp_path); store=ParticipantStore(cfg)
    token=store.participant("Test Participant", "R001")["token"]
    plan=store.session_plan(token,"english",1)
    assert plan["prompts"][0]["utterance_id"]=="U01"
    expected=tmp_path/"data/raw/S001/english/session_1/S001_english_S1_U01.wav"
    assert store.recording_path("S001","english",1,"U01")==expected
    payload=wav_bytes()
    assert 0 < validate_wav_payload(payload) < 1
    saved=store.accept_upload(token,"english",1,"U01",payload)
    assert saved["filename"]==expected.name and expected.exists()
    try: store.accept_upload(token,"english",1,"U01",payload)
    except FileExistsError: pass
    else: assert False, "existing recordings must not be overwritten"
    try: validate_wav_payload(wav_bytes(rate=22050))
    except ValueError: pass
    else: assert False, "nonstandard audio must be rejected"

def test_recording_http_api_smoke(tmp_path):
    cfg=config_at(tmp_path)
    server=ThreadingHTTPServer(("127.0.0.1",0),RecordingHandler)
    RecordingHandler.store=ParticipantStore(cfg)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base=f"http://127.0.0.1:{server.server_address[1]}"
    try:
        page=urlopen(base+"/").read().decode("utf-8")
        assert "Participant recording" in page
        body=json.dumps({"name":"API Participant","roll_number":"API001"}).encode()
        registered=json.loads(urlopen(Request(base+"/api/register",data=body,headers={"Content-Type":"application/json"})).read())
        token=registered["token"]
        req=Request(base+"/api/session?language=english&session=1",headers={"Authorization":f"Bearer {token}"})
        plan=json.loads(urlopen(req).read())
        assert plan["prompts"][0]["utterance_id"]=="U01"
        upload=Request(base+"/api/upload",data=wav_bytes(),method="POST",headers={"Authorization":f"Bearer {token}","X-Language":"english","X-Session":"1","X-Utterance-ID":"U01","Content-Type":"audio/wav"})
        assert urlopen(upload).status==201
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
