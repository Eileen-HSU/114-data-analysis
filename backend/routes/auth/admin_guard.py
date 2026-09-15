"""Admin JWT 建立與驗證的共用工具。

刻意獨立成一個小檔案，讓 login.py / two_factor.py / routes/admin/*
都能 import 同一份邏輯，不用各自重複判斷 "account_type == admin"。

安全性重點：
- Admin token 與 User token 的 payload 結構不同（Admin 沒有
  user_id，User 沒有 admin_id），任何一個 API 要當「Admin 專用」
  都必須同時檢查 account_type == "admin" 與 role == "admin"，
  不可以只檢查其中一個欄位。
- 這裡完全不查詢 User table、不看 User.role，Admin 權限與
  User.role 徹底脫鉤（對應需求 #7）。
"""

from datetime import timedelta
import os

import jwt

from extensions import taiwan_now

_JWT_SECRET: str | None = None


def get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.getenv("JWT_SECRET_KEY")
        if not _JWT_SECRET:
            raise RuntimeError("JWT_SECRET_KEY 環境變數未設定")
    return _JWT_SECRET


def build_admin_token(admin_id: int, now=None) -> str:
    """建立正式 Admin JWT。刻意不帶 user_id，避免任何程式碼誤把
    Admin token 拿去當 User token 用（少了 user_id 就會直接失敗，
    而不是靜默地對到錯的帳號）。
    """
    if now is None:
        now = taiwan_now()
    exp_time = (now + timedelta(hours=24)).replace(tzinfo=None)
    return jwt.encode(
        {
            "account_type": "admin",
            "admin_id": admin_id,
            "role": "admin",
            "exp": exp_time,
        },
        get_jwt_secret(),
        algorithm="HS256",
    )


def build_admin_pre_auth_token(email: str, now=None) -> str:
    """Admin 2FA 第一步（密碼驗證通過）之後發的短效 pre-auth token。"""
    if now is None:
        now = taiwan_now()
    exp_time = (now + timedelta(minutes=10)).replace(tzinfo=None)
    return jwt.encode(
        {
            "email": email,
            "type": "pre_auth",
            "account_type": "admin",
            "exp": exp_time,
        },
        get_jwt_secret(),
        algorithm="HS256",
    )


def verify_admin_token(req):
    """驗證正式 Admin JWT。回傳 (admin_id, error)。

    error 為 None 時 admin_id 一定是整數；否則 admin_id 一定是 None。
    呼叫端可用 error 內容判斷要回 401（未登入/token 問題）還是
    403（token 有效但不是 admin）。
    """
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Unauthorized"
    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"

    if payload.get("account_type") != "admin" or payload.get("role") != "admin":
        return None, "Admin access required"

    admin_id = payload.get("admin_id")
    if not admin_id:
        return None, "Admin access required"

    return admin_id, None
