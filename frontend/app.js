const BACKEND = "http://localhost:8000";
const OCR_BACKEND = "http://localhost:8080";
const TRANSCRIPT_BACKEND = "http://localhost:8081";
let streaming = false;

// OCR stream
const es = new EventSource(`${OCR_BACKEND}/stream`);
es.onopen = () => {
  document.getElementById("ocrDot").classList.add("active");
};
es.onmessage = e => {
  const container = document.getElementById("ocrText");
  const empty = container.querySelector(".ocr-empty");
  if (empty) empty.remove();

  const line = document.createElement("p");
  line.textContent = e.data;
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
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
  document.getElementById("liveBadge").classList.add("visible");
  document.getElementById("startBtn").disabled = true;
  document.getElementById("stopBtn").disabled = false;
}

function stopStream() {
  streaming = false;
  const img = document.getElementById("videoFeed");
  img.src = "";
  img.style.display = "none";
  document.getElementById("placeholder").style.display = "flex";
  document.getElementById("liveBadge").classList.remove("visible");
  document.getElementById("startBtn").disabled = false;
  document.getElementById("stopBtn").disabled = true;
}

fetchDevices();
