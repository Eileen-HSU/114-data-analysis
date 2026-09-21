"""
cli.py

集中管理原本散落在根目錄的一次性維運／管理腳本，2026-09 合併於此。

原本這 7 支各自獨立的腳本：
    init_workspace.py        -> flask init-workspace
    diagnose.py               -> flask diagnose
    seed_prompt_templates.py  -> flask seed-prompts
    update_prompts.py         -> flask update-prompts
    fix_access_codes.py       -> flask fix-access-codes
    create_admin.py           -> flask create-admin
    run_classification.py     -> flask run-classification

全部改用 Flask 官方支援的 CLI command（@app.cli.command()）統一掛在
同一個進入點，不再各自重複「開一個 app.app_context() 做一件事」的
樣板程式碼，也不用記一堆檔名，只要記得都是 `flask <子指令>`。

其中 seed_prompt_templates.py / update_prompts.py / create_admin.py /
run_classification.py 原本刻意「自己組一個最小的 Flask app」，是為了
避免載入完整 app.py（含所有 routes）才能跑一支小腳本；改成 CLI
command 之後，這些指令本來就是透過 `flask` 指令、以完整 app.py
啟動，這個顧慮不再適用，因此統一改為直接使用 app.py 建立好的 app
實例，不再各自建立最小 app。

【使用方式】
    cd backend
    FLASK_APP=cli.py flask <子指令> [選項]

例如：
    FLASK_APP=cli.py flask init-workspace
    FLASK_APP=cli.py flask diagnose
    FLASK_APP=cli.py flask seed-prompts
    FLASK_APP=cli.py flask update-prompts
    FLASK_APP=cli.py flask fix-access-codes
    FLASK_APP=cli.py flask create-admin --enable-2fa
    FLASK_APP=cli.py flask run-classification

用 `FLASK_APP=cli.py flask --help` 可以列出全部子指令。
"""

import csv
import os
import re
import sys
import time
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
# flask seed-prompts（原 seed_prompt_templates.py）
# ═══════════════════════════════════════════════════════════════
@app.cli.command("seed-prompts")
def seed_prompts():
    """一次性腳本：把 classify_v2.py 的預設 prompt 寫進 Prompt_Template 表。"""
    from models import Prompt_Template
    from services.classify_v2 import DEFAULT_PROMPT_LEADERSHIP, DEFAULT_PROMPT_CAREER
    from services.subcategory_methodology import QUESTION_LEADERSHIP, QUESTION_CAREER

    seeds = [
        (QUESTION_LEADERSHIP, DEFAULT_PROMPT_LEADERSHIP),
        (QUESTION_CAREER, DEFAULT_PROMPT_CAREER),
    ]
    for key, content in seeds:
        existing = Prompt_Template.query.get(key)
        if existing:
            click.echo(f"prompt_key='{key}' 已存在，略過（如需重置請先手動刪除）")
            continue
        row = Prompt_Template(
            prompt_key=key,
            draft_content=content,
            live_content=content,
            draft_validated=True,  # 初始值等同正式版，視為已驗證
        )
        db.session.add(row)
        click.echo(f"已新增 prompt_key='{key}'")
    db.session.commit()
    click.echo("完成")


# ═══════════════════════════════════════════════════════════════
# flask update-prompts（原 update_prompts.py）
# ═══════════════════════════════════════════════════════════════
@app.cli.command("update-prompts")
def update_prompts():
    """一次性腳本：把更新過的 prompt 常數推進資料庫（更新草稿→測試→發布）。

    run_classification 實際呼叫的是資料庫裡 Prompt_Template.live_content，
    不是 classify_v2.py 裡的常數本身，改了 .py 檔案不會自動生效，
    必須執行這個指令才會真的推進到正式版。
    """
    from services.prompt_admin_service import update_draft, test_draft_prompt, publish_prompt
    from services.classify_v2 import DEFAULT_PROMPT_LEADERSHIP, DEFAULT_PROMPT_CAREER
    from services.subcategory_methodology import QUESTION_LEADERSHIP, QUESTION_CAREER

    def _update_and_publish(prompt_key, new_content):
        click.echo(f"--- {prompt_key} ---")
        update_draft(prompt_key, new_content)
        click.echo("  已更新草稿")

        result = test_draft_prompt(prompt_key)
        click.echo(
            f"  測試結果：格式合法比例 {result['format_valid_rate']:.0%}，"
            f"跟黃金標籤一致比例 {result['accuracy_vs_golden']:.0%}"
        )

        if not result["can_publish"]:
            click.echo("  ⚠️ 測試未通過，不會發布，請檢查 prompt 內容是否有誤")
            for d in result["details"]:
                if not d["is_format_valid"]:
                    click.echo(f"    格式錯誤：{d['answer_text'][:20]}... -> {d['actual_sub_category']}")
            return

        publish_prompt(prompt_key)
        click.echo("  ✅ 已發布到正式版")

    _update_and_publish(QUESTION_LEADERSHIP, DEFAULT_PROMPT_LEADERSHIP)
    click.echo()
    click.echo("等待 30 秒，避免兩組測試的呼叫次數疊加超過 rate limit...")
    time.sleep(30)
    _update_and_publish(QUESTION_CAREER, DEFAULT_PROMPT_CAREER)


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
# flask run-classification（原 run_classification.py）
# ═══════════════════════════════════════════════════════════════
#
# 讀取 vine 滿意度質化資料 Excel，對每一題的每一則有效回答呼叫
# Gemini 分類，存成 CSV，供後續跟人工分類結果比對。需要：
#   1. 環境變數 GEMINI_API_KEY
#   2. pandas / openpyxl（已在 requirements.txt）
#   3. 對應的 Excel 檔案與這裡的 EXCEL_PATH 一致
_EXCEL_PATH = "vine滿意度質化資料（部門標記＋隨機）ㄐㄠ.xlsx"
_OUTPUT_PATH = "classification_results.csv"


