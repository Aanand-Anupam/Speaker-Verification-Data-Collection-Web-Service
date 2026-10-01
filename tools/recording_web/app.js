"use strict";

let participantToken = null;
let activePlan = null;
let activeIndex = -1;
let skipped = new Set();
let audioContext = null;
let microphoneStream = null;
let processorNode = null;
let audioChunks = [];
let recordingStartedAt = 0;
let timerHandle = null;
let isRecording = false;

const $ = (id) => document.getElementById(id);
const registration = $("registration");
const selection = $("session-selection");
const recorder = $("recorder");
const globalError = $("global-error");

function showError(message) {
  globalError.textContent = message;
  globalError.classList.remove("hidden");
}
function clearError() { globalError.textContent = ""; globalError.classList.add("hidden"); }

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

$("registration-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearError();
  const button = event.currentTarget.querySelector("button"); button.disabled = true;
  try {
    const data = await request("/api/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("name").value, roll_number: $("roll").value })
    });
    participantToken = data.token;
    registration.classList.add("hidden"); selection.classList.remove("hidden");
    $("name").value = ""; $("roll").value = "";
    $("language").focus();
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
});

$("session-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearError();
  const language = $("language").value;
  const session = Number($("session").value);
  try {
    activePlan = await request(`/api/session?language=${encodeURIComponent(language)}&session=${session}`, {
      headers: { Authorization: `Bearer ${participantToken}` }
    });
    activeIndex = -1; skipped = new Set();
    selection.classList.add("hidden"); recorder.classList.remove("hidden");
    $("session-label").textContent = `${language[0].toUpperCase()}${language.slice(1)} · Session ${session}`;
    $("notice").textContent = activePlan.message || "";
    $("notice").classList.toggle("hidden", activePlan.ready);
    $("prompt-area").classList.toggle("hidden", !activePlan.ready);
    $("complete-area").classList.add("hidden");
    if (activePlan.ready) renderCurrent();
  } catch (error) { showError(error.message); }
});

$("change-session").addEventListener("click", () => {
  if (isRecording) return;
  recorder.classList.add("hidden"); selection.classList.remove("hidden"); clearError();
});

$("switch-participant").addEventListener("click", logoutParticipant);
$("switch-participant-recorder").addEventListener("click", logoutParticipant);

async function logoutParticipant() {
  if (isRecording) return;
  clearError();
  try {
    if (participantToken) await request("/api/logout", { method: "POST", headers: { Authorization: `Bearer ${participantToken}` } });
  } catch (error) { showError(error.message); return; }
  participantToken = null; activePlan = null; skipped.clear();
  recorder.classList.add("hidden"); selection.classList.add("hidden"); registration.classList.remove("hidden");
  $("name").focus();
}

function missingIndices() {
  return activePlan.prompts.map((p, i) => !p.completed && !p.conflict ? i : -1).filter(i => i >= 0);
}

function renderCurrent() {
  const remaining = missingIndices();
  const done = activePlan.prompts.filter(p => p.completed).length;
  const missing = activePlan.prompts.filter(p => p.status === "missing" || (!p.completed && !p.conflict)).length;
  $("progress").textContent = `${done} complete · ${missing} missing`;
  $("complete-area").classList.add("hidden");
  if (!remaining.length) {
    $("prompt-area").classList.add("hidden");
    const conflicts = activePlan.prompts.filter(p => p.conflict).length;
    $("complete-area").textContent = conflicts
      ? `There are no more available prompts. ${conflicts} file name(s) are already occupied by another audio format; please ask the researcher to review them.`
      : "This session is complete. Your recordings have been saved.";
    $("complete-area").classList.remove("hidden"); return;
  }
  const next = remaining.find(i => !skipped.has(i));
  if (next === undefined) {
    $("prompt-area").classList.add("hidden");
    const box = $("complete-area"); box.replaceChildren();
    const text = document.createElement("p"); text.textContent = `${remaining.length} prompt(s) were skipped and are still missing.`;
    const retry = document.createElement("button"); retry.type = "button"; retry.textContent = "Try missing prompts";
    retry.addEventListener("click", () => { skipped.clear(); renderCurrent(); });
    box.append(text, retry); box.classList.remove("hidden"); return;
  }
  activeIndex = next;
  const prompt = activePlan.prompts[activeIndex];
  $("prompt-text").textContent = prompt.text;
  $("topic").textContent = prompt.topic || "";
  $("topic").classList.toggle("hidden", !prompt.topic);
  $("record-status").textContent = "Ready to record";
  $("timer").textContent = "00:00";
  $("record-button").textContent = "Start recording";
  $("record-button").disabled = false;
  $("skip-button").disabled = false;
  $("prompt-area").classList.remove("hidden");
}

