import depthai as dai
import cv2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import threading

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frame_lock = threading.Lock()
latest_frame = None
capture_thread = None  # NOT started on boot — only started after /connect

pipeline_instance = None

def capture_loop(ip: str):
    global latest_frame, pipeline_instance
    device_info = dai.DeviceInfo(ip)
    device = dai.Device(device_info)
    pipeline_instance = dai.Pipeline(device)
    cam = pipeline_instance.create(dai.node.Camera).build()
    video_queue = cam.requestOutput((640, 480), type=dai.ImgFrame.Type.BGR888i).createOutputQueue()
    pipeline_instance.start()
    while pipeline_instance.isRunning():
        frame_msg = video_queue.get() 
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