@app.cli.command("run-classification")
def run_classification():
    """讀取 Excel 問卷回饋，逐筆呼叫 Gemini 分類並輸出 CSV 供人工比對。"""
    import pandas as pd
    from services.classify_v2 import (
        classify_response_v2,
        is_text_response,
        QUESTION_LEADERSHIP,
        QUESTION_CAREER,
    )

    if not os.environ.get("GEMINI_API_KEY"):
        click.echo("錯誤：找不到 GEMINI_API_KEY，請確認 .env 檔案或環境變數已設定", err=True)
        return

    column_question_map = {
        "針對主管領導和部門合作這兩項，如果您有機會直接向管理層提出各一項建議，您會提出什麼建議？為什麼這項建議對您和公司很重要？": QUESTION_LEADERSHIP,
        "關於工作表現的回饋及職涯發展，您認為公司再強化或提供哪些協助將能更好地激勵您和您的同事？": QUESTION_CAREER,
    }

    df = pd.read_excel(_EXCEL_PATH)

    rows_to_process = []
    for col in df.columns:
        question_type = column_question_map.get(col)
        if question_type is None:
            click.echo(f"警告：欄位「{col[:30]}...」不在對應表裡，略過")
            continue
        for idx, value in df[col].items():
            if is_text_response(value):
                rows_to_process.append({
                    "respondent_id": idx + 1,
                    "question": col,
                    "question_type": question_type,
                    "answer_text": str(value).strip(),
                })

    click.echo(f"共 {len(rows_to_process)} 筆待分類回答，開始呼叫 Gemini...")

    results = []
    for i, row in enumerate(rows_to_process, 1):
        click.echo(f"[{i}/{len(rows_to_process)}] 分類中：{row['answer_text'][:20]}...")

        classification = classify_response_v2(row["answer_text"], row["question_type"])

        if classification["status"] == "failed":
            click.echo(f"    第一次失敗（{classification['error_detail'][:50]}...），15秒後重試...")
            time.sleep(15)
            classification = classify_response_v2(row["answer_text"], row["question_type"])
            if classification["status"] == "failed":
                click.echo(f"    重試後仍失敗：{classification['error_detail'][:50]}")

        results.append({
            "respondent_id": row["respondent_id"],
            "question": row["question"][:30] + "...",
            "answer_text": row["answer_text"],
            "ai_main_category": classification["main_category"],
            "ai_sub_category": classification["sub_category"],
            "ai_secondary_sub_category": classification["secondary_sub_category"],
            "ai_reasoning": classification["reasoning"],
            "ai_summary": classification["summary"],
            "ai_confidence": classification["confidence"],
            "ai_methodology": classification["methodology"],
            "ai_citation": classification["citation"],
            "ai_secondary_methodology": classification["secondary_methodology"],
            "ai_secondary_citation": classification["secondary_citation"],
            "status": classification["status"],
            "error_detail": classification.get("error_detail"),
        })

        # 免費方案 rate limit 是每分鐘 15 次請求，間隔設 5 秒比較安全
        time.sleep(5)

    with open(_OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    click.echo(f"\n完成！結果已存至 {_OUTPUT_PATH}")

    status_counts = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    click.echo(f"狀態統計：{status_counts}")
