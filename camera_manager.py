"""
Quan ly ket noi camera RTSP: doc frame lien tuc, hien thi live view (MJPEG),
chay bo phat hien tren tung khung hinh, va tu dong cat video + luu anh +
ghi metadata khi co canh bao.

Moi camera chay tren 1 thread rieng (CameraWorker). Neu mat ket noi RTSP se
tu dong thu ket noi lai.
"""
import collections
import datetime
import os
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np

import storage
from detection import MotionDetector

FRAME_WIDTH = 960            # resize khung hinh live/luu de do CPU
BUFFER_SECONDS = 5           # giu lai N giay TRUOC khi co canh bao
POST_EVENT_SECONDS = 8       # quay them N giay SAU khi co canh bao
COOLDOWN_SECONDS = 20        # thoi gian toi thieu giua 2 canh bao tren cung 1 camera
DETECT_EVERY_N_FRAMES = 2    # chay bo phat hien moi N khung (do CPU)
JPEG_QUALITY = 80

FFMPEG_PATH = shutil.which("ffmpeg")  # neu co ffmpeg, se chuyen clip sang H.264
                                        # de trinh duyet phat duoc muot hon

ORIENTATIONS = ("none", "flip_h", "flip_v", "rotate_180")


class IncidentSink:
    """Noi 'gui' ket qua phat hien den - tach rieng KHOI logic bat/ghi hinh
    cua CameraWorker de cung 1 CameraWorker co the chay theo 2 cach:
      - Trong tien trinh web app (LocalStorageSink): ghi thang vao JSON/data/
        cua chinh web app nay - HANH VI HIEN TAI, khong doi.
      - Trong 1 tien trinh doc lap chay ngay tren/canh camera (RemoteApiSink,
        dung trong detector_service.py): goi HTTP len API cua web app thay vi
        ghi truc tiep - day la kien truc "Edge AI": camera/thiet bi bien tu
        quay + tu phat hien, web app chi con la noi NHAN va hien thi ket qua.
    """

    def save_new(self, incident):
        """incident: dict metadata, video_path/image_path da duoc ghi ra dia
        (o VIDEOS_DIR/IMAGES_DIR cuc bo cua ben goi). Goi ngay khi bat dau
        quay (truoc khi quay xong) de khong bi mat du lieu neu tien trinh
        dung dot ngot giua chung."""
        raise NotImplementedError

    def mark_done(self, incident_id, video_path):
        """Bao hieu qua trinh hau xu ly (chuyen ma H.264) da xong."""
        raise NotImplementedError


class LocalStorageSink(IncidentSink):
    """Hanh vi MAC DINH, dung khi CameraWorker chay ngay trong tien trinh
    web app (nhu tu truoc gio): ghi thang vao file JSON cuc bo."""

    def save_new(self, incident):
        clean = {k: v for k, v in incident.items() if not k.startswith("_")}
        storage.add_incident(clean)

    def mark_done(self, incident_id, video_path):
        storage.update_incident(incident_id, {"status": "done"})


