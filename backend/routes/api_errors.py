"""統一的 API 錯誤格式：machine-readable `code` + user-readable `message`。

為了不破壞既有前端（一律讀 body.error），同一段訊息也放在 `error`。
"""

from flask import jsonify


def api_error(code: str, message: str, status: int = 400, **extra):
    body = {"code": code, "message": message, "error": message}
    body.update(extra)
    return jsonify(body), status
