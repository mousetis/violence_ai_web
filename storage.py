"""
Lop luu tru file-based (khong dung database).
Moi du lieu duoc luu duoi dang file JSON + thu muc chua video/anh.
"""
import json
import os
import secrets
import threading
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
CAMERAS_FILE = os.path.join(DATA_DIR, "cameras.json")
API_KEY_FILE = os.path.join(DATA_DIR, "api_key.txt")
INCIDENTS_DIR = os.path.join(DATA_DIR, "incidents")
INCIDENTS_FILE = os.path.join(INCIDENTS_DIR, "incidents.json")
VIDEOS_DIR = os.path.join(INCIDENTS_DIR, "videos")
IMAGES_DIR = os.path.join(INCIDENTS_DIR, "images")

_lock = threading.Lock()


def init_storage():
    """Goi 1 lan luc app khoi dong: tao thu muc va cac file rong neu chua co."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(INCIDENTS_DIR, exist_ok=True)
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    if not os.path.exists(CAMERAS_FILE):
        _write_json(CAMERAS_FILE, [])
    if not os.path.exists(INCIDENTS_FILE):
        _write_json(INCIDENTS_FILE, [])


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def new_id():
    return uuid.uuid4().hex[:12]


# ---- API key cho thiet bi AI o bien (Edge AI) goi ve web app ----
# Mot khoa duy nhat cho toan he thong: cac camera/thiet bi AI gui du lieu ve
# qua API deu dung chung khoa nay (dat trong header "X-API-Key"). Quyen so
# huu du lieu van tach theo tung nguoi dung thong qua owner_id cua CAMERA
# duoc chi dinh trong moi yeu cau - khoa API chi la "ve" xac thuc thiet bi
# duoc phep goi vao he thong, khong phai la danh tinh nguoi dung.
def get_or_create_api_key():
    with _lock:
        if os.path.exists(API_KEY_FILE):
            try:
                with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                    key = f.read().strip()
                if key:
                    return key
            except OSError:
                pass
        key = secrets.token_hex(24)
        tmp = API_KEY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(key)
        os.replace(tmp, API_KEY_FILE)
        return key


def regenerate_api_key():
    """Tao khoa API moi, cac khoa cu se khong con dung duoc nua - dung khi
    nghi ngo khoa bi lo hoac muon thu hoi quyen truy cap cua thiet bi cu."""
    with _lock:
        key = secrets.token_hex(24)
        tmp = API_KEY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(key)
        os.replace(tmp, API_KEY_FILE)
        return key


# ---- Users ----
def load_users():
    with _lock:
        return _read_json(USERS_FILE, [])


def save_users(users):
    with _lock:
        _write_json(USERS_FILE, users)


# ---- Cameras ----
def load_cameras():
    with _lock:
        return _read_json(CAMERAS_FILE, [])


def save_cameras(cameras):
    with _lock:
        _write_json(CAMERAS_FILE, cameras)


# ---- Incidents (cac su kien phat hien bao luc) ----
def load_incidents():
    with _lock:
        return _read_json(INCIDENTS_FILE, [])


def save_incidents(incidents):
    with _lock:
        _write_json(INCIDENTS_FILE, incidents)


def add_incident(incident):
    with _lock:
        incidents = _read_json(INCIDENTS_FILE, [])
        incidents.insert(0, incident)  # moi nhat len dau
        _write_json(INCIDENTS_FILE, incidents)


def update_incident(incident_id, updates):
    """Cap nhat 1 vai truong cua 1 su kien da ton tai (theo id), giu nguyen
    cac truong con lai. Dung khi hau xu ly (chuyen ma H.264) hoan tat, sau
    khi metadata ban dau da duoc ghi truoc do bang add_incident()."""
    with _lock:
        incidents = _read_json(INCIDENTS_FILE, [])
        for inc in incidents:
            if inc.get("id") == incident_id:
                inc.update(updates)
                break
        _write_json(INCIDENTS_FILE, incidents)
