import io
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.prompts import PromptUnavailable, load_prompts
from backend.app.repository import LocalRepository
from backend.app.settings import Settings


PROJECT = Path(__file__).resolve().parents[1]


def local_settings(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT / "config.yaml", tmp_path / "config.yaml")
    shutil.copytree(PROJECT / "scripts", tmp_path / "scripts")
    config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    return Settings(project_root=tmp_path, storage_backend="local", app_secret_key="local-tests-secret-at-least-32-chars", config=config)


def wav_bytes(rate=16000, channels=1, duration=0.25):
    samples = np.sin(np.arange(int(rate * duration)) * 0.07).astype("float32") * 0.2
    if channels > 1: samples = np.column_stack([samples] * channels)
    output = io.BytesIO()
    sf.write(output, samples, rate, format="WAV", subtype="PCM_16")
    return output.getvalue()


def test_local_registration_ids_and_duplicate_roll(tmp_path):
    settings = local_settings(tmp_path); repo = LocalRepository(settings)
    first = repo.register_participant("Example Name", "23CS001")
    returning = repo.register_participant("Example Name", " 23cs001 ")
    other = repo.register_participant("Another Name", "23CS002")
    assert first["speaker_id"] == returning["speaker_id"] == "S001"
    assert returning["is_returning"] is True and other["speaker_id"] == "S002"
    pii = settings.path("participant_mapping").read_text(encoding="utf-8")
    public_meta = (settings.path("metadata") / "speakers.csv").read_text(encoding="utf-8")
    assert "23CS001" in pii and "Example Name" in pii
    assert "23CS001" not in public_meta and "Example Name" not in public_meta


def test_prompt_pools_and_session_two_resume(tmp_path):
    settings = local_settings(tmp_path); repo = LocalRepository(settings)
    first = repo.register_participant("One", "R1"); second = repo.register_participant("Two", "R2")
    common = load_prompts(settings, "english", 1)
    pool = load_prompts(settings, "english", 2)
    assert len(common) == 10 and len(pool) == 100
    canonical = repo.ensure_assignment(first["participant_id"], "english", 1, common)
    script = settings.path("scripts") / "english" / "session_1.txt"
    script.write_text("Changed after collection began.\n" + "\n".join(item["sentence_text"] for item in common[1:]), encoding="utf-8")
    same_common = repo.ensure_assignment(second["participant_id"], "english", 1, load_prompts(settings, "english", 1))
    assert [item["sentence_text"] for item in canonical] == [item["sentence_text"] for item in same_common]
    assigned = repo.ensure_assignment(first["participant_id"], "english", 2, pool)
    resumed = repo.ensure_assignment(first["participant_id"], "english", 2, list(reversed(pool)))
    other = repo.ensure_assignment(second["participant_id"], "english", 2, pool)
    assert [x["sentence_id"] for x in assigned] == [x["sentence_id"] for x in resumed]
    assert len({x["sentence_id"] for x in assigned}) == 10
    assert len({x["sentence_text"] for x in assigned}) == 10
    assert len(other) == 10
    assert len(load_prompts(settings, "hindi", 1)) == 10


def test_upload_validation_and_metadata_only_complete_after_success(tmp_path):
    settings = local_settings(tmp_path); client = TestClient(create_app(settings))
    registered = client.post("/api/participants/register", json={"name": "Participant", "roll_number": "T001"})
    assert registered.status_code == 200
    assert "speaker_id" not in registered.json()
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "audio/wav"}
    session = client.get("/api/sessions/english/1", headers=headers).json()
    assert session["total"] == 10 and session["utterances"][0]["status"] == "missing"
    invalid = client.put("/api/recordings/english/1/1", content=wav_bytes(rate=22050), headers=headers)
    assert invalid.status_code == 422
    unchanged = client.get("/api/sessions/english/1", headers=headers).json()
    assert unchanged["utterances"][0]["status"] == "missing"
    saved = client.put("/api/recordings/english/1/1", content=wav_bytes(), headers=headers)
    assert saved.status_code == 200 and saved.json()["uploaded"] is True
    resumed = client.get("/api/sessions/english/1", headers=headers).json()
    assert resumed["utterances"][0]["status"] == "completed"
    duplicate = client.put("/api/recordings/english/1/1", content=wav_bytes(), headers=headers)
    assert duplicate.status_code == 409
    assignments = (settings.path("metadata") / "recording_assignments.csv").read_text(encoding="utf-8")
    assert "C01" in assignments and "Participant" not in assignments and "T001" not in assignments


