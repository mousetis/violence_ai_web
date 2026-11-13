"""
Dich vu phat hien doc lap chay TREN/CANH CAMERA (kien truc "Edge AI").

Muc dich: tach viec QUAY + PHAT HIEN ra khoi web app, dung DUNG lai
CameraWorker (dinh nghia trong camera_manager.py) - noi da co san toan bo
logic ket noi camera, dem frame de quay truoc/sau su kien, ghi video, chup
anh... CHI THAY DOI 1 diem duy nhat: thay vi ghi ket qua thang vao file JSON
cua web app (LocalStorageSink, dung khi CameraWorker chay ngay trong tien
trinh Flask), o day dung RemoteApiSink de GOI HTTP len API cua web app.

Nho tach nhu vay:
  - Camera/thiet bi nay van tu quay + tu phat hien BINH THUONG ke ca khi web
    app dang tat hoac mat mang - ket qua se duoc xep hang cho tren dia va tu
    dong gui lai khi ket noi duoc (xem RemoteApiSink._queue_for_retry va ham
    reconcile_pending() ben duoi).
  - Cung 1 thiet bi/script nay co the goi ve NHIEU web app khac nhau (chi
    can chay nhieu tien trinh voi config base_url khac nhau) - dap ung y
    "nhieu web app / nhieu noi dung chung 1 bo may AI".
  - Khi co model AI that (thay MotionDetector trong detection.py), CHI CAN
    sua 1 cho duy nhat (xem detection.py) - detector_service.py va
    camera_manager.py khong can dong lai.

CACH DUNG:
  1. Copy nguyen thu muc project nay (can storage.py, camera_manager.py,
     detection.py, requirements.txt) sang thiet bi AI gan camera (vi du
     Jetson Nano, mini PC, hoac chinh may tinh nhung chay rieng tien trinh
     nay thay vi app.py).
  2. Cai dat thu vien: pip install -r requirements.txt
  3. Tren web app (trang Cai dat), lay "Dia chi web app" va "Khoa API".
  4. Tren trang Camera, tao 1 camera moi voi che do "Camera/thiet bi AI tu
     gui du lieu" - ghi lai camera_id duoc cap (xem trong trang chi tiet
     camera do).
  5. Sua detector_config.json (tao ra khi chay lan dau, xem ham
     _default_config()) hoac dat bien moi truong tuong ung, roi chay:
         python detector_service.py
"""
import json
import os
import sys
import threading
import time

import storage
import camera_manager
from camera_manager import CameraWorker, RemoteApiSink

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "detector_config.json")
RECONCILE_INTERVAL_SECONDS = 30


def _default_config():
    return {
        "web_app_url": "http://DIA_CHI_WEB_APP:5000",
        "api_key": "DAN_KHOA_API_TU_TRANG_CAI_DAT_VAO_DAY",
        "camera": {
            "id": "DAN_CAMERA_ID_TU_TRANG_CHI_TIET_CAMERA_VAO_DAY",
            "name": "Camera Edge AI",
            "source_type": "webcam",
            "webcam_index": 0,
            "rtsp_url": "",
            "sensitivity": 0.03,
            "orientation": "none",
        },
    }


def load_config():
    if not os.path.exists(CONFIG_FILE):
        cfg = _default_config()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"[detector_service] Chua co cau hinh - da tao san file mau tai:\n  {CONFIG_FILE}")
        print("[detector_service] Hay mo file nay, dien dia chi web app / khoa API / thong tin camera roi chay lai.")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Bien moi truong duoc uu tien hon (tien cho trien khai bang Docker/systemd)
    cfg["web_app_url"] = os.environ.get("WEB_APP_URL", cfg.get("web_app_url", ""))
    cfg["api_key"] = os.environ.get("API_KEY", cfg.get("api_key", ""))
    if os.environ.get("CAMERA_ID"):
        cfg.setdefault("camera", {})["id"] = os.environ["CAMERA_ID"]

    cam = cfg.get("camera", {})
    if not cfg.get("web_app_url") or "DIA_CHI_WEB_APP" in cfg["web_app_url"]:
        sys.exit("[detector_service] Chưa cấu hình web_app_url trong detector_config.json (hoặc biến môi trường WEB_APP_URL).")
    if not cfg.get("api_key") or "DAN_KHOA_API" in cfg["api_key"]:
        sys.exit("[detector_service] Chưa cấu hình api_key trong detector_config.json (hoặc biến môi trường API_KEY) - lấy tại trang Cài đặt của web app.")
    if not cam.get("id") or "DAN_CAMERA_ID" in cam.get("id", ""):
        sys.exit("[detector_service] Chưa cấu hình camera.id trong detector_config.json - lấy tại trang chi tiết camera trên web app (camera phải ở chế độ Edge AI).")

    return cfg


