import { SonioxClient } from "https://esm.sh/@soniox/client";

const BACKEND = "http://localhost:8000";
const OCR_BACKEND = "http://localhost:8080";

let streaming = false;
let engagementInterval = null;
let volumeInterval = null;

function animateVolumeMeter(active, level) {
  const meter = document.getElementById("volumeMeter");
  if (!meter) return;
  const bars = meter.querySelectorAll(".vm-bar");
  if (!active) {
    meter.className = "volume-meter";
    bars.forEach(b => b.style.height = "4px");
    return;
  }
  const levelClass = level >= 70 ? "high" : level >= 40 ? "mid" : "low";
  meter.className = `volume-meter active ${levelClass}`;
  bars.forEach(bar => {
    const max = 8 + (level / 100) * 28;
    const h = 4 + Math.random() * max;
    bar.style.height = `${h}px`;
  });
}

function setEngagement(score) {
  const el = document.getElementById("engagementScore");
  if (!el) return;
  el.textContent = score === null ? "—" : `${score}%`;
  if (score === null) {
    el.className = "engagement-score";
    return;
  }
  const level = score >= 70 ? "high" : score >= 40 ? "mid" : "low";
  el.className = `engagement-score ${level}`;
}

const predavanjeName = new URLSearchParams(window.location.search).get("name");
if (predavanjeName) {
  document.getElementById("predavanjeTitle").textContent = predavanjeName;
  document.title = `${predavanjeName} — Dragonhack Jебачи`;
}

const ocrKey = predavanjeName ? `predavanje_ocr_${predavanjeName}` : "predavanje_ocr__default";

function loadStored(key) {
  try { return JSON.parse(localStorage.getItem(key)) || []; } catch { return []; }
}
function saveStored(key, list) {
  try { localStorage.setItem(key, JSON.stringify(list)); } catch {}
}

