import hmac
import os
import time
import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, Response, send_from_directory, flash, abort, jsonify
)

import storage
import auth
import camera_manager
import trash
from camera_manager import manager

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())

def _migrate_legacy_owner_id():
    """Nang cap du lieu tu ban truoc khi co tinh nang tai khoan rieng: gan
    owner_id cho camera/su kien nao chua co, ve tai khoan CU NHAT trong he
    thong - de khong bi "mat" camera/su kien cu khi nang cap len ban co
    phan tach du lieu theo tung nguoi dung (moi tai khoan 1 silo rieng)."""
    users = storage.load_users()
    if not users:
        return
    fallback_owner = users[0]["id"]

    cams = storage.load_cameras()
    if any("owner_id" not in c for c in cams):
        for c in cams:
            c.setdefault("owner_id", fallback_owner)
        storage.save_cameras(cams)

    incs = storage.load_incidents()
    if any("owner_id" not in i for i in incs):
        for i in incs:
            i.setdefault("owner_id", fallback_owner)
        storage.save_incidents(incs)


storage.init_storage()
auth.ensure_default_admin()
_migrate_legacy_owner_id()
manager.start_all()
trash.start_background_purger()


@app.template_filter("vi_datetime")
def vi_datetime(value):
    """Hien thi thoi gian dang dd/mm/yyyy HH:MM:SS thay vi chuoi ISO tho."""
    try:
        dt = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return dt.strftime("%d/%m/%Y %H:%M:%S")


@app.context_processor
def inject_globals():
    return {"ffmpeg_available": camera_manager.FFMPEG_PATH is not None}


