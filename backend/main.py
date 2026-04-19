import json
import re
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import cv2
import depthai as dai
from depthai_nodes.node import ParsingNeuralNetwork, GatherData, ImgDetectionsBridge
from depthai_nodes.node.utils import generate_script_content
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from utils.annotation_node import OCRAnnotationNode
from utils.host_process_detections import CropConfigsCreator

REQ_WIDTH, REQ_HEIGHT = 1152, 640
MODELS_DIR = Path(__file__).parent / "depthai_models"
DATA_DIR = Path(__file__).parent / "data" / "predavanja"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _predavanje_slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "").strip())
    return (s[:80] or "default")

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

# Engagement logging is toggled by /engagement/start and /engagement/stop
# (called from the frontend Start/Stop buttons).
engagement_logging = False

engagement_state_lock = threading.Lock()
engagement_state = {
    "frames": 0,
    "face_yes": 0,
    "pitch_yes": 0,
    "yaw_left": 0,
    "yaw_right": 0,
    "yaw_forward": 0,
}
engagement_final_score = 0.0
engagement_current_live = 0.0


def engagement_reset():
    with engagement_state_lock:
        for k in engagement_state:
            engagement_state[k] = 0


def engagement_update(face_detected, yaw, pitch):
    with engagement_state_lock:
        engagement_state["frames"] += 1
        if face_detected:
            engagement_state["face_yes"] += 1
        if pitch is not None and pitch < 30:
            engagement_state["pitch_yes"] += 1
        if yaw is not None:
            if abs(yaw) <= 10:
                engagement_state["yaw_forward"] += 1
            elif yaw > 10:
                engagement_state["yaw_right"] += 1
            else:
                engagement_state["yaw_left"] += 1


def _yaw_balance_score():
    total = (
        engagement_state["yaw_left"]
        + engagement_state["yaw_right"]
        + engagement_state["yaw_forward"]
    )
    if total == 0:
        return 0.0
    f = engagement_state["yaw_forward"] / total
    l = engagement_state["yaw_left"] / total
    r = engagement_state["yaw_right"] / total
    balance = 1 - (abs(f - 0.33) + abs(l - 0.33) + abs(r - 0.33)) / 2
    balance = max(0.0, min(1.0, balance))
    return 0.4 * balance


def engagement_live_score(face_detected, pitch):
    face_score = 0.3 if face_detected else 0.0
    pitch_score = 0.3 if (pitch is not None and pitch < 30) else 0.0
    with engagement_state_lock:
        yaw_score = _yaw_balance_score()
    return (face_score + pitch_score + yaw_score) * 100


