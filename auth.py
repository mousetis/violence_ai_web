"""
Dang nhap don gian, file-based (khong dung database).
Mat khau duoc bam bang PBKDF2-HMAC-SHA256 + salt rieng cho tung user.
"""
import hashlib
import hmac
import os
import functools

from flask import session, redirect, url_for, request

import storage

PBKDF2_ITERATIONS = 100_000


def hash_password(password, salt_hex=None):
    if salt_hex is None:
        salt_hex = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    )
    return f"{salt_hex}${digest.hex()}"


def verify_password(password, stored):
    try:
        salt_hex, hex_digest = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), hex_digest)


def ensure_default_admin():
    """Neu chua co user nao, tao san tai khoan admin/admin123 (doi ngay sau khi dang nhap lan dau)."""
    users = storage.load_users()
    if not users:
        users = [{
            "id": storage.new_id(),
            "username": "admin",
            "password": hash_password("admin123"),
        }]
        storage.save_users(users)


def find_user(username):
    for u in storage.load_users():
        if u["username"] == username:
            return u
    return None


def create_user(username, password):
    """Tao 1 tai khoan moi (tu dang ky). Goi ham nay CHI SAU KHI da kiem tra
    o app.py rang username chua ton tai va mat khau hop le."""
    users = storage.load_users()
    user = {
        "id": storage.new_id(),
        "username": username,
        "password": hash_password(password),
    }
    users.append(user)
    storage.save_users(users)
    return user


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped
