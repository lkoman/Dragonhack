import { SonioxClient } from "https://esm.sh/@soniox/client";

const BACKEND = "http://localhost:8000";
const OCR_BACKEND = "http://localhost:8080";

// Paste your OpenAI API key here to enable end-of-presentation summaries.
const OPENAI_API_KEY = "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";

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
  if (liveText.trim()) {
    lockedText += (lockedText ? " " : "") + liveText.trim();
    liveText = "";
    renderTranscript();
  }
}

/* ---------------- OpenAI summary ---------------- */

function showSummaryCard(innerHTML) {
  const card = document.getElementById("summaryCard");
  const text = document.getElementById("summaryText");
  if (!card || !text) return;
  card.style.display = "block";
  text.innerHTML = innerHTML;
  try { card.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch {}
}

function hideSummaryCard() {
  const card = document.getElementById("summaryCard");
  if (card) card.style.display = "none";
}

async function generateSummary() {
  console.log("[summary] generateSummary called, lockedText length:", lockedText.length);
  const text = lockedText.trim();

  if (!OPENAI_API_KEY) {
    console.error("[summary] OPENAI_API_KEY is not set in app.js — summary skipped");
    showSummaryCard('<span class="ocr-empty">OpenAI API key missing — set OPENAI_API_KEY in app.js</span>');
    return;
  }

  if (text.length < 20) {
    console.log("[summary] transcript too short, skipping");
    showSummaryCard('<span class="ocr-empty">Transcript too short for a summary</span>');
    return;
  }

  showSummaryCard('<span class="ocr-empty">Generating summary...</span>');

  try {
    const res = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${OPENAI_API_KEY}`
      },
      body: JSON.stringify({
        model: "gpt-4.1-mini",
        input: `Povzemi v alineje v angleščini:\n${text}`
      })
    });

    if (!res.ok) {
      const errBody = await res.text();
      console.error("[summary] OpenAI request failed", res.status, errBody);
      showSummaryCard('<span class="ocr-empty">Summary generation failed</span>');
      return;
    }

    const data = await res.json();
    const output =
      data.output_text ||
      data.output?.[0]?.content?.[0]?.text ||
      "";

    if (!output) {
      console.error("[summary] unexpected OpenAI response shape", data);
      showSummaryCard('<span class="ocr-empty">Summary generation failed</span>');
      return;
    }

    const safe = output
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    showSummaryCard(`<p>${safe.replace(/\n/g, "</p><p>")}</p>`);
    lastSummary = output;
    savePredavanje();
  } catch (err) {
    console.error("[summary] error calling OpenAI", err);
    showSummaryCard('<span class="ocr-empty">Summary generation failed</span>');
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

  hideSummaryCard();
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
      currentFinalScore = data.final_score;
      setEngagement(Math.round(data.final_score));
    }
  } catch {}

  fetch(`${BACKEND}/disconnect`, { method: "POST" }).catch(() => {});

  showSummaryCard('<span class="ocr-empty">Generating summary...</span>');
  savePredavanje();
  generateSummary();

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

/* ---------------- per-predavanje persistence ---------------- */

async function hydratePredavanje() {
  if (!predavanjeName) return;
  try {
    const res = await fetch(`${BACKEND}/predavanja/${encodeURIComponent(predavanjeName)}`);
    if (!res.ok) return;
    const data = await res.json();

    if (typeof data.transcript === "string" && data.transcript.trim()) {
      lockedText = data.transcript;
      liveText = "";
      renderTranscript();
    }

    if (Array.isArray(data.ocr_items) && data.ocr_items.length) {
      for (const item of data.ocr_items) {
        if (typeof item !== "string") continue;
        const key = normalizeOcr(item);
        if (!key || ocrSeen.has(key)) continue;
        ocrSeen.add(key);
        ocrItems.push(item);
      }
      saveStored(ocrKey, ocrItems);
      renderOcrStored();
    }

    if (typeof data.final_score === "number") {
      setEngagement(Math.round(data.final_score));
    }

    if (typeof data.summary === "string" && data.summary.trim()) {
      lastSummary = data.summary;
      const safe = data.summary
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      showSummaryCard(`<p>${safe.replace(/\n/g, "</p><p>")}</p>`);
    }
  } catch (err) {
    console.warn("[predavanje] hydrate failed", err);
  }
}

let lastSummary = "";

async function savePredavanje() {
  if (!predavanjeName) return;
  const body = {
    transcript: lockedText,
    summary: lastSummary,
    final_score: typeof currentFinalScore === "number" ? currentFinalScore : null,
    ocr_items: ocrItems,
  };
  try {
    await fetch(`${BACKEND}/predavanja/${encodeURIComponent(predavanjeName)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    console.warn("[predavanje] save failed", err);
  }
}

let currentFinalScore = null;

fetchDevices();
hydratePredavanje();
