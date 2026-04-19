const BACKEND = "http://localhost:8000";
const OCR_BACKEND = "http://localhost:8080";
const TRANSCRIPT_BACKEND = "http://localhost:8081";
let engagementInterval = null;
let volumeInterval = null;

function animateVolumeMeter(active, level) {
  const meter = document.getElementById("volumeMeter");
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
  el.textContent = score === null ? "—" : `${score}%`;
  const level = score >= 70 ? "high" : score >= 40 ? "mid" : "low";
  el.className = "engagement-score" + (score !== null ? ` ${level}` : "");
}


const predavanjeName = new URLSearchParams(window.location.search).get("name");
if (predavanjeName) {
  document.getElementById("predavanjeTitle").textContent = predavanjeName;
  document.title = `${predavanjeName} — Dragonhack Jебачи`;
}

// OCR stream
const es = new EventSource(`${OCR_BACKEND}/stream`);
es.onopen = () => {
  document.getElementById("ocrDot").classList.add("active");
};
es.onmessage = e => {
  const container = document.getElementById("ocrText");
  let items;
  try { items = JSON.parse(e.data); } catch { return; }
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
};
es.onerror = () => {
  document.getElementById("ocrDot").classList.remove("active");
};

// Transcript stream
const ts = new EventSource(`${TRANSCRIPT_BACKEND}/stream`);
ts.onopen = () => {
  document.getElementById("transcriptDot").classList.add("active");
};
ts.onmessage = e => {
  const container = document.getElementById("transcriptText");
  const empty = container.querySelector(".ocr-empty");
  if (empty) empty.remove();

  const line = document.createElement("p");
  line.textContent = e.data;
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
};
ts.onerror = () => {
  document.getElementById("transcriptDot").classList.remove("active");
};

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

function startStream() {
  streaming = true;
  const img = document.getElementById("videoFeed");
  img.src = `${BACKEND}/video-feed`;
  img.style.display = "block";
  document.getElementById("placeholder").style.display = "none";
  document.getElementById("videoPlayback").style.display = "none";
  document.getElementById("liveBadge").classList.add("visible");
  document.getElementById("startBtn").disabled = true;
  document.getElementById("stopBtn").disabled = false;
  document.getElementById("summaryCard").style.display = "none";
  document.querySelector(".transcript-card").classList.remove("shrunk");

  // start fake live engagement updates
  let fakeScore = 50;
  setEngagement(fakeScore);
  engagementInterval = setInterval(() => {
    fakeScore = Math.min(100, Math.max(0, fakeScore + (Math.random() * 14 - 6)));
    setEngagement(Math.round(fakeScore));
  }, 1800);
  volumeInterval = setInterval(() => animateVolumeMeter(true, fakeScore), 120);
}

function stopStream() {
  streaming = false;

  // stop engagement live updates, show final score
  clearInterval(engagementInterval);
  clearInterval(volumeInterval);
  animateVolumeMeter(false, 0);
  clearInterval(volumeInterval);
  animateVolumeMeter(false, 0);
  const finalScore = Math.round(40 + Math.random() * 45);
  setEngagement(finalScore);
  const img = document.getElementById("videoFeed");
  img.src = "";
  img.style.display = "none";
  document.getElementById("liveBadge").classList.remove("visible");
  document.getElementById("startBtn").disabled = false;
  document.getElementById("stopBtn").disabled = true;

  // show recorded video placeholder
  const video = document.getElementById("videoPlayback");
  video.src = "";
  video.style.display = "block";
  document.getElementById("placeholder").style.display = "none";

  // show summary box and fake-generate summary
  showSummary();
}