def reconcile_pending(sink: RemoteApiSink):
    """Chay nen: dinh ky quet lai hang cho (cac su kien gui khong thanh cong
    truoc do, vi du luc web app dang tat) va thu gui lai. Day la phan giu
    cho yeu cau 'camera van hoat dong doc lap ke ca khi web app tat' duoc
    ap dung day du: khong chi TIEP TUC quay/phat hien, ma con KHONG MAT du
    lieu da phat hien duoc trong luc web app khong san sang."""
    import requests
    while True:
        time.sleep(RECONCILE_INTERVAL_SECONDS)
        if not os.path.isdir(sink.queue_dir):
            continue
        for entry_id in list(os.listdir(sink.queue_dir)):
            entry_dir = os.path.join(sink.queue_dir, entry_id)
            payload_path = os.path.join(entry_dir, "payload.json")
            if not os.path.exists(payload_path):
                continue
            try:
                with open(payload_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                kind = payload["kind"]
                incident = payload["incident"]
                files = {}
                if payload.get("video_file"):
                    files["video"] = open(os.path.join(entry_dir, payload["video_file"]), "rb")
                if payload.get("image_file"):
                    files["image"] = open(os.path.join(entry_dir, payload["image_file"]), "rb")

                if kind == "new":
                    data = {
                        "id": incident["id"], "camera_id": incident["camera_id"],
                        "timestamp": incident["timestamp"], "label": incident["label"],
                        "confidence": str(incident["confidence"]), "description": incident["description"],
                    }
                    resp = requests.post(f"{sink.base_url}/api/incidents", data=data,
                                          files=files or None, headers=sink._headers(), timeout=sink.timeout)
                else:
                    resp = requests.post(f"{sink.base_url}/api/incidents/{incident['id']}/finish",
                                          files=files or None, headers=sink._headers(), timeout=sink.timeout)

                for f in files.values():
                    f.close()

                if resp.status_code == 200:
                    import shutil
                    shutil.rmtree(entry_dir, ignore_errors=True)
                    print(f"[detector_service] Đã gửi lại thành công mục chờ {entry_id}")
            except Exception as exc:
                print(f"[detector_service] Vẫn chưa gửi lại được mục chờ {entry_id}: {exc}")


def main():
    cfg = load_config()
    storage.init_storage()

    queue_dir = os.path.join(storage.DATA_DIR, "pending_uploads")
    sink = RemoteApiSink(base_url=cfg["web_app_url"], api_key=cfg["api_key"], queue_dir=queue_dir)

    threading.Thread(target=reconcile_pending, args=(sink,), daemon=True).start()

    camera = dict(cfg["camera"])
    camera.setdefault("owner_id", None)  # web app tu gan owner_id theo camera_id, khong can gui len

    print(f"[detector_service] Bắt đầu quay + phát hiện cho camera '{camera.get('name')}' (id={camera.get('id')})")
    print(f"[detector_service] Kết quả sẽ được gửi về: {cfg['web_app_url']}")
    worker = CameraWorker(camera, sink=sink)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(timeout=1.0)
    except KeyboardInterrupt:
        print("\n[detector_service] Đang dừng...")
        worker.stop()
        worker.join(timeout=5.0)


if __name__ == "__main__":
    main()
