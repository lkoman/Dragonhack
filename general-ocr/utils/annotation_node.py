import numpy as np
import depthai as dai
from depthai_nodes.utils import AnnotationHelper

class OCRAnnotationNode(dai.node.ThreadedHostNode):
    def __init__(self):
        super().__init__()
        self.input = self.createInput()
        self.passthrough = self.createInput()
        self.frame_output = self.createOutput()
        self.text_annotations_output = self.createOutput()
        self.seen_texts = set()

    def is_white_background(self, frame, points, w, h, threshold=200, white_ratio=0.6):
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

                    if not self.is_white_background(frame_np, points, w, h, threshold=150, white_ratio=0.3):
                        continue

                    text_line = ""
                    for text, score in zip(recognition.classes, recognition.scores):
                        if len(text) <= 2 or score < 0.25:
                            continue
                        text_line += text + " "

                    if text_line.strip() and text_line.strip() not in self.seen_texts:
                        self.seen_texts.add(text_line.strip())
                        with open("ocr_output.txt", "a") as f:
                            f.write(text_line.strip() + "\n")

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