class RemoteApiSink(IncidentSink):
    """Dung trong detector_service.py (chay tren/canh camera co AI). Goi
    HTTP POST len API cua web app (/api/incidents, /api/incidents/<id>/finish)
    thay vi ghi truc tiep vao JSON. Neu web app dang tam thoi khong chay
    (mat mang, dang khoi dong lai...), incident se duoc XEP HANG CHO tren
    dia cuc bo va thu gui lai sau - dam bao camera van "hoat dong doc lap"
    ke ca khi web app dang tat, dung yeu cau da thong nhat."""

    def __init__(self, base_url, api_key, queue_dir, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.queue_dir = queue_dir
        self.timeout = timeout
        os.makedirs(self.queue_dir, exist_ok=True)

    def _headers(self):
        return {"X-API-Key": self.api_key}

    def save_new(self, incident):
        video_path = incident.get("_local_video_path")
        image_path = incident.get("_local_image_path")
        try:
            import requests
            files = {}
            if image_path and os.path.exists(image_path):
                files["image"] = (os.path.basename(image_path), open(image_path, "rb"), "image/jpeg")
            data = {
                "id": incident["id"],
                "camera_id": incident["camera_id"],
                "timestamp": incident["timestamp"],
                "label": incident["label"],
                "confidence": str(incident["confidence"]),
                "description": incident["description"],
            }
            resp = requests.post(f"{self.base_url}/api/incidents", data=data, files=files or None,
                                  headers=self._headers(), timeout=self.timeout)
            for f in files.values():
                f[1].close()
            if resp.status_code == 200:
                return
        except Exception:
            pass
        self._queue_for_retry("new", incident, video_path, image_path)

    def mark_done(self, incident_id, video_path):
        try:
            import requests
            files = {}
            if video_path and os.path.exists(video_path):
                files["video"] = (os.path.basename(video_path), open(video_path, "rb"), "video/mp4")
            resp = requests.post(f"{self.base_url}/api/incidents/{incident_id}/finish",
                                  files=files or None, headers=self._headers(), timeout=self.timeout)
            for f in files.values():
                f[1].close()
            if resp.status_code == 200:
                return
        except Exception:
            pass
        self._queue_for_retry("finish", {"id": incident_id}, video_path, None)

    def _queue_for_retry(self, kind, incident, video_path, image_path):
        """Luu lai 1 ban ghi cho de thu gui lai sau (xem ham reconcile() trong
        detector_service.py) - khong lam mat du lieu khi web app dang tat."""
        import json as _json
        import shutil as _shutil
        import uuid as _uuid
        entry_id = _uuid.uuid4().hex[:10]
        entry_dir = os.path.join(self.queue_dir, entry_id)
        os.makedirs(entry_dir, exist_ok=True)
        payload = {"kind": kind, "incident": incident}
        if video_path and os.path.exists(video_path):
            dest = os.path.join(entry_dir, "video.mp4")
            _shutil.copy2(video_path, dest)
            payload["video_file"] = "video.mp4"
        if image_path and os.path.exists(image_path):
            dest = os.path.join(entry_dir, "image.jpg")
            _shutil.copy2(image_path, dest)
            payload["image_file"] = "image.jpg"
        with open(os.path.join(entry_dir, "payload.json"), "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)


class PushCameraState:
    """Trang thai cua 1 camera o che do 'push' (Edge AI tu goi ve): khong co
    CameraWorker/thread ket noi RTSP nao ca ben phia web app - web app chi
    thu dong nhan khung hinh moi nhat va su kien qua API. Lop nay chi de
    tuong thich giao dien voi CameraWorker (get_latest_jpeg/get_status) de
    cac route/template dung chung logic ma khong can phan biet 2 loai."""

    def __init__(self, camera):
        self.camera = camera
        self._lock = threading.Lock()
        self._latest_jpeg = None
        self._last_seen = 0.0

    def feed_jpeg(self, jpeg_bytes):
        with self._lock:
            self._latest_jpeg = jpeg_bytes
            self._last_seen = time.time()

    def touch(self):
        """Danh dau 'con song' ke ca khi thiet bi khong gui khung hinh live
        (vi du chi gui su kien khi co canh bao, khong stream lien tuc)."""
        with self._lock:
            self._last_seen = time.time()

    def get_latest_jpeg(self):
        with self._lock:
            return self._latest_jpeg

    def get_status(self):
        with self._lock:
            last_seen = self._last_seen
        if last_seen == 0:
            return {"status": "offline", "error": "Chưa nhận được dữ liệu nào từ thiết bị AI",
                    "name": self.camera.get("name")}
        if time.time() - last_seen > 60:
            return {"status": "offline", "error": "Thiết bị AI không phản hồi hơn 60 giây",
                    "name": self.camera.get("name")}
        return {"status": "live", "error": None, "name": self.camera.get("name")}

    def stop(self):
        pass



def _apply_orientation(frame, orientation):
    """Xoay/lat khung hinh theo cau hinh cua camera. CHI ap dung DUY NHAT 1
    lan, ngay sau khi doc frame tu nguon - dam bao live view, video luu va
    anh chup luon dong nhat chieu anh voi nhau (khong the bi lech nhau)."""
    if orientation == "flip_h":
        return cv2.flip(frame, 1)
    if orientation == "flip_v":
        return cv2.flip(frame, 0)
    if orientation == "rotate_180":
        return cv2.flip(frame, -1)
    return frame


def _transcode_to_h264(path):
    """Chuyen video sang H.264 (yuv420p) bang ffmpeg de trinh duyet xem duoc
    truc tiep. Neu may khong co ffmpeg thi bo qua (file van xem duoc bang
    VLC/trinh phat khac, chi la co the khong phat truc tiep tren trinh duyet)."""
    if not FFMPEG_PATH or not os.path.exists(path):
        return
    tmp_path = path + ".tmp.mp4"
    try:
        result = subprocess.run(
            [FFMPEG_PATH, "-y", "-i", path, "-c:v", "libx264", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp_path],
            capture_output=True, timeout=90,
        )
        if result.returncode == 0 and os.path.exists(tmp_path):
            os.replace(tmp_path, path)
        elif os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


class CameraWorker(threading.Thread):
    def __init__(self, camera, sink=None):
        super().__init__(daemon=True)
        self.camera = camera
        self.camera_id = camera["id"]
        self.sink = sink if sink is not None else LocalStorageSink()
        self._stop_flag = threading.Event()
        self._lock = threading.Lock()
        self._latest_jpeg = None
        self.status = "connecting"   # connecting | live | offline
        self.last_error = None

        self.detector = MotionDetector(sensitivity=camera.get("sensitivity", 0.03))

        self._frame_buffer = collections.deque()
        self._last_trigger_ts = 0.0

        self._writer = None
        self._writer_until = 0.0
        self._pending_incident = None

    # ---- doc tu ben ngoai (Flask routes) ----
    def get_latest_jpeg(self):
        with self._lock:
            return self._latest_jpeg

    def get_status(self):
        return {"status": self.status, "error": self.last_error, "name": self.camera.get("name")}

    def stop(self):
        self._stop_flag.set()

    # ---- vong lap chinh ----
    def run(self):
        while not self._stop_flag.is_set():
            source_type = self.camera.get("source_type", "rtsp")
            if source_type == "webcam":
                idx = int(self.camera.get("webcam_index", 0))
                if os.name == "nt":
                    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                else:
                    cap = cv2.VideoCapture(idx)
            else:
                cap = cv2.VideoCapture(self.camera.get("rtsp_url", ""))

            if not cap.isOpened():
                self.status = "offline"
                if source_type == "webcam":
                    self.last_error = (f"Không mở được webcam #{self.camera.get('webcam_index', 0)} "
                                        f"(có thể đang được ứng dụng khác dùng, hoặc máy không có webcam này)")
                else:
                    self.last_error = "Không kết nối được tới RTSP URL"
                cap.release()
                if self._sleep_or_stop(5):
                    return
                continue

            self.status = "live"
            self.last_error = None
            fps = cap.get(cv2.CAP_PROP_FPS)
            if not fps or fps <= 1 or fps > 60:
                fps = 15.0
            self._frame_buffer = collections.deque(maxlen=int(fps * BUFFER_SECONDS))
            frame_i = 0

            while not self._stop_flag.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    self.status = "offline"
                    self.last_error = "Mất kết nối / không đọc được khung hình"
                    break

                frame = _apply_orientation(frame, self.camera.get("orientation", "none"))

                frame_i += 1
                now = time.time()

                h, w = frame.shape[:2]
                if w > FRAME_WIDTH:
                    scale = FRAME_WIDTH / w
                    frame = cv2.resize(frame, (FRAME_WIDTH, int(h * scale)))

                self._frame_buffer.append((now, frame))

                ok2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if ok2:
                    with self._lock:
                        self._latest_jpeg = buf.tobytes()

                if self._writer is not None:
                    # dang quay clip canh bao -> ghi tiep khung hien tai
                    self._writer.write(frame)
                    if now >= self._writer_until:
                        self._finalize_incident()
                elif frame_i % DETECT_EVERY_N_FRAMES == 0:
                    result = self.detector.process_frame(frame)
                    if result.triggered and (now - self._last_trigger_ts) > COOLDOWN_SECONDS:
                        self._last_trigger_ts = now
                        self._start_incident(frame, result, fps, now)

            cap.release()
            self.status = "offline"
            if self._sleep_or_stop(3):
                return

        if self._writer is not None:
            self._finalize_incident()

    def _sleep_or_stop(self, seconds):
        """Ngu 'seconds' giay nhung kiem tra stop_flag moi 0.1s. Tra ve True neu bi stop."""
        steps = int(seconds / 0.1)
        for _ in range(steps):
            if self._stop_flag.is_set():
                return True
            time.sleep(0.1)
        return False

    # ---- xu ly khi co canh bao ----
    def _start_incident(self, trigger_frame, result, fps, now):
        incident_id = storage.new_id()
        video_name = f"{incident_id}.mp4"
        image_name = f"{incident_id}.jpg"
        video_path = os.path.join(storage.VIDEOS_DIR, video_name)
        image_path = os.path.join(storage.IMAGES_DIR, image_name)

        h, w = trigger_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(video_path, fourcc, max(fps, 5.0), (w, h))

        for ts, f in self._frame_buffer:
            if f.shape[:2] != (h, w):
                f = cv2.resize(f, (w, h))
            writer.write(f)

        cv2.imwrite(image_path, trigger_frame)

        self._writer = writer
        self._writer_until = now + POST_EVENT_SECONDS
        incident = {
            "id": incident_id,
            "camera_id": self.camera_id,
            "camera_name": self.camera.get("name", self.camera_id),
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "label": result.label,
            "confidence": round(result.confidence, 3),
            "description": result.description,
            "video_file": video_name,
            "image_file": image_name,
            "reviewed": False,
            "note": "",
            "status": "recording",  # -> "done" sau khi hau xu ly xong (xem _post_process_incident)
        }
        self._pending_incident = incident
        # Ghi metadata NGAY, khong cho luong nen xu ly xong: neu tien trinh bi
        # tat dot ngot giua chung (truoc khi chuyen ma xong), su kien van con
        # dau vet day du (video/anh/mo ta) thay vi bi "mo coi". Voi RemoteApiSink
        # (Edge AI), "ghi" o day nghia la GOI VE web app - neu web app dang tat
        # thi sink se tu xep hang cho gui lai sau, khong lam mat du lieu.
        incident_for_sink = dict(incident)
        incident_for_sink["_local_video_path"] = video_path
        incident_for_sink["_local_image_path"] = image_path
        self.sink.save_new(incident_for_sink)

    def _finalize_incident(self):
        writer = self._writer
        incident = self._pending_incident
        self._writer = None
        self._pending_incident = None
        if writer is not None:
            writer.release()
        if incident is not None:
            threading.Thread(target=self._post_process_incident, args=(incident,), daemon=True).start()

    def _post_process_incident(self, incident):
        video_path = os.path.join(storage.VIDEOS_DIR, incident["video_file"])
        _transcode_to_h264(video_path)
        self.sink.mark_done(incident["id"], video_path)


class CameraManager:
    """Quan ly ca 2 loai camera:
      - 'pull' (mac dinh, hanh vi cu): web app tu ket noi RTSP/webcam va tu
        chay bo phat hien - dung 1 CameraWorker (thread) cho moi camera.
      - 'push' (Edge AI): camera/thiet bi AI rieng tu quay + tu phat hien va
        GOI VE web app qua API (xem app.py: /api/incidents, /api/cameras/<id>/frame).
        Web app khong mo ket noi nao ca, chi giu 1 PushCameraState de nhan
        khung hinh/su kien va hien thi lai cho nguoi dung."""

    def __init__(self):
        self._workers = {}   # camera_id -> CameraWorker (pull) hoac PushCameraState (push)
        self._lock = threading.Lock()

    def start_all(self):
        for cam in storage.load_cameras():
            self.start_camera(cam)

    def start_camera(self, camera):
        with self._lock:
            self._stop_camera_locked(camera["id"])
            if camera.get("input_mode") == "push":
                # Khong mo ket noi/thread nao ca - chi cho nhan du lieu qua API.
                self._workers[camera["id"]] = PushCameraState(camera)
            else:
                worker = CameraWorker(camera)
                worker.start()
                self._workers[camera["id"]] = worker

    def stop_camera(self, camera_id):
        with self._lock:
            self._stop_camera_locked(camera_id)

    def _stop_camera_locked(self, camera_id):
        w = self._workers.pop(camera_id, None)
        if w:
            w.stop()

    def get_worker(self, camera_id):
        return self._workers.get(camera_id)

    def feed_push_frame(self, camera_id, jpeg_bytes):
        """Nhan 1 khung hinh moi tu thiet bi Edge AI (che do 'push')."""
        state = self._workers.get(camera_id)
        if isinstance(state, PushCameraState):
            state.feed_jpeg(jpeg_bytes)
            return True
        return False

    def touch_push_camera(self, camera_id):
        state = self._workers.get(camera_id)
        if isinstance(state, PushCameraState):
            state.touch()
            return True
        return False

    def status_map(self):
        return {cid: w.get_status() for cid, w in self._workers.items()}


manager = CameraManager()
