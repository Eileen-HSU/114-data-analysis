"""
cli.py

集中管理一次性維運／管理指令（2026-09 合併於此）：
    flask init-workspace
    flask diagnose
    flask fix-access-codes
    flask create-admin
    flask bootstrap-taxonomy

2026-09 資料庫整理時移除了 seed-prompts / update-prompts /
run-classification：這三個指令只服務已淘汰的 Prompt_Template 提示詞表，
正式分類改由已發布的分類架構（Taxonomy）即時組出提示詞。

【使用方式】
    cd backend
    FLASK_APP=cli.py flask <子指令> [選項]

例如：
    FLASK_APP=cli.py flask init-workspace
    FLASK_APP=cli.py flask diagnose
    FLASK_APP=cli.py flask fix-access-codes
    FLASK_APP=cli.py flask create-admin --enable-2fa
    FLASK_APP=cli.py flask bootstrap-taxonomy

用 `FLASK_APP=cli.py flask --help` 可以列出全部子指令。
"""

import os
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import click
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import app
from extensions import db


# ═══════════════════════════════════════════════════════════════
# flask init-workspace（原 init_workspace.py）
# ═══════════════════════════════════════════════════════════════
@app.cli.command("init-workspace")
def init_workspace():
    """初始化腳本：Workspace 表為空時插入一筆測試資料。"""
    click.echo("[INIT] ========== 初始化 Workspace 表 ==========")
    try:
        count = db.session.execute(text("SELECT COUNT(*) FROM Workspace")).fetchone()[0]
        click.echo(f"[INIT] Workspace 表目前有 {count} 筆記錄")

        if count == 0:
            db.session.execute(text("""
                INSERT INTO Workspace (user_id, project_name, status, created_at)
                VALUES (1, '測試專案', 'active', NOW())
            """))
            db.session.commit()
            click.echo("[✓] 已插入測試 Workspace 記錄 (user_id=1, project_name='測試專案')")
        else:
            click.echo("[INFO] Workspace 表已有資料，跳過初始化")

        rows = db.session.execute(text("SELECT project_id, project_name FROM Workspace")).fetchall()
        click.echo("[INIT] Workspace 表內容:")
        for row in rows:
            click.echo(f"  - project_id: {row[0]}, project_name: {row[1]}")
    except Exception as e:
        click.echo(f"[ERROR] 初始化失敗: {e}", err=True)
        raise
    click.echo("\n[INIT] ========== 初始化完成 ==========")