$("skip-button").addEventListener("click", () => {
  if (isRecording || activeIndex < 0) return;
  skipped.add(activeIndex); renderCurrent();
});

$("record-button").addEventListener("click", () => {
  if (isRecording) stopAndUpload(); else startRecording();
});

async function startRecording() {
  clearError();
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    showError("Microphone access needs a secure page. Use localhost on this computer, or open the HTTPS address supplied by the researcher."); return;
  }
  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    await audioContext.resume();
    const source = audioContext.createMediaStreamSource(microphoneStream);
    processorNode = audioContext.createScriptProcessor(4096, 1, 1);
    const silentOutput = audioContext.createGain(); silentOutput.gain.value = 0;
    audioChunks = [];
    processorNode.onaudioprocess = (event) => audioChunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    source.connect(processorNode); processorNode.connect(silentOutput); silentOutput.connect(audioContext.destination);
    isRecording = true; recordingStartedAt = Date.now();
    $("record-button").textContent = "Stop and save";
    $("skip-button").disabled = true;
    $("record-status").textContent = "Recording…";
    timerHandle = window.setInterval(updateTimer, 200);
    updateTimer();
  } catch (error) {
    cleanupAudio();
    showError(`Could not start microphone recording: ${error.message}`);
  }
}

function updateTimer() {
  const seconds = (Date.now() - recordingStartedAt) / 1000;
  const total = Math.floor(seconds);
  $("timer").textContent = `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  if (activePlan.session === 3 && seconds >= activePlan.max_duration_seconds) stopAndUpload();
}

async function stopAndUpload() {
  if (!isRecording) return;
  isRecording = false; window.clearInterval(timerHandle);
  const sampleRate = audioContext.sampleRate;
  if (processorNode) processorNode.onaudioprocess = null;
  const merged = mergeChunks(audioChunks);
  cleanupAudio();
  $("record-button").disabled = true;
  $("skip-button").disabled = true;
  $("record-status").textContent = "Preparing and uploading recording…";
  try {
    const wav = encodePcmWav(resample(merged, sampleRate, 16000), 16000);
    const prompt = activePlan.prompts[activeIndex];
    await request("/api/upload", {
      method: "POST", body: wav,
      headers: {
        Authorization: `Bearer ${participantToken}`,
        "Content-Type": "audio/wav",
        "X-Language": activePlan.language,
        "X-Session": String(activePlan.session),
        "X-Utterance-ID": prompt.utterance_id
      }
    });
    prompt.completed = true; prompt.status = "complete"; skipped.delete(activeIndex);
    $("record-status").textContent = "Recording saved.";
    renderCurrent();
  } catch (error) {
    showError(error.message);
    $("record-status").textContent = "Upload failed. You can record this prompt again.";
    $("record-button").disabled = false; $("record-button").textContent = "Start recording again";
    $("skip-button").disabled = false;
  }
}

function mergeChunks(chunks) {
  const size = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const result = new Float32Array(size); let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}

function resample(input, fromRate, toRate) {
  if (!input.length) throw new Error("No microphone audio was captured.");
  const length = Math.max(1, Math.round(input.length * toRate / fromRate));
  const output = new Float32Array(length);
  const step = fromRate / toRate;
  for (let i = 0; i < length; i++) {
    const pos = i * step, left = Math.floor(pos), right = Math.min(left + 1, input.length - 1), fraction = pos - left;
    output[i] = input[left] * (1 - fraction) + input[right] * fraction;
  }
  return output;
}

function encodePcmWav(samples, sampleRate) {
  const bytes = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(bytes);
  const write = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  write(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); write(8, "WAVE");
  write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  return new Blob([bytes], { type: "audio/wav" });
}

function cleanupAudio() {
  if (timerHandle) window.clearInterval(timerHandle);
  timerHandle = null;
  if (processorNode) { try { processorNode.disconnect(); } catch {} processorNode = null; }
  if (microphoneStream) { microphoneStream.getTracks().forEach(track => track.stop()); microphoneStream = null; }
  if (audioContext) { const ctx = audioContext; audioContext = null; ctx.close().catch(() => {}); }
}