function normalizeOcr(s) {
  return (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

let ocrItems = loadStored(ocrKey).filter(s => typeof s === "string" && s.trim() && normalizeOcr(s));
let ocrSeen = new Set(ocrItems.map(normalizeOcr));

let es = null;

function renderOcrLive(items) {
  const container = document.getElementById("ocrText");
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("span");
    empty.className = "ocr-empty";
    empty.textContent = "No text visible";
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    const line = document.createElement("p");
    line.textContent = item;
    container.appendChild(line);
  }
}

function renderOcrStored() {
  const container = document.getElementById("ocrText");
  container.innerHTML = "";
  if (!ocrItems.length) {
    const empty = document.createElement("span");
    empty.className = "ocr-empty";
    empty.textContent = "Waiting for text...";
    container.appendChild(empty);
    return;
  }
  for (const item of ocrItems) {
    const line = document.createElement("p");
    line.textContent = item;
    container.appendChild(line);
  }
  container.scrollTop = container.scrollHeight;
}

renderOcrStored();

function openStreams() {
  if (es) return;

  es = new EventSource(`${OCR_BACKEND}/stream`);
  es.onopen = () => {
    document.getElementById("ocrDot").classList.add("active");
  };
  es.onmessage = e => {
    if (!streaming) return;
    let items;
    try { items = JSON.parse(e.data); } catch { return; }
    const liveItems = [];
    let changed = false;
    for (const item of items) {
      if (typeof item !== "string") continue;
      const trimmed = item.trim();
      if (!trimmed) continue;
      const key = normalizeOcr(trimmed);
      if (!key) continue;
      liveItems.push(trimmed);
      if (!ocrSeen.has(key)) {
        ocrSeen.add(key);
        ocrItems.push(trimmed);
        changed = true;
      }
    }
    if (changed) saveStored(ocrKey, ocrItems);
    renderOcrLive(liveItems);
  };
  es.onerror = () => {
    document.getElementById("ocrDot").classList.remove("active");
  };
}

function closeStreams() {
  if (es) { es.close(); es = null; }
  const ocrDot = document.getElementById("ocrDot");
  if (ocrDot) ocrDot.classList.remove("active");
}

async function fetchDevices() {
  const select = document.getElementById("deviceSelect");
  select.innerHTML = '<option value="">scanning...</option>';
  try {
    const res = await fetch(`${BACKEND}/devices`);
    const devices = await res.json();
    select.innerHTML = '<option value="">— select device —</option>';
    devices.forEach(d => {
      const opt = document.createElement("option");
      opt.value = d.name;
      opt.textContent = `${d.name} (${d.mxid})`;
      select.appendChild(opt);
    });
    if (devices.length === 0) select.innerHTML = '<option value="">no devices found</option>';
  } catch {
    select.innerHTML = '<option value="">scan failed</option>';
  }
}

async function connectDevice() {
  const ip = document.getElementById("deviceSelect").value;
  if (!ip) return;
  await fetch(`${BACKEND}/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ip })
  });
  document.getElementById("statusDot").className = "status-dot connected";
  document.getElementById("cameraName").textContent = `OAK Camera (${ip})`;
  document.getElementById("cameraMxid").textContent = ip;
  document.getElementById("startBtn").disabled = false;
}

/* ---------------- Soniox transcription ---------------- */

const sonioxClient = new SonioxClient({
  api_key: "12e95c60016fa692812197e892e6193d9c38a3b8037ac81b871efe4b2ba1b4dc"
});

let lockedText = "";
let liveText = "";
let recording = null;

function renderTranscript() {
  const transcriptDiv = document.getElementById("transcriptText");
  if (!transcriptDiv) return;
  transcriptDiv.innerHTML =
    `<span class="locked-text">${lockedText}</span>` +
    (liveText ? ` <span class="live-text">${liveText}</span>` : "");
}

async function startTranscription() {
  const transcriptDot = document.getElementById("transcriptDot");
  if (transcriptDot) transcriptDot.classList.add("active");
  lockedText = "";
  liveText = "";
  renderTranscript();

  recording = sonioxClient.realtime.record({
    model: "stt-rt-v4",
    language_hints: ["en", "sl"],
    enable_endpoint_detection: true
  });

  recording.on("result", (result) => {
    let temp = "";
    for (const token of result.tokens || []) {
      if (!token.text) continue;
      temp += token.text;
    }
    liveText = temp;
    renderTranscript();
  });

  const lockLive = () => {
    if (liveText.trim()) {
      lockedText += (lockedText ? " " : "") + liveText.trim();
    }
    liveText = "";
    renderTranscript();
  };

  recording.on("finalized", lockLive);
  recording.on("endpoint", lockLive);
  recording.on("error", console.error);
}

async function stopTranscription() {
  const transcriptDot = document.getElementById("transcriptDot");
  if (transcriptDot) transcriptDot.classList.remove("active");
  if (recording) {
    try { await recording.stop(); } catch {}
    recording = null;
  }
}

/* ---------------- engagement polling ---------------- */

async function pollEngagement() {
  try {
    const res = await fetch(`${BACKEND}/engagement/score`);
    const data = await res.json();
    const score = Math.round(data.live_score ?? 0);
    setEngagement(score);
    animateVolumeMeter(true, score);
  } catch {}
}

/* ---------------- start / stop ---------------- */

function startStream() {
  streaming = true;
  const img = document.getElementById("videoFeed");
  img.src = `${BACKEND}/video-feed`;
  img.style.display = "block";
  document.getElementById("placeholder").style.display = "none";
  const playback = document.getElementById("videoPlayback");
  if (playback) playback.style.display = "none";
  document.getElementById("liveBadge").classList.add("visible");
  document.getElementById("startBtn").disabled = true;
  document.getElementById("stopBtn").disabled = false;

  openStreams();
  fetch(`${BACKEND}/engagement/start`, { method: "POST" }).catch(() => {});
  startTranscription().catch(console.error);

  setEngagement(0);
  if (engagementInterval) clearInterval(engagementInterval);
  engagementInterval = setInterval(pollEngagement, 500);
}

async function stopStream() {
  streaming = false;

  if (engagementInterval) { clearInterval(engagementInterval); engagementInterval = null; }
  if (volumeInterval) { clearInterval(volumeInterval); volumeInterval = null; }
  animateVolumeMeter(false, 0);

  closeStreams();
  await stopTranscription();

  try {
    const res = await fetch(`${BACKEND}/engagement/stop`, { method: "POST" });
    const data = await res.json();
    if (typeof data.final_score === "number") {
      setEngagement(Math.round(data.final_score));
    }
  } catch {}

  fetch(`${BACKEND}/disconnect`, { method: "POST" }).catch(() => {});

  const img = document.getElementById("videoFeed");
  img.removeAttribute("src");
  img.style.display = "none";
  document.getElementById("placeholder").style.display = "flex";
  document.getElementById("liveBadge").classList.remove("visible");
  document.getElementById("startBtn").disabled = true;
  document.getElementById("stopBtn").disabled = true;
  document.getElementById("statusDot").className = "status-dot";
  document.getElementById("cameraName").textContent = "No device selected";
  document.getElementById("cameraMxid").textContent = "—";
}

window.addEventListener("beforeunload", closeStreams);

window.startStream = startStream;
window.stopStream = stopStream;
window.connectDevice = connectDevice;
window.fetchDevices = fetchDevices;

fetchDevices();