# ═══════════════════════════════════════════════════════════════
# flask diagnose（原 diagnose.py）
# ═══════════════════════════════════════════════════════════════
@app.cli.command("diagnose")
def diagnose():
    """診斷腳本：驗證後端資料庫連接與 Survey_Template 表狀態。"""
    from models import Survey_Template

    click.echo("[INFO] ========== 資料庫診斷開始 ==========")
    try:
        click.echo(f"\n[1] SQLAlchemy 資料庫 URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

        db.session.execute(text("SELECT 1"))
        click.echo("[✓] 資料庫連接成功！")

        surveys = db.session.query(Survey_Template).all()
        click.echo(f"\n[2] Survey_Template 表現有 {len(surveys)} 筆記錄")
        if surveys:
            click.echo("最新 5 筆記錄：")
            for survey in surveys[-5:]:
                click.echo(f"  - ID={survey.template_id}, Access_Code='{survey.access_code}', Created={survey.share_uuid}")
        else:
            click.echo("  表為空")

        try:
            tables = db.session.execute(text("SHOW TABLES")).fetchall()
            click.echo("\n[0] 資料庫中的所有表:")
            for t in tables:
                click.echo(f"  - {t[0]}")
        except Exception as e:
            click.echo(f"\n[0] 無法列出表: {e}")

        try:
            rows = db.session.execute(text("SELECT project_id FROM Workspace LIMIT 5")).fetchall()
            click.echo(f"\n[2.5] Workspace 表檢查: 找到 {len(rows)} 筆記錄")
            for row in rows:
                click.echo(f"  - project_id: {row[0]}")
        except Exception as e:
            click.echo(f"\n[2.5] Workspace 表檢查失敗: {e}")

        try:
            cols = db.session.execute(text("DESCRIBE Workspace")).fetchall()
            click.echo("\n[2.6] Workspace 表結構:")
            for col in cols:
                click.echo(f"  - {col[0]}: {col[1]} {'NULL' if col[2] == 'YES' else 'NOT NULL'} {'AUTO_INCREMENT' if col[5] == 'auto_increment' else ''}")
        except Exception as e:
            click.echo(f"\n[2.6] Workspace 表結構檢查失敗: {e}")

        try:
            rows = db.session.execute(text("SELECT user_id, email FROM User LIMIT 5")).fetchall()
            click.echo(f"\n[2.7] User 表檢查: 找到 {len(rows)} 筆記錄")
            for row in rows:
                click.echo(f"  - user_id: {row[0]}, email: {row[1]}")
        except Exception as e:
            click.echo(f"\n[2.7] User 表檢查失敗: {e}")

        click.echo("\n[3] Survey_Template 模型：")
        click.echo(f"  - __tablename__: {Survey_Template.__tablename__}")
        click.echo(f"  - 欄位列表: {[c.name for c in Survey_Template.__table__.columns]}")

        click.echo("\n[INFO] ========== 診斷完成 ==========")
    except Exception as e:
        click.echo(f"\n[ERROR] 診斷失敗: {e}", err=True)
        raise


# ═══════════════════════════════════════════════════════════════
# flask fix-access-codes（原 fix_access_codes.py）
# ═══════════════════════════════════════════════════════════════
@app.cli.command("fix-access-codes")
def fix_access_codes():
    """修復所有問卷邀請碼的大小寫問題，統一轉為大寫。"""
    from models import Survey_Template

    click.echo("開始修復問卷邀請碼大小寫問題...")
    try:
        surveys = Survey_Template.query.all()
        fixed_count = 0
        for survey in surveys:
            original_code = survey.access_code
            new_code = original_code.upper() if original_code else original_code
            if original_code != new_code:
                survey.access_code = new_code
                fixed_count += 1
                click.echo(f"✓ 已修復: {original_code} → {new_code}")

        if fixed_count > 0:
            db.session.commit()
            click.echo(f"\n✅ 成功修復 {fixed_count} 個問卷的邀請碼")
        else:
            click.echo("✅ 所有邀請碼已經是大寫，無需修復")
    except Exception as e:
        db.session.rollback()
        click.echo(f"❌ 修復失敗: {e}", err=True)
        raise


# ═══════════════════════════════════════════════════════════════
# flask create-admin（原 create_admin.py）
# ═══════════════════════════════════════════════════════════════
#
# 刻意不把任何預設密碼寫進程式碼或 GitHub。密碼一律用「環境變數
# ADMIN_PASSWORD」或「互動輸入（getpass，畫面不顯示明碼）」取得，
# 不會被記錄在 shell history 以外的地方，也不會進 git。
_EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PASSWORD_MIN_LENGTH = 12  # Admin 密碼要求比一般 User 更高一點


def _is_valid_password(password: str) -> bool:
    if len(password) < _PASSWORD_MIN_LENGTH:
        return False
    if not re.search(r"[A-Za-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    return True


def _read_admin_password() -> str:
    import getpass

    env_password = os.environ.get("ADMIN_PASSWORD")
    if env_password:
        return env_password
    while True:
        password = getpass.getpass("請輸入 Admin 密碼（畫面不會顯示）：")
        confirm = getpass.getpass("請再輸入一次以確認：")
        if password != confirm:
            click.echo("兩次輸入不一致，請重新輸入。")
            continue
        return password


@app.cli.command("create-admin")
@click.option("--reset-password", is_flag=True, help="email 已存在時允許重設密碼（預設不覆蓋既有帳號）")
@click.option("--enable-2fa", is_flag=True, help="同時開啟這個 Admin 帳號的 Email 2FA")
def create_admin(reset_password, enable_2fa):
    """建立或重設初始 Admin 帳號。

    \b
    用法：
        flask create-admin
        flask create-admin --reset-password
        flask create-admin --enable-2fa
    """
    from models import Admin

    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_name = os.environ.get("ADMIN_NAME", "").strip()

    if not email:
        email = input("請輸入 Admin email：").strip().lower()
    if not admin_name:
        admin_name = input("請輸入 Admin 顯示名稱：").strip()

    if not _EMAIL_REGEX.match(email):
        click.echo(f"錯誤：email 格式不正確（{email}）", err=True)
        sys.exit(1)
    if not admin_name:
        click.echo("錯誤：admin_name 不可為空", err=True)
        sys.exit(1)

    existing = Admin.query.filter_by(email=email).first()

    if existing and not reset_password:
        click.echo(f"email='{email}' 的 Admin 帳號已存在（admin_id={existing.admin_id}）。")
        click.echo("若要重設密碼，請加上 --reset-password 參數重新執行。")
        sys.exit(1)

    password = _read_admin_password()
    if not _is_valid_password(password):
        click.echo(f"錯誤：密碼至少需要 {_PASSWORD_MIN_LENGTH} 個字元，並包含英文字母和數字", err=True)
        sys.exit(1)

    password_hash = generate_password_hash(password)

    if existing:
        existing.password_hash = password_hash
        existing.admin_name = admin_name or existing.admin_name
        if enable_2fa:
            existing.email_2fa_enabled = True
        db.session.commit()
        click.echo(f"已更新 Admin 帳號：email={email}, admin_id={existing.admin_id}")
    else:
        new_admin = Admin(
            admin_name=admin_name,
            email=email,
            password_hash=password_hash,
            email_2fa_enabled=enable_2fa,
        )
        db.session.add(new_admin)
        db.session.commit()
        click.echo(f"已建立 Admin 帳號：email={email}, admin_id={new_admin.admin_id}")

    if enable_2fa:
        click.echo("已開啟此 Admin 帳號的 Email 2FA（下次登入會需要驗證信裡的驗證碼）。")


# ═══════════════════════════════════════════════════════════════
# flask bootstrap-taxonomy（部署 / 手動執行 legacy taxonomy bootstrap）
# ═══════════════════════════════════════════════════════════════
@app.cli.command("bootstrap-taxonomy")
def bootstrap_taxonomy():
    """taxonomy 表為空時，冪等地帶入 legacy taxonomy（已有任何版本就略過）。"""
    from services.taxonomy_bootstrap_service import (
        bootstrap_legacy_taxonomy,
        ensure_published_topic_unique_index,
    )

    with app.app_context():
        result = bootstrap_legacy_taxonomy(logger=app.logger)
        click.echo(f"bootstrap：{result}")
        click.echo(f"published guard index：{ensure_published_topic_unique_index(app.logger)}")
        if result["status"] == "lock_timeout":
            sys.exit(1)
