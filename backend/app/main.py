from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .repository import LocalRepository, SupabaseRepository
from .security import read_token
from .service import CollectionService
from .settings import Settings
from .storage import LocalAudioStorage, SupabaseAudioStorage

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class RegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    roll_number: str = Field(min_length=1, max_length=64)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    if settings.storage_backend == "supabase":
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        repository = SupabaseRepository(settings, client)
        storage = SupabaseAudioStorage(settings, client)
    else:
        repository = LocalRepository(settings)
        storage = LocalAudioStorage(settings)
    service = CollectionService(settings, repository, storage)

    app = FastAPI(title="Multilingual Speech Collection API", version="1.0.0")
    app.state.settings = settings
    app.state.collection_service = service
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])

    def participant_id(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Register to continue.")
        try: return read_token(authorization[7:], settings.app_secret_key)
        except ValueError as exc: raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.get("/api/health")
    def health(): return {"ok": True, "storage": settings.storage_backend}

    @app.post("/api/participants/register")
    def register(body: RegistrationRequest):
        try: return service.register(body.name, body.roll_number)
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc: raise HTTPException(status_code=503, detail="Participant registration could not be saved.") from exc

    @app.get("/api/sessions/{language}/{session_number}")
    def session(language: str, session_number: int, participant: str = Depends(participant_id)):
        try: return service.session(participant, language.lower(), session_number)
        except FileNotFoundError as exc: raise HTTPException(status_code=503, detail="The prompt file is not available.") from exc
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc: raise HTTPException(status_code=503, detail="Could not load the selected session.") from exc

    @app.put("/api/recordings/{language}/{session_number}/{utterance_number}")
    async def upload(language: str, session_number: int, utterance_number: int, request: Request, participant: str = Depends(participant_id)):
        try: size = int(request.headers.get("content-length", "0"))
        except ValueError: raise HTTPException(status_code=400, detail="Invalid upload length.")
        if size < 1 or size > MAX_UPLOAD_BYTES: raise HTTPException(status_code=413, detail="Upload is empty or exceeds the 10 MB limit.")
        payload = await request.body()
        try: return await run_in_threadpool(service.upload, participant, language.lower(), session_number, utterance_number, payload)
        except FileExistsError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc: raise HTTPException(status_code=503, detail="Upload failed. Your recording was not marked complete; please retry.") from exc

    return app


app = create_app()
