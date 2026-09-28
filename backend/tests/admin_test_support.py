"""
Admin 系統整合測試共用 fixture（不是測試本身；檔名刻意不以 test_ 開頭）。

- Flask app + SQLite（預設 in-memory，可傳 db_uri 用檔案 DB 做併發測試）
- 註冊所有 Admin / Review / Report / Workspace / Export / Chat 相關 blueprint
- 建立完整 schema（MEDIUMTEXT 在 SQLite 編譯成 TEXT）＋ published 唯一索引
- 假的 Gemini：直接替換 services.gemini_client.GenerativeModel（不偽造
  sys.modules["google"]），依序從佇列吐出回應；佇列空了就拋例外，讓
  aggregated summary 這類非關鍵呼叫走 fallback。
"""

import json
import os
import sys

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt  # noqa: E402
from flask import Flask  # noqa: E402
from sqlalchemy.dialects.mysql import MEDIUMTEXT  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402

import models as m  # noqa: E402
import services.gemini_client as gemini_client  # noqa: E402
from extensions import db  # noqa: E402
from routes.auth.admin_guard import build_admin_token  # noqa: E402


@compiles(MEDIUMTEXT, "sqlite")
def _compile_mediumtext_sqlite(element, compiler, **kwargs):
    return "TEXT"


GEMINI_QUEUE = []
GEMINI_CALLS = []


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, model_name=None, system_instruction=None, **kwargs):
        self.system_instruction = system_instruction

    def generate_content(self, contents, **kwargs):
        GEMINI_CALLS.append({"system_instruction": self.system_instruction, "contents": contents})
        if not GEMINI_QUEUE:
            raise RuntimeError("fake gemini queue empty")
        item = GEMINI_QUEUE.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))


gemini_client.GenerativeModel = FakeModel

# aggregated summary / routing 的重試會 time.sleep（2~20 秒）；測試裡只替換
# 這兩個模組內部引用的 time，不影響其他模組的 time.sleep。
import types as _types  # noqa: E402
import time as _time  # noqa: E402
import services.aggregated_summary_service as _summary_service  # noqa: E402
import services.question_routing_service as _routing_service  # noqa: E402

_no_sleep_time = _types.SimpleNamespace(sleep=lambda _s: None, time=_time.time, monotonic=_time.monotonic)
_summary_service.time = _no_sleep_time
_routing_service.time = _no_sleep_time


def q(*items):
    GEMINI_QUEUE.extend(items)


FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


def finish():
    print("\n" + "=" * 50)
    if FAILED:
        print(f"共 {len(FAILED)} 項測試失敗：")
        for f in FAILED:
            print("  -", f)
        sys.exit(1)
    print("全部測試通過！")


def create_app(db_uri=None):
    """db_uri 未指定時使用 ADMIN_TEST_DATABASE_URI（例如在 CI 指向一個空的
    MySQL database，驗證 SELECT ... FOR UPDATE / DDL 在正式 DB 引擎上的行為），
    否則使用 SQLite in-memory。"""
    db_uri = db_uri or os.environ.get("ADMIN_TEST_DATABASE_URI") or "sqlite:///:memory:"
    from routes.admin.ai_admin import ai_admin_bp
    from routes.chats.chat import chat_bp
    from routes.classifications.classification import classification_bp
    from routes.classifications.report import report_bp
    from routes.classifications.review import review_bp
    from routes.exports.export import exports_bp
    from services.taxonomy_bootstrap_service import ensure_published_topic_unique_index

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config["TESTING"] = True
    for bp in (ai_admin_bp, chat_bp, classification_bp, report_bp, review_bp, exports_bp):
        app.register_blueprint(bp)
    db.init_app(app)
    with app.app_context():
        if not db_uri.startswith("sqlite"):
            db.drop_all()
        db.create_all()
        ensure_published_topic_unique_index()
    return app


def user_header(user_id):
    token = jwt.encode({"user_id": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def admin_header(admin_id):
    return {"Authorization": f"Bearer {build_admin_token(admin_id)}"}


def seed_people():
    db.session.add_all([
        m.User(user_id=1, user_name="owner", email="owner@example.com", password_hash="x"),
        m.Admin(admin_id=1, admin_name="Alice", email="alice@example.com", password_hash="x"),
        m.Admin(admin_id=2, admin_name="Bob", email="bob@example.com", password_hash="x"),
    ])
    db.session.commit()


def seed_topic(topic_key="custom_topic", categories=None, status="published", version_number=1):
    """建立 Topic + 一個 taxonomy version（預設 published）。"""
    categories = categories or [
        ("Main A", "A1 Original", "Method A1", "Cite A1"),
        ("Main B", "B1 Candidate", "Method B1", "Cite B1"),
    ]
    if db.session.get(m.Topic, topic_key) is None:
        db.session.add(m.Topic(topic_key=topic_key, title=f"Topic {topic_key}"))
    version = m.Taxonomy_Version(topic_key=topic_key, version_number=version_number, status=status, source="manual")
    db.session.add(version)
    db.session.flush()
    for i, (main, sub, method, cite) in enumerate(categories, start=1):
        db.session.add(m.Taxonomy_Category(
            version_id=version.version_id, main_category=main, sub_category=sub,
            methodology=method, citation=cite, definition=f"{sub} definition", sort_order=i,
        ))
    db.session.commit()
    return version.version_id


def seed_upload_batch(batch_id, texts, question_type="custom_topic", column="意見", user_id=1):
    """建立一批 Uploaded_Answer，回傳 [answer_id, ...]。"""
    ids = []
    for idx, text in enumerate(texts):
        answer = m.Uploaded_Answer(
            upload_batch_id=batch_id, user_id=user_id, source_column=column, row_index=idx,
            answer_text=text, question_type=question_type, routing_status="routed",
        )
        db.session.add(answer)
        db.session.flush()
        ids.append(answer.id)
    db.session.commit()
    return ids


def seed_classification(answer_id, batch_id, text, main, sub, *, version_id=None, status="completed",
                        review_status="pending_review", confidence=0.95, question_id=None, **extra):
    row = m.Response_Classification(
        source_type="user_upload", upload_batch_id=batch_id, uploaded_answer_id=answer_id,
        question_id=question_id or f"意見_row{answer_id}", answer_text=text,
        segment_start=0, segment_end=len(text), main_category=main, sub_category=sub,
        reasoning=f"AI reasoning for {sub}", summary=f"summary {sub}", status=status,
        review_status=review_status, taxonomy_version_id=version_id, confidence=confidence,
        **extra,
    )
    db.session.add(row)
    db.session.flush()
    status_row = m.Response_Segmentation_Status.query.filter_by(uploaded_answer_id=answer_id).first()
    if status_row is None:
        db.session.add(m.Response_Segmentation_Status(
            upload_batch_id=batch_id, uploaded_answer_id=answer_id, question_id=row.question_id,
            source_type="user_upload", segmentation_status="completed",
        ))
    db.session.commit()
    return row.classification_id


def seed_workspace_chat(batch_id, rows=None, meta_extra=None, project_id=1):
    """建立一個 Workspace + 一則分類結果訊息（模擬前端存進 Chat_History 的快照）。"""
    from services.workspace_result_service import build_classification_message

    if db.session.get(m.Workspace, project_id) is None:
        db.session.add(m.Workspace(project_id=project_id, user_id=1, project_name="ws"))
        db.session.flush()
    meta = {"upload_batch_id": batch_id, "source_filename": "t.xlsx"}
    meta.update(meta_extra or {})
    chat = m.Chat_History(
        project_id=project_id, sender_type="ai",
        message_content=build_classification_message({"rows": rows or [], "meta": meta, "rating_stats": []}),
    )
    db.session.add(chat)
    db.session.commit()
    return chat.chat_id
