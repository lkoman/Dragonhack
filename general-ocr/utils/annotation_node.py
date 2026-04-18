import threading
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import numpy as np
import depthai as dai
from depthai_nodes.utils import AnnotationHelper

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
        self.seen_texts = set()

        t = threading.Thread(target=start_server, daemon=True)
        t.start()
        print("Web server running at http://localhost:8080")

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

                    if text_line.strip() and text_line.strip() not in self.seen_texts:
                        self.seen_texts.add(text_line.strip())
                        text_queue.put(text_line.strip())

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