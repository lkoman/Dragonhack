import difflib
import json
import os
import threading
import time
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import numpy as np
import depthai as dai
from depthai_nodes.utils import AnnotationHelper

try:
    import openai
except ImportError:
    openai = None

FLUSH_INTERVAL_S = 5.0
LINE_BUCKET = 0.05  # rows within 5% of frame height are treated as the same line
GPT_MODEL = "gpt-4o-mini" # "gpt-3.5-turbo"

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if openai is None:
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    _openai_client = openai.OpenAI(api_key=api_key)
    return _openai_client


def _clean_texts_via_gpt(texts):
    if not texts:
        return texts
    client = _get_openai_client()
    if client is None:
        return texts

    unique_texts = list(dict.fromkeys(texts))

    try:
        prompt = (
                "You are cleaning OCR readings from a camera feed. Each reading "
                "may be a single word, a fragment, or a full sentence. Readings "
                "are noisy: typos, misrecognized characters (0/O, 1/l/I, 5/S), "
                "missing or extra words, and the same intended text often "
                "appears multiple times with slightly different spellings.\n\n"
                "For each reading in the list, output a cleaned version following "
                "these rules:\n\n"
                "1. GIBBERISH -> DROP. If a reading is not a real English word, "
                'cannot be corrected to one, and is not part of any sentence you '
                'can infer from the other readings, output an empty string "". '
                "DO NOT return gibberish unchanged. Only keep readings you can "
                "confidently map to real English.\n"
                "2. TYPO -> CORRECT. If a word is a typo of a real English word "
                '(e.g. "apfle" -> "apple", "BlTeh" -> "BITCH"), output the '
                "corrected word.\n"
                "3. BROKEN SENTENCE -> REPAIR. If a reading is a sentence with "
                "missing, extra, or wrong words, rewrite it as the most likely "
                "intended sentence.\n"
                "4. WORDS/FRAGMENTS -> COMBINE INTO SENTENCES. The readings are "
                "usually individual words or short fragments detected separately "
                "from the same slide/scene, and they almost always fit together "
                "into one (or a few) coherent sentences or phrases. Assemble them "
                "into the most plausible sentence(s) using context, common sense, "
                "and natural English word order. If a group of readings clearly "
                "belongs to one sentence, output the SAME full assembled sentence "
                "for every reading in that group so they collapse into a single "
                "entry after dedup. Prefer combining over keeping words isolated "
                "whenever a reasonable sentence can be formed. Only leave a "
                "reading standalone if it genuinely does not fit with any other "
                "reading (e.g. a heading, a label, or a single-word title).\n"
                "5. VARIANTS -> CANONICALIZE. If multiple readings are variants "
                "of the same word or sentence, output the EXACT SAME canonical "
                "string for all of them (ignore minor word-order, spelling, or "
                "punctuation differences).\n"
                "6. CASE. Preserve case style (ALL-CAPS stays ALL-CAPS, Sentence "
                "case stays Sentence case).\n\n"
                'Respond as JSON: {"items": ["cleaned1", "cleaned2", ...]} with '
                "the SAME length and order as the input list. Use empty strings "
                "for dropped gibberish.\n\n"
            f"Input: {json.dumps(unique_texts)}"
        )
        response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        cleaned_list = parsed.get("items") if isinstance(parsed, dict) else None
        if isinstance(cleaned_list, list) and len(cleaned_list) == len(unique_texts):
            mapping = {orig: str(cleaned) for orig, cleaned in zip(unique_texts, cleaned_list)}
            return [mapping[t] for t in texts]
    except Exception as e:
        print(f"GPT cleanup failed: {e}")

    return texts

text_queue = queue.Queue()

class SSEHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html>
            <body style="background:white; font-family:sans-serif; padding:40px; font-size:32px;">
              <div id="text"></div>
              <script>
                const es = new EventSource("/stream");
                es.onmessage = e => {
                  const line = document.createElement("p");
                  line.textContent = e.data;
                  document.getElementById("text").appendChild(line);
                };
              </script>
            </body>
            </html>
            """.encode()
            self.wfile.write(html)

        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    text = text_queue.get()
                    self.wfile.write(f"data: {text}\n\n".encode())
                    self.wfile.flush()
            except:
                pass

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

def start_server():
    server = ThreadedHTTPServer(("0.0.0.0", 8080), SSEHandler)
    server.serve_forever()

class OCRAnnotationNode(dai.node.ThreadedHostNode):
    def __init__(self):
        super().__init__()
        self.input = self.createInput()
        self.passthrough = self.createInput()
        self.frame_output = self.createOutput()
        self.text_annotations_output = self.createOutput()
        self.seen_items = {}
        self.similarity_threshold = 0.8
        self._items_lock = threading.Lock()

        threading.Thread(target=start_server, daemon=True).start()
        threading.Thread(target=self._flush_loop, daemon=True).start()
        print("Web server running at http://localhost:8080")

    def _flush_loop(self):
        while True:
            time.sleep(FLUSH_INTERVAL_S)
            with self._items_lock:
                raw_items = list(self.seen_items.values())
                self.seen_items.clear()

            if not raw_items:
                text_queue.put(json.dumps([]))
                continue

            raw_texts = [t for t, _, _ in raw_items]
            #print(f"[OCR raw]     {raw_texts}")
            cleaned_texts = _clean_texts_via_gpt(raw_texts)
            # print(f"[OCR cleaned] {cleaned_texts}")

            dedup = {}
            for (_, y, x), cleaned in zip(raw_items, cleaned_texts):
                key = self._normalize(cleaned)
                if key and key not in dedup:
                    dedup[key] = (cleaned, y, x)

            ordered = sorted(
                dedup.values(),
                key=lambda v: (int(v[1] / LINE_BUCKET), v[2]),
            )
            snapshot = [text for text, _, _ in ordered]
            print(f"[OCR sent]    {snapshot}")
            text_queue.put(json.dumps(snapshot))

    def _normalize(self, text):
        return "".join(c.lower() for c in text if c.isalnum())

    def _is_duplicate(self, text):
        key = self._normalize(text)
        if not key:
            return True
        if key in self.seen_items:
            return True
        for existing_key in self.seen_items:
            ratio = difflib.SequenceMatcher(None, key, existing_key).ratio()
            if ratio >= self.similarity_threshold:
                return True
        return False

    def is_white_background(self, frame, points, w, h, threshold=150, white_ratio=0.3):
        xs = [int(p.x * w) for p in points]
        ys = [int(p.y * h) for p in points]
        xmin, xmax = max(0, min(xs)), min(w, max(xs))
        ymin, ymax = max(0, min(ys)), min(h, max(ys))

        if xmax <= xmin or ymax <= ymin:
            return False

        crop = frame[ymin:ymax, xmin:xmax]
        if crop.size == 0:
            return False

        white_pixels = np.all(crop > threshold, axis=2)
        return white_pixels.mean() > white_ratio

    def run(self):
        while self.isRunning():
            text_descriptions = self.input.get()
            passthrough_frame = self.passthrough.get()
            detections_list = text_descriptions.reference_data.detections
            recognitions_list = text_descriptions.gathered
            w, h = passthrough_frame.getWidth(), passthrough_frame.getHeight()
            frame_np = passthrough_frame.getCvFrame()

            if len(recognitions_list) >= 1:
                annotation_helper = AnnotationHelper()
                for i, recognition in enumerate(recognitions_list):
                    detection = detections_list[i]
                    points = detection.rotated_rect.getPoints()

                    if not self.is_white_background(frame_np, points, w, h):
                        continue

                    text_line = ""
                    for text, score in zip(recognition.classes, recognition.scores):
                        if len(text) <= 2 or score < 0.25:
                            continue
                        text_line += text + " "

                    stripped = text_line.strip()
                    if stripped:
                        y_min = min(p.y for p in points)
                        x_min = min(p.x for p in points)
                        with self._items_lock:
                            if not self._is_duplicate(stripped):
                                self.seen_items[self._normalize(stripped)] = (
                                    stripped,
                                    y_min,
                                    x_min,
                                )

                    size = int(points[3].y * h - points[0].y * h)
                    annotation_helper.draw_text(
                        text_line, [points[3].x + 0.02, points[3].y + 0.02], size=size
                    )
                annotations = annotation_helper.build(
                    text_descriptions.getTimestamp(), text_descriptions.getSequenceNum()
                )
            self.frame_output.send(passthrough_frame)
            if len(recognitions_list) >= 1:
                self.text_annotations_output.send(annotations)
