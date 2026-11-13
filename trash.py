"""
Thung rac (trash / recycle bin) cho camera va su kien canh bao.

Khi xoa "thuong" (soft delete), ban ghi KHONG bi xoa khoi cameras.json/
incidents.json ngay - chi duoc gan them truong "deleted_at" (thoi diem xoa).
Cac ham _my_cameras()/_my_incidents() trong app.py loc bo nhung ban ghi co
deleted_at, nen chung "bien mat" khoi giao dien binh thuong nhung van con
tren dia, cho toi khi:
  (a) nguoi dung tu tay "Khoi phuc" (xoa truong deleted_at), hoac
  (b) nguoi dung tu tay "Xoa vinh vien" trong trang Thung rac, hoac
  (c) qua RETENTION_DAYS ngay ma khong ai dong toi - purge_expired() (chay
      nen dinh ky, xem start_background_purger()) se tu xoa han.

"Xoa vinh vien" (hard delete) - dung khi nguoi dung chon thang "Xoa vinh
vien" ngay tu dau, hoac khi don don thung rac - xoa hoan toan khoi
cameras.json/incidents.json VA xoa luon file video/anh tren dia (voi su
kien). Khong the hoan tac.
"""
import datetime
import os
import threading
import time

import storage

RETENTION_DAYS = 15
PURGE_INTERVAL_SECONDS = 3600  # kiem tra don thung rac moi 1 gio


def _parse_iso(value):
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def is_deleted(record):
    return bool(record.get("deleted_at"))


def days_left(deleted_at):
    """So ngay con lai truoc khi 1 muc trong thung rac bi tu dong xoa han.
    Tra ve 0 neu da qua han (se duoc purge_expired() don trong lan chay ke tiep)."""
    dt = _parse_iso(deleted_at)
    if dt is None:
        return RETENTION_DAYS
    expires_at = dt + datetime.timedelta(days=RETENTION_DAYS)
    remaining = (expires_at - datetime.datetime.now()).total_seconds()
    return max(0, int(remaining // 86400) + (1 if remaining % 86400 > 0 else 0))


def mark_deleted(record):
    record["deleted_at"] = datetime.datetime.now().isoformat(timespec="seconds")


def unmark_deleted(record):
    record["deleted_at"] = None


def _is_expired(deleted_at, cutoff):
    dt = _parse_iso(deleted_at)
    return dt is not None and dt <= cutoff


def purge_expired(retention_days=RETENTION_DAYS):
    """Don han cac muc trong thung rac da qua retention_days ngay: xoa han
    khoi JSON, va voi su kien thi xoa luon file video/anh tren dia. Tra ve
    (so_camera_da_xoa, so_su_kien_da_xoa) de tien ghi log/kiem thu."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)

    cams = storage.load_cameras()
    keep_cams = [c for c in cams if not _is_expired(c.get("deleted_at"), cutoff)]
    purged_cams = len(cams) - len(keep_cams)
    if purged_cams:
        storage.save_cameras(keep_cams)

    incidents = storage.load_incidents()
    keep_incidents = []
    purged_incidents = 0
    for inc in incidents:
        if _is_expired(inc.get("deleted_at"), cutoff):
            for fname, folder in (
                (inc.get("video_file"), storage.VIDEOS_DIR),
                (inc.get("image_file"), storage.IMAGES_DIR),
            ):
                if fname:
                    path = os.path.join(folder, fname)
                    if os.path.exists(path):
                        os.remove(path)
            purged_incidents += 1
        else:
            keep_incidents.append(inc)
    if purged_incidents:
        storage.save_incidents(keep_incidents)

    return purged_cams, purged_incidents


def start_background_purger():
    """Chay 1 luong nen: don thung rac ngay luc khoi dong, roi lap lai moi
    PURGE_INTERVAL_SECONDS - de cac muc qua han 15 ngay tu dong bi xoa han
    ke ca khi khong co ai mo trang Thung rac."""

    def _loop():
        while True:
            try:
                purge_expired()
            except Exception:
                pass
            time.sleep(PURGE_INTERVAL_SECONDS)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
