"""
create_admin.py

一次性 bootstrap 腳本：建立/重設「初始管理員帳號」。

刻意不把任何預設密碼寫進程式碼或 GitHub。密碼一律用下面兩種方式
之一取得，兩者都不會被記錄在 shell history 以外的地方，也不會進
git：

【方式一：環境變數】（適合 CI / 部署腳本一次性執行）
    ADMIN_EMAIL=admin@example.com \
    ADMIN_NAME="系統管理員" \
    ADMIN_PASSWORD="一組夠長且不會被猜到的密碼" \
    python3 create_admin.py

【方式二：互動輸入】（適合手動在本機/伺服器上執行，不建議把密碼
    留在任何一行指令歷史紀錄裡）
    python3 create_admin.py
    # 沒給 ADMIN_PASSWORD 環境變數時，會用 getpass 互動輸入，
    # 畫面上不會顯示明碼

行為：
- email 已存在 → 預設「不覆蓋」，除非加上 --reset-password 才會
  更新密碼（並且一樣是 hash 過的）。
- 密碼一律用 werkzeug 的 generate_password_hash 存成雜湊，資料庫裡
  永遠看不到明碼。
- 跟 seed_prompt_templates.py 一樣，自己組一個最小的 Flask app 只
  為了拿到 db context，不 import 整支 app.py。

用法：
    python3 create_admin.py                      # 新增（互動輸入密碼）
    python3 create_admin.py --reset-password      # email 已存在時允許改密碼
    python3 create_admin.py --enable-2fa          # 順便打開這個 Admin 的 Email 2FA
"""

import argparse
import getpass
import os
import re
import sys
from urllib.parse import urlsplit, parse_qsl, urlunsplit, urlencode

from dotenv import load_dotenv
from flask import Flask
from werkzeug.security import generate_password_hash

load_dotenv()

from extensions import db
from models import Admin

EMAIL_REGEX = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
PASSWORD_MIN_LENGTH = 12  # Admin 密碼要求比一般 User 更高一點

basedir = os.path.abspath(os.path.dirname(__file__))


def _normalize_db_url(raw_url: str) -> str:
    if not raw_url:
        return raw_url
    parsed_url = urlsplit(raw_url)
    query_params = []
    for key, value in parse_qsl(parsed_url.query, keep_blank_values=True):
        normalized_key = key.lower().replace("_", "-")
        if normalized_key == "ssl-mode":
            continue
        if key == "ssl_ca" and value == "ca.pem":
            value = os.path.join(basedir, "ca.pem")
        query_params.append((key, value))

    return urlunsplit((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        urlencode(query_params),
        parsed_url.fragment,
    ))


app = Flask(__name__)
_raw_db_url = os.environ.get("DATABASE_URL") or os.environ.get("SQLALCHEMY_DATABASE_URI")
app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(_raw_db_url)
db.init_app(app)


def _is_valid_password(password: str) -> bool:
    if len(password) < PASSWORD_MIN_LENGTH:
        return False
    if not re.search(r'[A-Za-z]', password):
        return False
    if not re.search(r'\d', password):
        return False
    return True


def _read_password() -> str:
    env_password = os.environ.get("ADMIN_PASSWORD")
    if env_password:
        return env_password
    while True:
        password = getpass.getpass("請輸入 Admin 密碼（畫面不會顯示）：")
        confirm = getpass.getpass("請再輸入一次以確認：")
        if password != confirm:
            print("兩次輸入不一致，請重新輸入。")
            continue
        return password


def create_admin(reset_password: bool, enable_2fa: bool):
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_name = os.environ.get("ADMIN_NAME", "").strip()

    if not email:
        email = input("請輸入 Admin email：").strip().lower()
    if not admin_name:
        admin_name = input("請輸入 Admin 顯示名稱：").strip()

    if not EMAIL_REGEX.match(email):
        print(f"錯誤：email 格式不正確（{email}）")
        sys.exit(1)
    if not admin_name:
        print("錯誤：admin_name 不可為空")
        sys.exit(1)

    with app.app_context():
        existing = Admin.query.filter_by(email=email).first()

        if existing and not reset_password:
            print(f"email='{email}' 的 Admin 帳號已存在（admin_id={existing.admin_id}）。")
            print("若要重設密碼，請加上 --reset-password 參數重新執行。")
            sys.exit(1)

        password = _read_password()
        if not _is_valid_password(password):
            print(f"錯誤：密碼至少需要 {PASSWORD_MIN_LENGTH} 個字元，並包含英文字母和數字")
            sys.exit(1)

        password_hash = generate_password_hash(password)

        if existing:
            existing.password_hash = password_hash
            existing.admin_name = admin_name or existing.admin_name
            if enable_2fa:
                existing.email_2fa_enabled = True
            db.session.commit()
            print(f"已更新 Admin 帳號：email={email}, admin_id={existing.admin_id}")
        else:
            new_admin = Admin(
                admin_name=admin_name,
                email=email,
                password_hash=password_hash,
                email_2fa_enabled=enable_2fa,
            )
            db.session.add(new_admin)
            db.session.commit()
            print(f"已建立 Admin 帳號：email={email}, admin_id={new_admin.admin_id}")

        if enable_2fa:
            print("已開啟此 Admin 帳號的 Email 2FA（下次登入會需要驗證信裡的驗證碼）。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="建立或重設初始 Admin 帳號")
    parser.add_argument(
        "--reset-password", action="store_true",
        help="如果 email 已存在，允許重設密碼（預設不覆蓋既有帳號）",
    )
    parser.add_argument(
        "--enable-2fa", action="store_true",
        help="同時開啟這個 Admin 帳號的 Email 2FA",
    )
    args = parser.parse_args()
    create_admin(reset_password=args.reset_password, enable_2fa=args.enable_2fa)