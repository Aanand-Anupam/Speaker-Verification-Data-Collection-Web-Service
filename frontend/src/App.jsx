import { useEffect, useMemo, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const LANGUAGES = ["english", "hindi", "telugu", "khasi"];

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(body.detail || `Request failed (${response.status}).`);
  return body;
}

export default function App() {
  const [token, setToken] = useState("");
  const [returning, setReturning] = useState(false);
  const [language, setLanguage] = useState("english");
  const [session, setSession] = useState(1);
  const [plan, setPlan] = useState(null);
  const [skipped, setSkipped] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [pendingUpload, setPendingUpload] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [seconds, setSeconds] = useState(0);
  const streamRef = useRef(null);
  const contextRef = useRef(null);
  const processorRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const startedRef = useRef(0);
  const stoppingRef = useRef(false);

  const completed = useMemo(
    () =>
      plan?.utterances.filter((item) => item.status === "completed").length ||
      0,
    [plan],
  );
  const missingIndices = useMemo(
    () =>
      plan?.utterances
        .map((item, index) => (item.status !== "completed" ? index : -1))
        .filter((index) => index >= 0) || [],
    [plan],
  );
  const currentIndex = missingIndices.find((index) => !skipped.has(index));
  const current =
    currentIndex === undefined ? null : plan?.utterances[currentIndex];

  function cleanup() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    if (processorRef.current) {
      try {
        processorRef.current.disconnect();
      } catch {}
      processorRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (contextRef.current) {
      const context = contextRef.current;
      contextRef.current = null;
      context.close().catch(() => {});
    }
  }

  useEffect(() => () => cleanup(), []);

  async function register(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const result = await api("/api/participants/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.get("name"),
          roll_number: form.get("roll_number"),
        }),
      });
      setToken(result.access_token);
      setReturning(result.is_returning);
      setMessage("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadSession(event) {
    if (pendingUpload) return;
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);
    setPlan(null);
    setSkipped(new Set());
    try {
      const result = await api(`/api/sessions/${language}/${session}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setPlan(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function skipCurrent() {
    if (pendingUpload) return;
    if (currentIndex === undefined) return;
    setSkipped((old) => new Set([...old, currentIndex]));
  }

  function retrySkipped() {
    setSkipped(new Set());
  }

  async function startRecording() {
    setError("");
    setMessage("");
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError(
        "Microphone access requires HTTPS, or localhost during local development.",
      );
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const context = new (window.AudioContext || window.webkitAudioContext)();
      await context.resume();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const mute = context.createGain();
      mute.gain.value = 0;
      chunksRef.current = [];
      processor.onaudioprocess = (event) =>
        chunksRef.current.push(
          new Float32Array(event.inputBuffer.getChannelData(0)),
        );
      source.connect(processor);
      processor.connect(mute);
      mute.connect(context.destination);
      streamRef.current = stream;
      contextRef.current = context;
      processorRef.current = processor;
      startedRef.current = Date.now();
      stoppingRef.current = false;
      setSeconds(0);
      setRecording(true);
      timerRef.current = window.setInterval(() => {
        const elapsed = (Date.now() - startedRef.current) / 1000;
        setSeconds(elapsed);
        if (elapsed >= plan.max_duration_seconds) stopRecording();
      }, 200);
    } catch (e) {
      cleanup();
      setError(`Could not access the microphone: ${e.message}`);
    }
  }

  async function stopRecording() {
    if (stoppingRef.current || !contextRef.current) return;
    stoppingRef.current = true;
    setRecording(false);
    setBusy(true);
    window.clearInterval(timerRef.current);
    const context = contextRef.current;
    const rate = context.sampleRate;
    if (processorRef.current) processorRef.current.onaudioprocess = null;
    const merged = merge(chunksRef.current);
    cleanup();
    try {
      const wav = toWav(resample(merged, rate, 16000), 16000);
      const utterance = plan.utterances[currentIndex];
      const pending = {
        wav,
        language: plan.language,
        session: plan.session_number,
        utteranceNumber: utterance.utterance_number,
        token,
      };
      setPendingUpload(pending);
      await sendPendingUpload(pending);
    } catch (e) {
      setError(e.message);
      setMessage(
        "The recording could not be prepared. Please record this utterance again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function sendPendingUpload(pending = pendingUpload) {
    if (!pending) return;
    setBusy(true);
    setError("");
    setMessage("Retrying the saved recording upload…");
    try {
      await api(
        `/api/recordings/${pending.language}/${pending.session}/${pending.utteranceNumber}`,
        {
          method: "PUT",
          headers: {
            Authorization: `Bearer ${pending.token}`,
            "Content-Type": "audio/wav",
          },
          body: pending.wav,
        },
      );
      setPlan((old) =>
        old
          ? {
              ...old,
              utterances: old.utterances.map((item) =>
                item.utterance_number === pending.utteranceNumber
                  ? { ...item, status: "completed" }
                  : item,
              ),
            }
          : old,
      );
      setPendingUpload(null);
      setMessage("Upload succeeded. This utterance is saved.");
    } catch (e) {
      setError(e.message);
      setMessage(
        "The upload failed. Your recording is kept on this device; retry the upload to send the same take.",
      );
    } finally {
      setBusy(false);
    }
  }

  function recordAction() {
    if (recording) return stopRecording();
    if (pendingUpload) return sendPendingUpload(pendingUpload);
    return startRecording();
  }

  function switchParticipant() {
    if (recording || busy || pendingUpload) return;
    setToken("");
    setPlan(null);
    setReturning(false);
    setError("");
    setMessage("");
  }

  const remaining = missingIndices.length;
  return (
    <main className="page">
      <header className="hero">
        <div className="mark">MS</div>
        <div>
          <p className="kicker">Multilingual speech study</p>
          <h1>Recording session</h1>
          <p>Read each sentence naturally in the selected language.</p>
        </div>
      </header>
      <aside className="privacy">
        Your name and roll number identify your participant record. The
        recording system stores them separately from audio and uses an internal
        participant code in the dataset.
      </aside>
      {!token ? (
        <section className="card">
          <h2>Participant registration</h2>
          <form className="form" onSubmit={register}>
            <label>
              Name
              <input name="name" autoComplete="name" maxLength="200" required />
            </label>
            <label>
              Roll number
              <input
                name="roll_number"
                autoComplete="off"
                maxLength="64"
                required
              />
            </label>
            <button disabled={busy}>{busy ? "Saving…" : "Continue"}</button>
          </form>
        </section>
      ) : (
        <>
          <section className="card select-card">
            <div>
              <h2>Choose language and session</h2>
              <p>
                {returning
                  ? "Welcome back. Your completed recordings and sentence assignment are retained."
                  : "Your participant record is ready."}
              </p>
            </div>
            <form className="select-form" onSubmit={loadSession}>
              <label>
                Language
                <select
                  disabled={recording || busy || pendingUpload}
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  {LANGUAGES.map((item) => (
                    <option key={item} value={item}>
                      {item[0].toUpperCase() + item.slice(1)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Session
                <select
                  disabled={recording || busy || pendingUpload}
                  value={session}
                  onChange={(e) => setSession(Number(e.target.value))}
                >
                  <option value={1}>Session 1 · common sentences</option>
                  <option value={2}>Session 2 · randomized sentences</option>
                </select>
              </label>
              <button disabled={busy || recording || Boolean(pendingUpload)}>
                {busy ? "Loading…" : "Load session"}
              </button>
              <button
                className="quiet"
                type="button"
                disabled={Boolean(pendingUpload)}
                onClick={switchParticipant}
              >
                Switch participant
              </button>
            </form>
          </section>
        </>
      )}
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="alert success" role="status">
          {message}
        </div>
      )}
      {plan && (
        <section className="card recorder" aria-live="polite">
          <div className="session-title">
            <div>
              <p className="kicker">
                {plan.language[0].toUpperCase() + plan.language.slice(1)} ·
                Session {plan.session_number}
              </p>
              <h2>
                {current
                  ? `Utterance ${current.utterance_number} / ${plan.total}`
                  : remaining
                    ? "Prompts still missing"
                    : "Session complete"}
              </h2>
            </div>
            <div className="progress-count">
              {completed} complete
              <br />
              <span>{remaining} remaining</span>
            </div>
          </div>
          {current ? (
            <>
              <div className="progress-track">
                <div style={{ width: `${(completed / plan.total) * 100}%` }} />
              </div>
              <p className="sentence">{current.text}</p>
              <p className="format-hint">
                Speak clearly at a comfortable pace. Recording stops
                automatically after {plan.max_duration_seconds} seconds.
              </p>
              <div className="record-actions">
                <button
                  className={recording ? "stop" : "record"}
                  disabled={busy}
                  onClick={recordAction}
                >
                  {recording
                    ? "Stop recording"
                    : pendingUpload
                      ? "Retry upload"
                      : "Start recording"}
                </button>
                <span className="timer">
                  {String(Math.floor(seconds / 60)).padStart(2, "0")}:
                  {String(Math.floor(seconds % 60)).padStart(2, "0")}
                </span>
                <button
                  className="quiet"
                  disabled={recording || busy || Boolean(pendingUpload)}
                  onClick={skipCurrent}
                >
                  Skip for now
                </button>
              </div>
              {pendingUpload && (
                <button
                  className="quiet discard-take"
                  disabled={busy}
                  onClick={() => {
                    setPendingUpload(null);
                    setMessage(
                      "Saved take cleared from this page. You can record this utterance again.",
                    );
                  }}
                >
                  Discard failed take
                </button>
              )}
              {busy && (
                <p className="upload-note">
                  Validating and uploading… This utterance is not complete until
                  upload succeeds.
                </p>
              )}
            </>
          ) : remaining ? (
            <div className="done">
              <h3>{remaining} utterance(s) are still missing.</h3>
              <p>Skipped prompts have not been marked complete.</p>
              <button onClick={retrySkipped}>Review missing utterances</button>
            </div>
          ) : (
            <div className="done">
              <h3>All ten utterances are complete.</h3>
              <p>You can choose the other session or switch participant.</p>
            </div>
          )}
        </section>
      )}
      <footer>
        Audio is saved as mono 16 kHz, 16-bit PCM WAV. Continue only after the
        researcher has explained the study and obtained your consent.
      </footer>
    </main>
  );
}

function merge(chunks) {
  const total = chunks.reduce((n, item) => n + item.length, 0);
  const result = new Float32Array(total);
  let offset = 0;
  for (const item of chunks) {
    result.set(item, offset);
    offset += item.length;
  }
  return result;
}
function resample(input, from, to) {
  if (!input.length) throw new Error("No microphone audio was captured.");
  const length = Math.max(1, Math.round((input.length * to) / from));
  const out = new Float32Array(length);
  const step = from / to;
  for (let i = 0; i < length; i++) {
    const pos = i * step;
    const lo = Math.floor(pos),
      hi = Math.min(lo + 1, input.length - 1),
      frac = pos - lo;
    out[i] = input[lo] * (1 - frac) + input[hi] * frac;
  }
  return out;
}
function toWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, value) =>
    [...value].forEach((char, i) =>
      view.setUint8(offset + i, char.charCodeAt(0)),
    );
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, v < 0 ? v * 32768 : v * 32767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
