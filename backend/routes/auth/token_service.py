"""使用者登入 token：效期（環境變數）與「版本號」失效機制。

- 效期：AUTH_TOKEN_TTL_HOURS（預設 10 小時），不做 refresh。
- User.token_version：改密碼／登出時 +1，帶舊版本號的 token 立即失效（回 401）。
- 沒有 tv 欄位的舊 token 視為版本 0；第一次改密碼／登出後就會失效。
"""

import os
from datetime import datetime, timedelta

import jwt
from sqlalchemy import update

from extensions import db
from models import User


def token_ttl():
    try:
        hours = float(os.getenv("AUTH_TOKEN_TTL_HOURS", "10"))
        if hours <= 0:
            raise ValueError
    except ValueError:
        hours = 10.0
    return timedelta(hours=hours)


def current_version(user_id):
    value = db.session.query(User.token_version).filter(User.user_id == user_id).scalar()
    return value


def issue_user_token(user_id, secret, now):
    """簽發 User token（含目前的 token 版本號）。

    exp 一律用 UTC：PyJWT 把沒有時區的 datetime 當成 UTC，舊程式傳入台灣時間
    （UTC+8）會讓 token 實際多活 8 小時。now 參數保留只為相容舊呼叫端。"""
    version = current_version(user_id) or 0
    return jwt.encode(
        {
            "account_type": "user",
            "user_id": user_id,
            "tv": int(version),
            "exp": datetime.utcnow() + token_ttl(),
        },
        secret,
        algorithm="HS256",
    )


def token_is_current(payload):
    """token 的版本號是否仍是目前版本。查不到使用者時維持原行為（不在這裡擋）。"""
    user_id = payload.get("user_id")
    if user_id is None:
        return True
    version = current_version(user_id)
    if version is None:
        return True
    return int(payload.get("tv", 0) or 0) == int(version or 0)


def bump_token_version(user_id):
    """讓這位使用者所有既有 token 立即失效（呼叫端負責 commit）。"""
    db.session.execute(
        update(User).where(User.user_id == user_id).values(token_version=User.token_version + 1)
    )