class FakeResult:
    def __init__(self, data): self.data = data


class FakeRpc:
    def __init__(self, data): self.data = data
    def execute(self): return FakeResult(self.data)


class FakeTable:
    def __init__(self, participant): self.person = participant
    def select(self, *_): return self
    def eq(self, *_): return self
    def limit(self, *_): return self
    def execute(self): return FakeResult([self.person])


class FakeSupabase:
    def __init__(self, registration, assignments):
        self.registration, self.assignments = registration, assignments
    def rpc(self, name, args):
        if name == "register_participant":
            assert set(args) == {"p_name", "p_roll_number"}
            return FakeRpc(self.registration)
        assert name == "assign_session_prompts"
        assert set(args) == {"p_participant_id", "p_language", "p_session_number", "p_prompts"}
        assert len(args["p_prompts"]) == 10
        return FakeRpc(self.assignments)
    def table(self, name):
        assert name == "participants"
        return FakeTable({"participant_id": "participant-1", "speaker_id": "S001"})


def test_supabase_rpc_jsonb_object_and_assignment_table_shapes(tmp_path):
    from backend.app.repository import SupabaseRepository
    settings = local_settings(tmp_path)
    prompts = load_prompts(settings, "english", 1)
    rows = [{"utterance_number": i, "sentence_id": p["sentence_id"], "sentence_text": p["sentence_text"], "status": "missing", "storage_path": None, "duration_seconds": None} for i, p in enumerate(prompts, 1)]
    repo = SupabaseRepository(settings, FakeSupabase({"participant_id": "participant-1", "speaker_id": "S001", "is_returning": False}, rows))
    registered = repo.register_participant("Example", "R001")
    assigned = repo.ensure_assignment("participant-1", "english", 1, prompts)
    assert registered["speaker_id"] == "S001" and registered["is_returning"] is False
    assert len(assigned) == 10 and assigned[0]["raw_path"].endswith("U01.wav")


@pytest.mark.parametrize("response", ["", "not json", [], {"speaker_id": "S001"}])
def test_supabase_registration_rejects_malformed_rpc_response(tmp_path, response):
    from backend.app.repository import SupabaseRepository
    repo = SupabaseRepository(local_settings(tmp_path), FakeSupabase(response, []))
    with pytest.raises(RuntimeError): repo.register_participant("Example", "R001")


def test_supabase_assignment_rejects_wrong_rpc_return_type(tmp_path):
    from backend.app.repository import SupabaseRepository
    settings = local_settings(tmp_path)
    repo = SupabaseRepository(settings, FakeSupabase({}, {"assign_session_prompts": []}))
    with pytest.raises(RuntimeError): repo.ensure_assignment("participant-1", "english", 1, load_prompts(settings, "english", 1))


def test_session_requires_authorization_and_returns_safe_prompt_error(tmp_path):
    settings = local_settings(tmp_path); client = TestClient(create_app(settings))
    assert client.get("/api/sessions/english/1").status_code == 401
    registered = client.post("/api/participants/register", json={"name": "Participant", "roll_number": "T002"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    assert client.get("/api/sessions/english/1", headers=headers).status_code == 200
    (settings.path("scripts") / "hindi" / "session_1.txt").write_text("TODO native review\n" * 10, encoding="utf-8")
    response = client.get("/api/sessions/hindi/1", headers=headers)
    assert response.status_code == 503 and "TODO" not in response.text


def test_production_settings_accept_legacy_key_and_reject_empty_or_placeholder(monkeypatch, tmp_path):
    from backend.app.settings import Settings
    legacy_key = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature"
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", legacy_key)
    monkeypatch.setenv("PROJECT_ROOT", str(PROJECT))
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("APP_SECRET_KEY", "a" * 40)
    settings = Settings.from_env()
    settings.validate()
    settings.supabase_service_role_key = "sb_secret_" + "x" * 30
    settings.validate()
    for key, url in [("", "https://project.supabase.co"), ("server-only-secret-key", "https://project.supabase.co"), ("x" * 40, "https://project.supabase.co"), ("sb_secret_" + "x" * 30, "your-project.supabase.co")]:
        invalid = local_settings(tmp_path / str(len(key) + len(url)))
        invalid.storage_backend = "supabase"
        invalid.supabase_url = url
        invalid.supabase_service_role_key = key
        invalid.app_secret_key = "a" * 40
        with pytest.raises(ValueError): invalid.validate()