# ---------------- Dang nhap / dang ky / dang xuat ----------------
# Moi tai khoan la 1 "silo" rieng biet: camera va su kien cua tai khoan nay
# khong ai khac (ke ca tai khoan khac) xem duoc - xem ham _owned_* ben duoi.

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = auth.find_user(username)
        if user and auth.verify_password(password, user["password"]):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Sai tên đăng nhập hoặc mật khẩu.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not username:
            flash("Vui lòng nhập tên đăng nhập.", "error")
        elif auth.find_user(username):
            flash("Tên đăng nhập đã tồn tại, hãy chọn tên khác.", "error")
        elif len(password) < 6:
            flash("Mật khẩu cần ít nhất 6 ký tự.", "error")
        elif password != confirm:
            flash("Mật khẩu xác nhận không khớp.", "error")
        else:
            user = auth.create_user(username, password)
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash(f"Chào mừng {user['username']}! Tài khoản của bạn đã sẵn sàng — hãy thêm camera đầu tiên.", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- Truy vet quyen so huu (moi user 1 silo rieng) ----------------

def _my_cameras():
    uid = session.get("user_id")
    return [c for c in storage.load_cameras() if c.get("owner_id") == uid and not trash.is_deleted(c)]


def _my_incidents():
    uid = session.get("user_id")
    return [i for i in storage.load_incidents() if i.get("owner_id") == uid and not trash.is_deleted(i)]


def _my_trashed_cameras():
    uid = session.get("user_id")
    cams = [c for c in storage.load_cameras() if c.get("owner_id") == uid and trash.is_deleted(c)]
    cams.sort(key=lambda c: c.get("deleted_at") or "", reverse=True)
    return cams


def _my_trashed_incidents():
    uid = session.get("user_id")
    incs = [i for i in storage.load_incidents() if i.get("owner_id") == uid and trash.is_deleted(i)]
    incs.sort(key=lambda i: i.get("deleted_at") or "", reverse=True)
    return incs


def _owned_camera_or_none(camera_id):
    """Chi tim trong camera CON HOAT DONG (chua bi chuyen vao thung rac) -
    dung cho moi thao tac binh thuong (xem, sua, xem truc tiep...)."""
    uid = session.get("user_id")
    for c in storage.load_cameras():
        if c["id"] == camera_id and c.get("owner_id") == uid and not trash.is_deleted(c):
            return c
    return None


def _owned_incident_or_none(incident_id):
    """Tuong tu _owned_camera_or_none nhung cho su kien - bo qua su kien
    dang trong thung rac."""
    uid = session.get("user_id")
    for i in storage.load_incidents():
        if i["id"] == incident_id and i.get("owner_id") == uid and not trash.is_deleted(i):
            return i
    return None


def _owned_camera_any(camera_id):
    """Tim camera cua dung chu so huu BAT KE dang hoat dong hay dang trong
    thung rac - dung cho thao tac xoa vinh vien / khoi phuc."""
    uid = session.get("user_id")
    for c in storage.load_cameras():
        if c["id"] == camera_id and c.get("owner_id") == uid:
            return c
    return None


def _owned_incident_any(incident_id):
    uid = session.get("user_id")
    for i in storage.load_incidents():
        if i["id"] == incident_id and i.get("owner_id") == uid:
            return i
    return None


# ---------------- Dashboard ----------------

@app.route("/")
@auth.login_required
def dashboard():
    cameras = _my_cameras()
    statuses = manager.status_map()
    for c in cameras:
        c["_status"] = statuses.get(c["id"], {}).get("status", "offline")
    incidents = _my_incidents()
    return render_template(
        "dashboard.html",
        cameras=cameras,
        recent_incidents=incidents[:6],
        total_incidents=len(incidents),
        live_count=sum(1 for c in cameras if c["_status"] == "live"),
    )


# ---------------- Quan ly camera ----------------

@app.route("/cameras", methods=["GET", "POST"])
@auth.login_required
def cameras_page():
    if request.method == "POST":
        cams = storage.load_cameras()
        try:
            sensitivity = float(request.form.get("sensitivity", 0.03))
        except ValueError:
            sensitivity = 0.03

        source_type = request.form.get("source_type", "webcam")
        if source_type not in ("webcam", "rtsp"):
            source_type = "webcam"
        try:
            webcam_index = int(request.form.get("webcam_index", 0))
        except ValueError:
            webcam_index = 0
        rtsp_url = request.form.get("rtsp_url", "").strip()

        orientation = request.form.get("orientation", "none")
        if orientation not in ("none", "flip_h", "flip_v", "rotate_180"):
            orientation = "none"

        input_mode = request.form.get("input_mode", "pull")
        if input_mode not in ("pull", "push"):
            input_mode = "pull"

        if input_mode == "pull" and source_type == "rtsp" and not rtsp_url:
            flash("Vui lòng nhập đường dẫn RTSP.", "error")
            return redirect(url_for("cameras_page"))

        cam = {
            "id": storage.new_id(),
            "owner_id": session["user_id"],
            "name": request.form.get("name", "").strip() or "Camera",
            "input_mode": input_mode,
            "source_type": source_type,
            "webcam_index": webcam_index,
            "rtsp_url": rtsp_url,
            "sensitivity": sensitivity,
            "orientation": orientation,
        }
        cams.append(cam)
        storage.save_cameras(cams)
        manager.start_camera(cam)
        if input_mode == "push":
            flash(f"Đã thêm camera “{cam['name']}” (chế độ Edge AI). Hãy cấu hình thiết bị AI gửi dữ liệu về theo hướng dẫn bên dưới.", "success")
        else:
            flash(f"Đã thêm camera “{cam['name']}”. Đang kết nối — bạn có thể chỉnh chiều ảnh ngay tại đây nếu camera bị lật.", "success")
        return redirect(url_for("camera_view", camera_id=cam["id"]))

    cams = _my_cameras()
    statuses = manager.status_map()
    for c in cams:
        st = statuses.get(c["id"], {})
        c["_status"] = st.get("status", "offline")
        c["_error"] = st.get("error")
    return render_template("cameras.html", cameras=cams)


@app.route("/cameras/<camera_id>/edit", methods=["POST"])
@auth.login_required
def edit_camera(camera_id):
    if not _owned_camera_or_none(camera_id):
        flash("Không tìm thấy camera.", "error")
        return redirect(url_for("cameras_page"))

    cams = storage.load_cameras()
    updated = None
    for c in cams:
        if c["id"] == camera_id and c.get("owner_id") == session["user_id"]:
            c["name"] = request.form.get("name", c["name"]).strip() or c["name"]

            source_type = request.form.get("source_type", c.get("source_type", "webcam"))
            if source_type not in ("webcam", "rtsp"):
                source_type = c.get("source_type", "webcam")
            c["source_type"] = source_type

            try:
                c["webcam_index"] = int(request.form.get("webcam_index", c.get("webcam_index", 0)))
            except ValueError:
                pass
            c["rtsp_url"] = request.form.get("rtsp_url", c.get("rtsp_url", "")).strip()

            try:
                c["sensitivity"] = float(request.form.get("sensitivity", c.get("sensitivity", 0.03)))
            except ValueError:
                pass

            orientation = request.form.get("orientation", c.get("orientation", "none"))
            if orientation not in ("none", "flip_h", "flip_v", "rotate_180"):
                orientation = c.get("orientation", "none")
            c["orientation"] = orientation

            input_mode = request.form.get("input_mode", c.get("input_mode", "pull"))
            if input_mode not in ("pull", "push"):
                input_mode = c.get("input_mode", "pull")
            c["input_mode"] = input_mode

            updated = c
    storage.save_cameras(cams)
    if updated:
        manager.start_camera(updated)
        flash(f"Đã cập nhật camera “{updated['name']}”.", "success")
    return redirect(url_for("cameras_page"))


@app.route("/cameras/<camera_id>/delete", methods=["POST"])
@auth.login_required
def delete_camera(camera_id):
    """Xoa 'thuong': chuyen camera vao thung rac (deleted_at) va dung luong/
    trang thai dang chay - camera co the duoc khoi phuc trong 15 ngay."""
    if not _owned_camera_or_none(camera_id):
        flash("Không tìm thấy camera.", "error")
        return redirect(url_for("cameras_page"))
    manager.stop_camera(camera_id)
    cams = storage.load_cameras()
    name = camera_id
    for c in cams:
        if c["id"] == camera_id:
            trash.mark_deleted(c)
            name = c.get("name", camera_id)
    storage.save_cameras(cams)
    flash(f"Đã chuyển camera “{name}” vào thùng rác — có thể khôi phục trong {trash.RETENTION_DAYS} ngày.", "success")
    return redirect(url_for("cameras_page"))


@app.route("/cameras/<camera_id>/delete-permanent", methods=["POST"])
@auth.login_required
def delete_camera_permanent(camera_id):
    """Xoa VINH VIEN ngay lap tuc - dung khi nguoi dung chu dong chon 'Xoa
    vinh vien' (bo qua thung rac), hoac xoa han 1 camera dang trong thung rac."""
    if not _owned_camera_any(camera_id):
        flash("Không tìm thấy camera.", "error")
        return redirect(url_for("cameras_page"))
    manager.stop_camera(camera_id)
    cams = [c for c in storage.load_cameras() if c["id"] != camera_id]
    storage.save_cameras(cams)
    flash("Đã xoá vĩnh viễn camera.", "success")
    return redirect(request.referrer or url_for("cameras_page"))


@app.route("/cameras/<camera_id>/restore", methods=["POST"])
@auth.login_required
def restore_camera(camera_id):
    if not _owned_camera_any(camera_id):
        flash("Không tìm thấy camera.", "error")
        return redirect(url_for("trash_page"))
    cams = storage.load_cameras()
    restored = None
    for c in cams:
        if c["id"] == camera_id:
            trash.unmark_deleted(c)
            restored = c
    storage.save_cameras(cams)
    if restored:
        manager.start_camera(restored)
        flash(f"Đã khôi phục camera “{restored.get('name', camera_id)}”.", "success")
    return redirect(url_for("trash_page"))


@app.route("/cameras/bulk-delete", methods=["POST"])
@auth.login_required
def cameras_bulk_delete():
    """Xoa thuong hang loat -> chuyen vao thung rac."""
    ids = set(request.form.getlist("ids"))
    uid = session["user_id"]
    cams = storage.load_cameras()
    to_delete = [c for c in cams if c["id"] in ids and c.get("owner_id") == uid and not trash.is_deleted(c)]
    for c in to_delete:
        manager.stop_camera(c["id"])
        trash.mark_deleted(c)
    storage.save_cameras(cams)
    flash(f"Đã chuyển {len(to_delete)} camera vào thùng rác." if to_delete else "Chưa chọn camera nào để xoá.",
          "success" if to_delete else "error")
    return redirect(url_for("cameras_page"))


@app.route("/cameras/bulk-delete-permanent", methods=["POST"])
@auth.login_required
def cameras_bulk_delete_permanent():
    """Xoa vinh vien hang loat - dung tu trang Camera (chon roi xoa han
    ngay) hoac tu trang Thung rac (don han cac muc da chon)."""
    ids = set(request.form.getlist("ids"))
    uid = session["user_id"]
    cams = storage.load_cameras()
    to_delete = [c for c in cams if c["id"] in ids and c.get("owner_id") == uid]
    for c in to_delete:
        manager.stop_camera(c["id"])
    delete_ids = {c["id"] for c in to_delete}
    cams = [c for c in cams if c["id"] not in delete_ids]
    storage.save_cameras(cams)
    flash(f"Đã xoá vĩnh viễn {len(to_delete)} camera." if to_delete else "Chưa chọn camera nào để xoá.",
          "success" if to_delete else "error")
    return redirect(request.referrer or url_for("cameras_page"))


@app.route("/cameras/bulk-restore", methods=["POST"])
@auth.login_required
def cameras_bulk_restore():
    ids = set(request.form.getlist("ids"))
    uid = session["user_id"]
    cams = storage.load_cameras()
    restored = [c for c in cams if c["id"] in ids and c.get("owner_id") == uid and trash.is_deleted(c)]
    for c in restored:
        trash.unmark_deleted(c)
    storage.save_cameras(cams)
    for c in restored:
        manager.start_camera(c)
    flash(f"Đã khôi phục {len(restored)} camera." if restored else "Chưa chọn camera nào để khôi phục.",
          "success" if restored else "error")
    return redirect(url_for("trash_page"))


# ---------------- Xem truc tiep (live view) ----------------

@app.route("/camera/<camera_id>")
@auth.login_required
def camera_view(camera_id):
    cam = _owned_camera_or_none(camera_id)
    if not cam:
        flash("Không tìm thấy camera.", "error")
        return redirect(url_for("cameras_page"))
    worker = manager.get_worker(camera_id)
    status = worker.get_status() if worker else {"status": "offline", "error": "Chưa khởi động", "name": cam["name"]}
    return render_template("camera_view.html", camera=cam, status=status,
                            api_base_url=request.host_url.rstrip("/"))


@app.route("/camera/<camera_id>/orientation", methods=["POST"])
@auth.login_required
def camera_set_orientation(camera_id):
    if not _owned_camera_or_none(camera_id):
        flash("Không tìm thấy camera.", "error")
        return redirect(url_for("cameras_page"))

    orientation = request.form.get("orientation", "none")
    if orientation not in ("none", "flip_h", "flip_v", "rotate_180"):
        orientation = "none"

    cams = storage.load_cameras()
    updated = None
    for c in cams:
        if c["id"] == camera_id:
            c["orientation"] = orientation
            updated = c
    storage.save_cameras(cams)

    # Ap dung NGAY cho luong dang chay, khong can khoi dong lai ket noi camera:
    # CameraWorker doc self.camera.get("orientation") moi khung hinh, nen chi
    # can sua truc tiep dict cua worker dang chay la co hieu luc tuc thi.
    worker = manager.get_worker(camera_id)
    if worker is not None:
        worker.camera["orientation"] = orientation

    if updated:
        flash("Đã cập nhật chiều ảnh.", "success")
    else:
        flash("Không tìm thấy camera.", "error")
    return redirect(url_for("camera_view", camera_id=camera_id))


def _mjpeg_generator(camera_id):
    boundary = b"--frame"
    while True:
        worker = manager.get_worker(camera_id)
        jpeg = worker.get_latest_jpeg() if worker else None
        if jpeg:
            yield (boundary + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                   str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
        time.sleep(0.08)


@app.route("/camera/<camera_id>/stream")
@auth.login_required
def camera_stream(camera_id):
    if not _owned_camera_or_none(camera_id):
        abort(404)
    return Response(_mjpeg_generator(camera_id),
                     mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------- Su kien / canh bao (incidents) ----------------

@app.route("/incidents")
@auth.login_required
def incidents_page():
    incidents = _my_incidents()
    camera_filter = request.args.get("camera_id") or ""
    if camera_filter:
        incidents = [i for i in incidents if i["camera_id"] == camera_filter]
    cameras = _my_cameras()
    return render_template("incidents.html", incidents=incidents, cameras=cameras,
                            selected_camera=camera_filter)


@app.route("/incidents/<incident_id>")
@auth.login_required
def incident_detail(incident_id):
    incident = _owned_incident_or_none(incident_id)
    if not incident:
        flash("Không tìm thấy sự kiện.", "error")
        return redirect(url_for("incidents_page"))
    return render_template("incident_detail.html", incident=incident)


@app.route("/incidents/<incident_id>/note", methods=["POST"])
@auth.login_required
def incident_note(incident_id):
    if not _owned_incident_or_none(incident_id):
        flash("Không tìm thấy sự kiện.", "error")
        return redirect(url_for("incidents_page"))
    incidents = storage.load_incidents()
    for i in incidents:
        if i["id"] == incident_id:
            i["note"] = request.form.get("note", "").strip()
            i["reviewed"] = True
    storage.save_incidents(incidents)
    flash("Đã lưu ghi chú.", "success")
    return redirect(url_for("incident_detail", incident_id=incident_id))


@app.route("/incidents/<incident_id>/delete", methods=["POST"])
@auth.login_required
def incident_delete(incident_id):
    """Xoa 'thuong': chuyen su kien vao thung rac - GIU NGUYEN file video/
    anh tren dia, chi an khoi danh sach - co the khoi phuc trong 15 ngay."""
    if not _owned_incident_or_none(incident_id):
        flash("Không tìm thấy sự kiện.", "error")
        return redirect(url_for("incidents_page"))
    incidents = storage.load_incidents()
    for i in incidents:
        if i["id"] == incident_id:
            trash.mark_deleted(i)
    storage.save_incidents(incidents)
    flash(f"Đã chuyển sự kiện vào thùng rác — có thể khôi phục trong {trash.RETENTION_DAYS} ngày.", "success")
    return redirect(url_for("incidents_page"))


@app.route("/incidents/<incident_id>/delete-permanent", methods=["POST"])
@auth.login_required
def incident_delete_permanent(incident_id):
    """Xoa VINH VIEN ngay: xoa het file video/anh tren dia roi xoa ban ghi
    khoi incidents.json. Dung khi chon 'Xoa vinh vien' truc tiep, hoac don
    han 1 su kien dang trong thung rac."""
    if not _owned_incident_any(incident_id):
        flash("Không tìm thấy sự kiện.", "error")
        return redirect(url_for("incidents_page"))
    incidents = storage.load_incidents()
    target = next((i for i in incidents if i["id"] == incident_id), None)
    if target:
        for fname, folder in (
            (target.get("video_file"), storage.VIDEOS_DIR),
            (target.get("image_file"), storage.IMAGES_DIR),
        ):
            if fname:
                path = os.path.join(folder, fname)
                if os.path.exists(path):
                    os.remove(path)
        incidents = [i for i in incidents if i["id"] != incident_id]
        storage.save_incidents(incidents)
        flash("Đã xoá vĩnh viễn sự kiện.", "success")
    return redirect(request.referrer or url_for("incidents_page"))


@app.route("/incidents/<incident_id>/restore", methods=["POST"])
@auth.login_required
def restore_incident(incident_id):
    if not _owned_incident_any(incident_id):
        flash("Không tìm thấy sự kiện.", "error")
        return redirect(url_for("trash_page"))
    incidents = storage.load_incidents()
    for i in incidents:
        if i["id"] == incident_id:
            trash.unmark_deleted(i)
    storage.save_incidents(incidents)
    flash("Đã khôi phục sự kiện.", "success")
    return redirect(url_for("trash_page"))


def _media_owner_check(filename, file_field):
    """Chi cho phep xem file video/anh neu file do thuoc 1 su kien cua CHINH
    nguoi dang dang nhap - tranh viec 1 tai khoan xem duoc bang chung cua
    tai khoan khac chi bang cach doan/biet ten file."""
    uid = session.get("user_id")
    for i in storage.load_incidents():
        if i.get(file_field) == filename:
            return i.get("owner_id") == uid
    return False


@app.route("/incidents/bulk-delete", methods=["POST"])
@auth.login_required
def incidents_bulk_delete():
    """Xoa thuong hang loat -> chuyen vao thung rac (giu nguyen file)."""
    ids = set(request.form.getlist("ids"))
    uid = session["user_id"]
    incidents = storage.load_incidents()
    to_delete = [i for i in incidents if i["id"] in ids and i.get("owner_id") == uid and not trash.is_deleted(i)]
    for i in to_delete:
        trash.mark_deleted(i)
    storage.save_incidents(incidents)
    flash(f"Đã chuyển {len(to_delete)} sự kiện vào thùng rác." if to_delete else "Chưa chọn sự kiện nào để xoá.",
          "success" if to_delete else "error")
    return redirect(url_for("incidents_page"))


@app.route("/incidents/bulk-delete-permanent", methods=["POST"])
@auth.login_required
def incidents_bulk_delete_permanent():
    """Xoa vinh vien hang loat - tu trang Su kien (xoa han ngay) hoac tu
    trang Thung rac (don han cac muc da chon)."""
    ids = set(request.form.getlist("ids"))
    uid = session["user_id"]
    incidents = storage.load_incidents()
    to_delete = [i for i in incidents if i["id"] in ids and i.get("owner_id") == uid]
    for target in to_delete:
        for fname, folder in (
            (target.get("video_file"), storage.VIDEOS_DIR),
            (target.get("image_file"), storage.IMAGES_DIR),
        ):
            if fname:
                path = os.path.join(folder, fname)
                if os.path.exists(path):
                    os.remove(path)
    delete_ids = {i["id"] for i in to_delete}
    incidents = [i for i in incidents if i["id"] not in delete_ids]
    storage.save_incidents(incidents)
    flash(f"Đã xoá vĩnh viễn {len(to_delete)} sự kiện." if to_delete else "Chưa chọn sự kiện nào để xoá.",
          "success" if to_delete else "error")
    return redirect(request.referrer or url_for("incidents_page"))


@app.route("/incidents/bulk-restore", methods=["POST"])
@auth.login_required
def incidents_bulk_restore():
    ids = set(request.form.getlist("ids"))
    uid = session["user_id"]
    incidents = storage.load_incidents()
    restored = [i for i in incidents if i["id"] in ids and i.get("owner_id") == uid and trash.is_deleted(i)]
    for i in restored:
        trash.unmark_deleted(i)
    storage.save_incidents(incidents)
    flash(f"Đã khôi phục {len(restored)} sự kiện." if restored else "Chưa chọn sự kiện nào để khôi phục.",
          "success" if restored else "error")
    return redirect(url_for("trash_page"))


@app.route("/media/videos/<path:filename>")
@auth.login_required
def media_video(filename):
    if not _media_owner_check(filename, "video_file"):
        abort(404)
    return send_from_directory(storage.VIDEOS_DIR, filename)


@app.route("/media/images/<path:filename>")
@auth.login_required
def media_image(filename):
    if not _media_owner_check(filename, "image_file"):
        abort(404)
    return send_from_directory(storage.IMAGES_DIR, filename)


# ---------------- API cho thiet bi Edge AI (camera tu phat hien) ----------------
# Kien truc "tich hop AI vao camera": mot thiet bi AI o canh camera (Jetson,
# May tinh nho gan camera, hoac chinh camera thong minh) tu quay video va tu
# chay model phat hien bao luc, RIENG BIET voi web app nay. Web app chi con
# dong vai tro NHAN ket qua va HIEN THI - khong con phai tu ket noi RTSP/
# webcam va tu chay bo phat hien cho nhung camera loai nay (xem input_mode
# "push" trong cameras.json, va PushCameraState/RemoteApiSink trong
# camera_manager.py). Nho vay: (1) camera van hoat dong doc lap ke ca khi tat
# web app nay, (2) nhieu web app / nhieu noi co the dung chung 1 "bo nao" AI
# bang cach tro no ve nhieu URL API khac nhau. Xem detector_service.py de
# biet cach mot thiet bi AI ket noi vao day.
#
# Xac thuc bang 1 khoa dung chung (header "X-API-Key", xem storage.get_or_create_api_key()
# va trang /settings). Quyen so huu du lieu van tach theo tung nguoi dung
# thong qua owner_id cua CAMERA duoc chi dinh trong yeu cau.

def _check_api_key():
    key = request.headers.get("X-API-Key", "")
    expected = storage.get_or_create_api_key()
    return bool(key) and hmac.compare_digest(key, expected)


@app.route("/api/cameras/<camera_id>/frame", methods=["POST"])
def api_camera_frame(camera_id):
    """Nhan 1 khung hinh live-view moi tu thiet bi AI (tuy chon - camera co
    the chi gui su kien khi co canh bao ma khong stream lien tuc, live view
    khi do se hien trang thai 'live' nhung khong co hinh)."""
    if not _check_api_key():
        abort(401)
    cam = next((c for c in storage.load_cameras() if c["id"] == camera_id), None)
    if not cam or cam.get("input_mode") != "push":
        abort(404)
    jpeg_bytes = request.files["frame"].read() if "frame" in request.files else request.data
    if not jpeg_bytes:
        abort(400)
    manager.feed_push_frame(camera_id, jpeg_bytes)
    return jsonify({"ok": True})


@app.route("/api/incidents", methods=["POST"])
def api_create_incident():
    """Thiet bi AI bao ve 1 su kien moi phat hien duoc. Co the goi ngay khi
    bat dau quay (video se gui sau qua /api/incidents/<id>/finish) hoac gui
    luon video neu da quay xong."""
    if not _check_api_key():
        abort(401)
    camera_id = request.form.get("camera_id", "")
    cam = next((c for c in storage.load_cameras() if c["id"] == camera_id), None)
    if not cam:
        return jsonify({"error": "camera_id không hợp lệ"}), 404
    if cam.get("input_mode") != "push":
        return jsonify({"error": "Camera này không ở chế độ Edge AI (push)"}), 400

    incident_id = request.form.get("id") or storage.new_id()
    timestamp = request.form.get("timestamp") or datetime.datetime.now().isoformat(timespec="seconds")
    try:
        confidence = round(float(request.form.get("confidence", 0.0)), 3)
    except ValueError:
        confidence = 0.0

    video_file = None
    image_file = None
    if "video" in request.files and request.files["video"].filename:
        video_file = f"{incident_id}.mp4"
        request.files["video"].save(os.path.join(storage.VIDEOS_DIR, video_file))
    if "image" in request.files and request.files["image"].filename:
        image_file = f"{incident_id}.jpg"
        request.files["image"].save(os.path.join(storage.IMAGES_DIR, image_file))

    incident = {
        "id": incident_id,
        "owner_id": cam.get("owner_id"),
        "camera_id": camera_id,
        "camera_name": cam.get("name", camera_id),
        "timestamp": timestamp,
        "label": request.form.get("label", "edge_ai_detection"),
        "confidence": confidence,
        "description": request.form.get("description", "Cảnh báo từ thiết bị AI ở biên (Edge AI)."),
        "video_file": video_file,
        "image_file": image_file,
        "reviewed": False,
        "note": "",
        "status": "done" if video_file else "recording",
    }
    storage.add_incident(incident)
    manager.touch_push_camera(camera_id)
    return jsonify({"id": incident_id, "status": incident["status"]})


@app.route("/api/incidents/<incident_id>/finish", methods=["POST"])
def api_finish_incident(incident_id):
    """Thiet bi AI gui video quay duoc sau khi da tao su kien truoc do bang
    /api/incidents (truong hop video con dang quay o thoi diem bao canh bao)."""
    if not _check_api_key():
        abort(401)
    incidents = storage.load_incidents()
    target = next((i for i in incidents if i["id"] == incident_id), None)
    if not target:
        return jsonify({"error": "Không tìm thấy sự kiện"}), 404

    if "video" in request.files and request.files["video"].filename:
        video_file = target.get("video_file") or f"{incident_id}.mp4"
        video_path = os.path.join(storage.VIDEOS_DIR, video_file)
        request.files["video"].save(video_path)
        camera_manager._transcode_to_h264(video_path)
        storage.update_incident(incident_id, {"status": "done", "video_file": video_file})
    else:
        storage.update_incident(incident_id, {"status": "done"})
    return jsonify({"id": incident_id, "status": "done"})


# ---------------- Thung rac ----------------

@app.route("/trash")
@auth.login_required
def trash_page():
    cams = _my_trashed_cameras()
    incidents = _my_trashed_incidents()
    for c in cams:
        c["_days_left"] = trash.days_left(c.get("deleted_at"))
    for i in incidents:
        i["_days_left"] = trash.days_left(i.get("deleted_at"))
    return render_template("trash.html", cameras=cams, incidents=incidents,
                            retention_days=trash.RETENTION_DAYS)


# ---------------- Cai dat tai khoan ----------------

@app.route("/settings", methods=["GET", "POST"])
@auth.login_required
def settings_page():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        users = storage.load_users()
        user = next((u for u in users if u["id"] == session["user_id"]), None)
        if not user or not auth.verify_password(current, user["password"]):
            flash("Mật khẩu hiện tại không đúng.", "error")
        elif len(new_pw) < 6:
            flash("Mật khẩu mới cần ít nhất 6 ký tự.", "error")
        elif new_pw != confirm:
            flash("Mật khẩu xác nhận không khớp.", "error")
        else:
            user["password"] = auth.hash_password(new_pw)
            storage.save_users(users)
            flash("Đã đổi mật khẩu.", "success")
    return render_template("settings.html", api_key=storage.get_or_create_api_key(),
                            api_base_url=request.host_url.rstrip("/"))


@app.route("/settings/regenerate-api-key", methods=["POST"])
@auth.login_required
def regenerate_api_key():
    """Tao lai khoa API dung chung cho cac thiet bi AI - khoa cu se ngung
    hoat dong ngay. Dung khi nghi ngo khoa bi lo hoac can thu hoi truy cap."""
    storage.regenerate_api_key()
    flash("Đã tạo khoá API mới. Các thiết bị đang dùng khoá cũ sẽ cần cập nhật lại.", "success")
    return redirect(url_for("settings_page"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