def engagement_final_compute():
    global engagement_final_score
    with engagement_state_lock:
        frames = engagement_state["frames"]
        if frames == 0:
            engagement_final_score = 0.0
            return 0.0
        face_pct = engagement_state["face_yes"] / frames
        pitch_pct = engagement_state["pitch_yes"] / frames
        face_score = 0.3 * face_pct
        pitch_score = 0.3 * pitch_pct
        yaw_score = _yaw_balance_score()
    engagement_final_score = (face_score + pitch_score + yaw_score) * 100
    return engagement_final_score


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

        # --- Engagement branch: YuNet face detection + head pose estimation ---
        engagement_det_queue = None
        engagement_pose_queue = None
        try:
            yunet_desc = dai.NNModelDescription.fromYamlFile(
                str(MODELS_DIR / f"yunet.{platform}.yaml")
            )
            yunet_archive = dai.NNArchive(dai.getModelFromZoo(yunet_desc))
            yunet_w, yunet_h = yunet_archive.getInputSize()

            pose_desc = dai.NNModelDescription.fromYamlFile(
                str(MODELS_DIR / f"head_pose_estimation.{platform}.yaml")
            )
            pose_archive = dai.NNArchive(dai.getModelFromZoo(pose_desc))
            pose_w, pose_h = pose_archive.getInputSize()

            face_resize = pipeline.create(dai.node.ImageManip)
            face_resize.initialConfig.setOutputSize(yunet_w, yunet_h)
            face_resize.initialConfig.setReusePreviousImage(False)
            cam_out.link(face_resize.inputImage)

            face_det_nn: ParsingNeuralNetwork = pipeline.create(ParsingNeuralNetwork).build(
                face_resize.out, yunet_archive
            )

            det_bridge = pipeline.create(ImgDetectionsBridge).build(face_det_nn.out)

            face_script = pipeline.create(dai.node.Script)
            det_bridge.out.link(face_script.inputs["det_in"])
            cam_out.link(face_script.inputs["preview"])
            face_script.setScript(
                generate_script_content(resize_width=pose_w, resize_height=pose_h)
            )

            face_crop = pipeline.create(dai.node.ImageManip)
            face_crop.initialConfig.setOutputSize(pose_w, pose_h)
            face_crop.inputConfig.setWaitForMessage(True)
            face_script.outputs["manip_cfg"].link(face_crop.inputConfig)
            face_script.outputs["manip_img"].link(face_crop.inputImage)

            pose_nn: ParsingNeuralNetwork = pipeline.create(ParsingNeuralNetwork).build(
                face_crop.out, pose_archive
            )

            pose_gather = pipeline.create(GatherData).build(fps_limit)
            pose_nn.outputs.link(pose_gather.input_data)
            face_det_nn.out.link(pose_gather.input_reference)

            engagement_det_queue = face_det_nn.out.createOutputQueue()
            engagement_pose_queue = pose_gather.out.createOutputQueue()
            print("[engagement] pipeline branch ready")
        except Exception as e:
            print(f"[engagement] setup failed, skipping: {e}")

        def engagement_print_loop():
            global engagement_current_live
            last_yaw = None
            last_pitch = None
            last_face_time = 0.0
            last_print = 0.0
            prev_enabled = False
            while pipeline.isRunning():
                det_msg = None
                if engagement_det_queue is not None:
                    det_msg = engagement_det_queue.tryGet()
                    if det_msg is not None:
                        try:
                            if len(det_msg.detections) > 0:
                                last_face_time = time.time()
                        except Exception:
                            pass
                if engagement_pose_queue is not None:
                    pose_msg = engagement_pose_queue.tryGet()
                    if pose_msg is not None:
                        try:
                            groups = pose_msg.gathered
                            if groups:
                                g = groups[0]
                                last_yaw = float(g["0"].prediction)
                                last_pitch = float(g["2"].prediction)
                        except Exception:
                            pass
                
                now = time.time()
                if engagement_logging and not prev_enabled:
                    last_print = 0.0
                    engagement_reset()
                    last_yaw = None
                    last_pitch = None
                    last_face_time = 0.0
                    engagement_current_live = 0.0
                    print("[engagement] logging started")
                if not engagement_logging and prev_enabled:
                    final = engagement_final_compute()
                    print(f"[engagement] logging stopped — FINAL SCORE: {final:.2f}")
                prev_enabled = engagement_logging

                face_present_now = (now - last_face_time) < 0.8
                if engagement_logging and det_msg is not None:
                    engagement_update(face_present_now, last_yaw, last_pitch)

                if engagement_logging and (now - last_print) >= 0.3:
                    yaw_str = f"{last_yaw:+6.1f}" if last_yaw is not None else "  ---"
                    pitch_str = f"{last_pitch:+6.1f}" if last_pitch is not None else "  ---"
                    face_str = "YES" if face_present_now else "NO "
                    live = engagement_live_score(face_present_now, last_pitch)
                    engagement_current_live = live
                    print(
                        f"[engagement] face={face_str}  yaw={yaw_str}  pitch={pitch_str}  score={live:5.1f}"
                    )
                    last_print = now
                time.sleep(0.02)

        pipeline.start()
        threading.Thread(target=engagement_print_loop, daemon=True).start()
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


@app.post("/disconnect")
def disconnect():
    global capture_thread, pipeline_instance, latest_frame, engagement_logging
    engagement_logging = False
    if pipeline_instance is not None:
        try:
            pipeline_instance.stop()
        except Exception as e:
            print(f"pipeline stop error: {e}")
    if capture_thread is not None and capture_thread.is_alive():
        capture_thread.join(timeout=5.0)
    pipeline_instance = None
    capture_thread = None
    with frame_lock:
        latest_frame = None
    return JSONResponse({"status": "disconnected"})


@app.post("/engagement/start")
def engagement_start():
    global engagement_logging
    engagement_logging = True
    return JSONResponse({"logging": True})


@app.post("/engagement/stop")
def engagement_stop():
    global engagement_logging
    engagement_logging = False
    final = engagement_final_compute()
    print(f"[engagement] FINAL SCORE: {final:.2f}")
    return JSONResponse({"logging": False, "final_score": final})


@app.get("/engagement/score")
def engagement_score():
    return JSONResponse({
        "live_score": engagement_current_live,
        "final_score": engagement_final_score,
        "logging": engagement_logging,
    })


@app.get("/predavanja/{name}")
def get_predavanje(name: str):
    path = DATA_DIR / f"{_predavanje_slug(name)}.json"
    if not path.exists():
        return JSONResponse({
            "name": name,
            "transcript": "",
            "summary": "",
            "final_score": None,
            "ocr_items": [],
            "updated_at": None,
        })
    try:
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        return JSONResponse({"error": f"failed to read: {e}"}, status_code=500)


@app.put("/predavanja/{name}")
def put_predavanje(name: str, body: dict):
    path = DATA_DIR / f"{_predavanje_slug(name)}.json"
    data = {
        "name": name,
        "transcript": body.get("transcript", "") or "",
        "summary": body.get("summary", "") or "",
        "final_score": body.get("final_score", None),
        "ocr_items": list(body.get("ocr_items", []) or []),
        "updated_at": time.time(),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return JSONResponse(data)


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
