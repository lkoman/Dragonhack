import threading
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import cv2
import depthai as dai
from depthai_nodes.node import ParsingNeuralNetwork, GatherData
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from utils.annotation_node import OCRAnnotationNode
from utils.host_process_detections import CropConfigsCreator

REQ_WIDTH, REQ_HEIGHT = 1152, 640
MODELS_DIR = Path(__file__).parent / "depthai_models"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frame_lock = threading.Lock()
latest_frame = None
capture_thread = None
pipeline_instance = None


def capture_loop(ip: str):
    global latest_frame, pipeline_instance

    device = dai.Device(dai.DeviceInfo(ip)) if ip else dai.Device()
    platform = device.getPlatform().name
    print(f"Platform: {platform}")

    frame_type = (
        dai.ImgFrame.Type.BGR888i if platform == "RVC4" else dai.ImgFrame.Type.BGR888p
    )
    fps_limit = 5 if platform == "RVC2" else 30

    with dai.Pipeline(device) as pipeline:
        pipeline_instance = pipeline

        det_model_description = dai.NNModelDescription.fromYamlFile(
            str(MODELS_DIR / f"paddle_text_detection.{platform}.yaml")
        )
        det_model_nn_archive = dai.NNArchive(dai.getModelFromZoo(det_model_description))
        det_model_w, det_model_h = det_model_nn_archive.getInputSize()

        rec_model_description = dai.NNModelDescription.fromYamlFile(
            str(MODELS_DIR / f"paddle_text_recognition.{platform}.yaml")
        )
        rec_model_nn_archive = dai.NNArchive(dai.getModelFromZoo(rec_model_description))
        rec_model_w, rec_model_h = rec_model_nn_archive.getInputSize()

        cam = pipeline.create(dai.node.Camera).build()
        cam_out = cam.requestOutput(
            size=(REQ_WIDTH, REQ_HEIGHT), type=frame_type, fps=fps_limit
        )

        resize_node = pipeline.create(dai.node.ImageManip)
        resize_node.initialConfig.setOutputSize(det_model_w, det_model_h)
        resize_node.initialConfig.setReusePreviousImage(False)
        cam_out.link(resize_node.inputImage)

        det_nn: ParsingNeuralNetwork = pipeline.create(ParsingNeuralNetwork).build(
            resize_node.out, det_model_nn_archive
        )
        det_nn.setNumPoolFrames(30)

        detection_process_node = pipeline.create(CropConfigsCreator)
        detection_process_node.build(
            det_nn.out, (REQ_WIDTH, REQ_HEIGHT), (rec_model_w, rec_model_h)
        )

        crop_node = pipeline.create(dai.node.ImageManip)
        crop_node.initialConfig.setReusePreviousImage(False)
        crop_node.inputConfig.setReusePreviousMessage(False)
        crop_node.inputImage.setReusePreviousMessage(True)
        crop_node.inputConfig.setMaxSize(30)
        crop_node.inputImage.setMaxSize(30)
        crop_node.setNumFramesPool(30)

        detection_process_node.config_output.link(crop_node.inputConfig)
        cam_out.link(crop_node.inputImage)

        ocr_nn: ParsingNeuralNetwork = pipeline.create(ParsingNeuralNetwork).build(
            crop_node.out, rec_model_nn_archive
        )
        ocr_nn.setNumPoolFrames(30)
        ocr_nn.input.setMaxSize(30)

        gather_data_node = pipeline.create(GatherData).build(fps_limit)
        detection_process_node.detections_output.link(gather_data_node.input_reference)
        ocr_nn.out.link(gather_data_node.input_data)

        annotation_node = pipeline.create(OCRAnnotationNode)
        gather_data_node.out.link(annotation_node.input)
        det_nn.passthrough.link(annotation_node.passthrough)

        frame_queue = annotation_node.frame_output.createOutputQueue()

        pipeline.start()
        while pipeline.isRunning():
            frame_msg = frame_queue.get()
            if frame_msg is None:
                continue
            frame = frame_msg.getCvFrame()
            _, jpeg = cv2.imencode(".jpg", frame)
            with frame_lock:
                latest_frame = jpeg.tobytes()


def generate_mjpeg():
    while True:
        with frame_lock:
            frame = latest_frame
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )


@app.get("/devices")
def list_devices():
    devices = dai.Device.getAllAvailableDevices()
    return JSONResponse([
        {
            "mxid": d.deviceId,
            "name": d.name,
            "state": str(d.state),
        }
        for d in devices
    ])


@app.post("/connect")
def connect(body: dict):
    global capture_thread
    ip = body.get("ip")
    if not ip:
        return JSONResponse({"error": "No IP provided"}, status_code=400)
    if capture_thread and capture_thread.is_alive():
        return JSONResponse({"error": "Already connected"}, status_code=400)
    capture_thread = threading.Thread(target=capture_loop, args=(ip,), daemon=True)
    capture_thread.start()
    return JSONResponse({"status": "connecting", "ip": ip})


@app.get("/status")
def status():
    return JSONResponse({
        "streaming": latest_frame is not None,
        "thread_alive": capture_thread is not None and capture_thread.is_alive()
    })


@app.get("/video-feed")
def video_feed():
    return StreamingResponse(
        generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
