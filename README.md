# Multilingual Speaker Verification — Data Collection and Preparation

This project collects read speech through a browser and prepares those recordings for the existing local Python dataset pipeline. It does not train or run speaker models.

```text
React/Vite browser → FastAPI → local files (development)
                            ↘ Supabase PostgreSQL + private Storage (deployment)
                                  ↓ sync
                              data/raw/
                                  ↓ python tools/pipeline.py
                              data/processed/ + local reports
```

## Study design

Each speaker-language has exactly two sessions of ten read utterances. Session 1 uses the same ten common sentences for everyone in that language. Session 2 randomly assigns ten unique sentences from a pool of 100–150; the assignments are saved and reused when a participant resumes.

Current prompt-material status:

| Language | Session 1 | Session 2 |
|---|---|---|
| English | 10 sentences available | 100 sentence pool available |
| Hindi | Native-reviewed text required | Native-reviewed pool required |
| Telugu | Native-reviewed text required | Native-reviewed pool required |
| Khasi | Native-reviewed text required | Native-reviewed pool required |

The Hindi, Telugu, and Khasi files are clearly marked TODO placeholders. The API refuses to start a session from placeholder text. Have native speakers validate exactly ten Session 1 sentences and 100–150 unique Session 2 sentences before collection in those languages. Store Session 2 pools as UTF-8 rows in `sentence_id<TAB>sentence_text` format. Do not edit English prompts after collection begins: the first accepted Session 1 version is persisted as the canonical shared script.

Targets remain speaker-language memberships in `config.yaml`: English 100, Hindi 60–70, Telugu 30, Khasi 20. One participant may contribute to more than one language.

## Repository layout

```text
backend/app/                 FastAPI API, local/Supabase repositories and storage
frontend/                    React + Vite participant website
supabase/schema.sql          Database tables, restricted RPCs and private bucket
scripts/<language>/          Common scripts and randomized sentence pools
tools/sync_supabase.py       Cloud audio and metadata download
tools/import_local_participants.py  Optional old local identity-map migration
tools/advance_supabase_speaker_ids.py  Avoid IDs colliding with local raw data
tools/pipeline.py            Existing local processing pipeline (unchanged)
data/raw/                    Pipeline input after local collection or cloud sync
data/processed/              Standardized pipeline output
data/metadata/               Pipeline reports and sentence assignment metadata
data/private/                Local participant identity and assignment files; Git-ignored
tests/                       Pipeline and collection tests; no microphone required
```

Participant names and roll numbers are kept in the private `participants` table (cloud) or `data/private/participants.csv` (local). Audio objects, speaker records, and recording-assignment metadata use internal Speaker IDs and do not include names or roll numbers. The Supabase service key is only used by FastAPI and the researcher’s sync/import commands, never by the browser. Supabase recommends keeping secret keys server-side; they bypass Row Level Security and must not be exposed to clients ([Supabase RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security)).

## Local setup

Use PowerShell from the project root. Python and Node.js must be installed. All Python packages install into the project-local `.venv`:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -c "import sys; print(sys.executable)"
```

The final command should point to `.venv\Scripts\python.exe`. Copy `.env.example` to `.env` for local settings if needed. `.env` is Git-ignored. Local API mode is the default and requires no Supabase account:

```text
STORAGE_BACKEND=local
```

Open two PowerShell terminals from the repository root. In terminal 1, start the API:

```powershell
.venv\Scripts\activate
uvicorn backend.app.main:app --reload --port 8001
```

In terminal 2, start Vite:

```powershell
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite, usually `http://localhost:5173`. Vite proxies `/api` calls to FastAPI at port 8001. The earlier local recorder used port 8000, so this keeps both tools from contending for the same port. Microphone access works on localhost; deployed or phone access requires HTTPS.

## Participant workflow

1. Enter a name and roll number. Participants never enter or select a Speaker ID.
2. The backend reuses the existing internal ID for a returning roll number or assigns the next available `S001`, `S002`, etc.
3. Choose a language and Session 1 or 2.
4. The browser displays one assigned sentence at a time. Session 2 selections remain the same after reload or re-registration.
5. Record and stop early, or let recording stop at the configured 30-second limit. The browser creates mono 16 kHz, 16-bit PCM WAV.
6. The API validates the uploaded WAV, stores it without overwriting an existing utterance, then marks it complete. A failed upload remains incomplete and can be retried.

Names, roll numbers, and Speaker IDs are linked only by the backend. Do not expose participant database rows or service keys to the browser.

## Supabase setup

