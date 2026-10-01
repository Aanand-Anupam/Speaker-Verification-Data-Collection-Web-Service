# Collection workflow

1. Have the researcher explain the study and obtain consent before recording.
2. Validate the prompt files with native speakers. Session 1 needs exactly ten shared sentences; Session 2 needs 100–150 unique `sentence_id<TAB>sentence` rows.
3. Start the React site and FastAPI service locally, or deploy the Vercel frontend with the Render API and Supabase environment configured.
4. The participant enters only their name and roll number. The service reuses the roll-number mapping or assigns the next internal Speaker ID.
5. The participant chooses a language and one of two sessions. Session 2 draws ten unique sentences and stores the exact assignment before recording.
6. Each utterance is encoded and validated as 16 kHz mono PCM-16 WAV. The service stores audio without overwrite and marks the prompt complete only after the storage write succeeds.
7. For cloud collection, a researcher runs `python tools/sync_supabase.py` to copy completed audio and prompt metadata into `data/raw/` and `data/metadata/`.
8. Run `python tools/pipeline.py` to validate and standardize the recordings and generate local dataset reports.

Names and roll numbers stay in the separate private mapping/database. Session dates, devices, and environments are not invented; they remain blank unless the researcher records accurate values.