function showSummary() {
  const card = document.getElementById("summaryCard");
  const text = document.getElementById("summaryText");
  card.style.display = "block";
  document.querySelector(".transcript-card").classList.add("shrunk");
  card.scrollIntoView({ behavior: "smooth", block: "start" });

  // collect transcript lines for the real implementation later
  const transcriptLines = Array.from(
    document.getElementById("transcriptText").querySelectorAll("p")
  ).map(p => p.textContent).join(" ");

  // fake placeholder summary for now
  text.innerHTML = "";
  const placeholder = `
    <p>The lecture covered the fundamentals of computer vision and real-time image processing pipelines.</p>
    <p>Key topics included edge detection algorithms, convolutional neural networks, and their application to object recognition tasks.</p>
    <p>The speaker demonstrated a live OCR pipeline and discussed latency optimizations for embedded hardware deployment.</p>
  `.trim();

  // typewriter effect so it feels alive
  const sentences = placeholder.match(/<p>.*?<\/p>/g) || [];
  let i = 0;
  function addNext() {
    if (i >= sentences.length) return;
    const p = document.createElement("p");
    p.innerHTML = sentences[i].replace(/<\/?p>/g, "");
    text.appendChild(p);
    p.style.opacity = "0";
    p.style.transform = "translateY(6px)";
    p.style.transition = "opacity 0.4s ease, transform 0.4s ease";
    requestAnimationFrame(() => {
      p.style.opacity = "1";
      p.style.transform = "translateY(0)";
    });
    i++;
    setTimeout(addNext, 500);
  }
  addNext();
}

fetchDevices();

import { SonioxClient } from "https://esm.sh/@soniox/client";

/* ---------------- STATE ---------------- */

let lockedText = "";
let liveText = "";
let recording;

const transcriptDiv = document.getElementById("transcriptText");
const transcriptDot = document.getElementById("transcriptDot");

/* ---------------- RENDER ---------------- */

function render() {
  transcriptDiv.innerHTML =
    `<span class="locked-text">${lockedText}</span>` +
    (liveText
      ? ` <span class="live-text">${liveText}</span>`
      : "");

  console.log("---- RENDER ----");
  console.log("LOCKED:", lockedText);
  console.log("LIVE:", liveText);
}

/* ---------------- CLIENT ---------------- */

const client = new SonioxClient({
  api_key: "12e95c60016fa692812197e892e6193d9c38a3b8037ac81b871efe4b2ba1b4dc"
});

/* ---------------- START STREAM ---------------- */

window.startStream = async function () {

  console.log("START TRANSCRIPTION");

  transcriptDot.classList.add("active");

  recording = client.realtime.record({
    model: "stt-rt-v4",
    language_hints: ["en", "sl"],
    enable_endpoint_detection: true
  });

  /* -------- RESULT (LIVE ONLY) -------- */

  recording.on("result", (result) => {
    console.log("RESULT:", result);

    let temp = "";

    for (const token of result.tokens || []) {
      if (!token.text) continue;
      temp += token.text;
    }

    liveText = temp;

    render();
  });

  /* -------- FINALIZED (LOCK) -------- */

  recording.on("finalized", () => {
    console.log("FINALIZED");

    if (liveText.trim()) {
      console.log("LOCK ADD:", liveText);

      lockedText += (lockedText ? " " : "") + liveText.trim();
    }

    liveText = "";

    render();
    triggerSummary();
  });

  /* -------- ENDPOINT (fallback) -------- */

  recording.on("endpoint", () => {
    console.log("ENDPOINT");

    if (liveText.trim()) {
      console.log("FORCE LOCK:", liveText);

      lockedText += (lockedText ? " " : "") + liveText.trim();
    }

    liveText = "";

    render();
    triggerSummary();
  });

  recording.on("error", console.error);
};

/* ---------------- STOP ---------------- */

window.stopStream = async function () {
  if (recording) {
    console.log("STOP TRANSCRIPTION");

    transcriptDot.classList.remove("active");

    await recording.stop();
  }
};

/* ---------------- SUMMARY ---------------- */

let summaryTimeout;

function triggerSummary() {
  clearTimeout(summaryTimeout);

  summaryTimeout = setTimeout(() => {
    const text = lockedText;

    console.log("SUMMARY INPUT:", text);

    if (text.length < 30) return;

    summarize(text);
  }, 2000);
}

/* ---------------- OPENAI ---------------- */

async function summarize(text) {
  const summaryDiv = document.getElementById("ocrText");

  const res = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer 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"
    },
    body: JSON.stringify({
      model: "gpt-4.1-mini",
      input: `Povzemi v alineje v slovenščini:\n${text}`
    })
  });

  const data = await res.json();

  console.log("OPENAI RAW:", data);

  const output =
    data.output_text ||
    data.output?.[0]?.content?.[0]?.text ||
    "Napaka pri povzetku";

  summaryDiv.innerHTML = `<p>${output}</p>`;
}