1. Create a Supabase project.
2. Run [`supabase/schema.sql`](supabase/schema.sql) once in the Supabase SQL Editor. It creates participant, session, common-prompt and utterance tables, protected registration/assignment functions, and a **private** `speaker-audio` bucket.
3. In Render, set `STORAGE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_AUDIO_BUCKET=speaker-audio`, `APP_SECRET_KEY`, and `ALLOWED_ORIGINS`. Use the server-only secret key (or legacy service-role key); never put it in a `VITE_` variable or frontend file.
4. `APP_SECRET_KEY` must be a random value of at least 32 characters. Render’s `render.yaml` generates one for a new service.
5. Before opening cloud registration, advance the ID allocator past any existing local speakers. If `data/private/participants.csv` exists, import its mapping first to preserve participant-to-ID links:

   ```powershell
   .venv\Scripts\activate
   python tools/advance_supabase_speaker_ids.py
   python tools/import_local_participants.py
   ```

   The sequence check scans local participant mappings, `speakers.csv`, and `data/raw/` speaker folders. The import sends only the existing name/roll/Speaker ID mapping to the private Supabase participant table. Neither command uploads audio. The import is idempotent for matching roll and speaker-ID pairs and refuses conflicting mappings. If no local participant mapping exists, run only the sequence check.

For a new Supabase project, there is no separate PostgreSQL connection string to place in the app; the backend uses Supabase’s server-side API client. The service role/secret key is restricted to backend environment variables. Storage and database rows are not publicly readable.

## Deploy

### FastAPI on Render

1. Push this repository to a Git provider connected to Render.
2. Create a Render Blueprint from the repository using `render.yaml` (repository root as the service root). It builds `backend/requirements.txt` and starts `backend.app.main:app`.
3. Supply `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, and `ALLOWED_ORIGINS` in the Render service environment. Set `ALLOWED_ORIGINS` to the exact Vercel site origin, for example `https://your-project.vercel.app`.
4. Wait for `/api/health` to report `ok: true` and `storage: supabase`.

The included Blueprint uses Render’s Free web-service plan. Free services can spin down while idle; the first request after idle can take longer. Upgrade the service plan in Render if collection needs an always-on API ([Render Free plan notes](https://render.com/docs/free)).

### React/Vite on Vercel

1. Import the same repository into Vercel.
2. Set the Vercel project root directory to `frontend`; Vercel uses the checked-in Vite build configuration and outputs `dist`.
3. Set the build environment variable `VITE_API_BASE_URL` to the HTTPS Render API base URL, without a trailing slash.
4. Deploy, then set that deployment’s origin in Render’s `ALLOWED_ORIGINS` and redeploy the API.
5. Open the Vercel HTTPS URL and test registration, one short recording, resume, and a second participant before study collection.

The Vercel `frontend/vercel.json` configures the Vite build output; Vercel’s `outputDirectory` setting is the standard way to point deployment at a custom build directory ([Vercel configuration](https://vercel.com/docs/project-configuration/vercel-json)).

## Download cloud data and run the existing pipeline

For a local cloud sync, set `STORAGE_BACKEND=supabase`, `SUPABASE_URL`, and `SUPABASE_SECRET_KEY` in the researcher’s ignored local `.env`, then run from the repository root:

```powershell
.venv\Scripts\activate
python tools/sync_supabase.py
```

The sync downloads completed private Storage objects into their existing layout under `data/raw/<speaker_id>/<language>/session_<n>/`. It skips raw files that already exist, so it does not overwrite local recordings. It also refreshes privacy-safe `speakers.csv`, `sessions.csv`, and `recording_assignments.csv` in `data/metadata/`. Sentence IDs and exact assigned text are retained there. Participant names and roll numbers are not downloaded. Sync can be repeated safely. Use `python tools/sync_supabase.py --dry-run` to count cloud assignments first.

Then run the unchanged preparation pipeline:

```powershell
python tools/pipeline.py
```

It continues to validate raw audio, standardize files into `data/processed/`, run quality checks, generate metadata/statistics, and track targets. Browser recordings are already WAV/16 kHz/mono/PCM-16, while the existing conversion stage remains safe for any other supported raw formats.

## Tests

From the repository root with `.venv` active:

```powershell
pytest
```

Tests cover existing pipeline behavior, participant registration and ID reuse, prompt-pool validation, randomized assignment persistence and uniqueness, upload format validation, no-overwrite behavior, metadata privacy, and API registration/session/upload routes. Synthetic WAVs are generated in temporary directories; no microphone hardware is used.

## Data integrity notes

- Raw recordings are preserved; cloud sync skips existing destination files.
- Session 2 assignments are persisted before the participant starts recording.
- A sentence is complete only after storage succeeds and metadata is updated.
- Uploads must decode as WAV, 16 kHz, mono, 16-bit PCM and stay under the configured time and request-size limits.
- Names and roll numbers are private identity data. Back up and limit access to the local mapping or Supabase project.
- Native reviewers must validate the non-English prompt material before collection begins in those languages.
- Set the Vercel origin exactly in FastAPI CORS configuration; do not use a wildcard in production.
