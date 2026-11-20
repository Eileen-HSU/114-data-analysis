#!/usr/bin/env python
"""AI 用量與成本管理：紀錄、單位平均、成本估算、配額監控、設定驗證、保留期限。

不打真實 API（假的 Gemini client / response）。SQLite 檔案 DB（用量紀錄走獨立
連線，in-memory DB 的單一連線測不出「獨立交易」）。
執行：cd backend && python3 tests/test_ai_usage.py
"""
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt  # noqa: E402
from flask import Flask, jsonify  # noqa: E402
from sqlalchemy.dialects.mysql import MEDIUMTEXT  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402

import ai_usage_models as um  # noqa: E402
import models as m  # noqa: E402
import services.gemini_client as gc  # noqa: E402
from audit import Admin_Audit_Log  # noqa: E402
from extensions import db  # noqa: E402
from routes.admin.ai_usage import ai_usage_bp  # noqa: E402
from routes.auth.admin_guard import build_admin_token  # noqa: E402
from services import ai_usage_report_service as report  # noqa: E402
from services import ai_usage_service as usage  # noqa: E402


@compiles(MEDIUMTEXT, "sqlite")
def _mediumtext(element, compiler, **kw):
    return "TEXT"


FAILED = []


def check(label, ok):
    print(("[PASS] " if ok else "[FAIL] ") + label)
    if not ok:
        FAILED.append(label)


def response(inp, out, think=0, text="ok"):
    meta = types.SimpleNamespace(prompt_token_count=inp, candidates_token_count=out,
                                 thoughts_token_count=think, total_token_count=inp + out + think)
    return types.SimpleNamespace(text=text, usage_metadata=meta)


tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp.name}"
app.config["TESTING"] = True
app.register_blueprint(ai_usage_bp)
db.init_app(app)
usage.init_app(app)


@app.route("/test/analysis", methods=["POST"])
def fake_analysis():
    usage.bind_request_unit(usage.UNIT_ANALYSIS_BATCH, "batch-req", user_id=7)
    usage.add_items(4, 1200)
    usage.record_call("classification", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite", response=response(900, 100))
    return jsonify({"ok": True})


with app.app_context():
    db.create_all()
    db.session.add_all([
        m.Admin(admin_id=1, admin_name="Alice", email="alice@example.com", password_hash="x"),
        m.User(user_id=7, user_name="u", email="u@example.com", password_hash="x"),
    ])
    db.session.commit()

client = app.test_client()
ADMIN = {"Authorization": f"Bearer {build_admin_token(1)}"}
USER = {"Authorization": "Bearer " + jwt.encode({"account_type": "user", "user_id": 7},
                                                 os.environ["JWT_SECRET_KEY"], algorithm="HS256")}


def logs():
    return um.AI_Usage_Log.query.order_by(um.AI_Usage_Log.log_id).all()


def reset():
    for model in (um.AI_Usage_Log, um.AI_Usage_Unit, um.AI_Usage_Daily, um.AI_Model_Price, um.AI_Usage_Setting):
        model.query.delete()
    db.session.commit()


print("== 1. 成功呼叫：記錄 token，不存任何內容 ==")
with app.app_context():
    usage.record_call("classification", "gemini-3.1-flash-lite", "models/gemini-3.1-flash-lite",
                      response=response(1000, 200, 50, text="機密回答內容"))
    rows = logs()
    r = rows[-1]
    check("寫入一筆", len(rows) == 1)
    check("輸入／輸出／思考 token 正確", (r.input_tokens, r.output_tokens, r.thinking_tokens) == (1000, 200, 50))
    check("模型名稱去掉 models/ 前綴", r.actual_model == "gemini-3.1-flash-lite")
    check("outcome = success", r.outcome == "success" and r.error_code is None)
    columns = {c.name for c in um.AI_Usage_Log.__table__.columns}
    check("資料表沒有任何存放內容或 email 的欄位",
          not columns & {"prompt", "contents", "text", "answer_text", "response_text", "email"})
    check("回應內容沒有被寫進任何欄位",
          "機密回答內容" not in " ".join(str(getattr(r, c)) for c in columns))

print("== 2. 失敗呼叫：記狀態碼，不記錯誤訊息、不計 token ==")
with app.app_context():
    usage.record_call("routing", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite",
                      error=RuntimeError("429 RESOURCE_EXHAUSTED. quota for user secret@example.com"))
    usage.record_call("routing", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite",
                      error=RuntimeError("503 UNAVAILABLE overloaded"))
    usage.record_call("routing", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite", error=ValueError("bad json"))
    quota, unavailable, other = logs()[-3:]
    check("429 → quota", quota.outcome == "quota" and quota.error_code == "429")
    check("503 → unavailable", unavailable.outcome == "unavailable" and unavailable.error_code == "503")
    check("其他 → error", other.outcome == "error")
    check("失敗不計 token", quota.input_tokens == 0 and quota.output_tokens == 0)
    check("錯誤訊息內容（含 email）沒有被存下來",
          all("secret@example.com" not in str(getattr(quota, c.name)) for c in um.AI_Usage_Log.__table__.columns))

print("== 3. 記錄失敗不影響呼叫端，也不會 rollback 呼叫端 ==")
with app.app_context():
    db.session.add(m.User(user_id=99, user_name="pending", email="pending@example.com", password_hash="x"))
    before = um.AI_Usage_Log.query.count()
    db.session.rollback()
    usage.record_call("classification", "m", "m", response=response(1, 1))
    db.session.rollback()  # 呼叫端 rollback 自己的交易
    check("呼叫端 rollback 後用量紀錄仍在（獨立交易）", um.AI_Usage_Log.query.count() == before + 1)
    check("用量紀錄沒有把呼叫端未 commit 的資料一起寫入", db.session.get(m.User, 99) is None)
    original = usage._insert_log
    usage._insert_log = lambda row: (_ for _ in ()).throw(RuntimeError("db down"))
    try:
        usage.record_call("classification", "m", "m", response=response(1, 1))
        check("資料庫寫入失敗時 record_call 不拋例外", True)
    except Exception:  # noqa: BLE001
        check("資料庫寫入失敗時 record_call 不拋例外", False)
    finally:
        usage._insert_log = original
    try:
        usage.record_call("classification", "m", "m", response=object())
        check("回應沒有 usage_metadata 時不拋例外", logs()[-1].input_tokens == 0)
    except Exception:  # noqa: BLE001
        check("回應沒有 usage_metadata 時不拋例外", False)

print("== 4. 沒有 app context 的背景 thread 也能寫入 ==")
import threading  # noqa: E402

with app.app_context():
    before = um.AI_Usage_Log.query.count()


def background():
    token = usage.begin_unit(usage.UNIT_SURVEY_GENERATION, "task-bg", user_id=7, label="課程簡報.pdf")
    usage.set_response_total(42)
    usage.record_call(usage.current_feature("survey_generation"), "gemini-3.8-flash", "gemini-3.8-flash",
                      response=response(5000, 800))
    usage.finish_unit(token)


t = threading.Thread(target=background)
t.start()
t.join()
with app.app_context():
    r = logs()[-1]
    check("背景 thread 寫入成功", um.AI_Usage_Log.query.count() == before + 1)
    check("歸到背景工作開的單位", r.unit_type == "survey_generation" and r.unit_id == "task-bg" and r.user_id == 7)
    unit = um.AI_Usage_Unit.query.filter_by(unit_id="task-bg").first()
    check("單位寫入 completed", unit is not None and unit.status == "completed")
    check("單位記下顯示名稱（檔名）", unit.label == "課程簡報.pdf")
    check("單位記下回覆總數（含沿用、不送 AI 的）", unit.response_total == 42)

print("== 5. request 內的分析批次：teardown 自動收尾 ==")
resp = client.post("/test/analysis")
with app.app_context():
    unit = um.AI_Usage_Unit.query.filter_by(unit_id="batch-req").first()
    check("request 成功", resp.status_code == 200)
    check("單位記下筆數與字數", unit is not None and (unit.item_count, unit.char_count) == (4, 1200))
    check("該 request 的呼叫歸到這個單位", logs()[-1].unit_id == "batch-req")
    check("request 結束後單位已清除，不殘留到下一次", usage.current_unit() is None)
    usage.record_call("classification", "m", "m", response=response(1, 1))
    check("request 外的呼叫不帶單位", logs()[-1].unit_id is None)

print("== 6. GenerativeModel：功能自動判斷、備援時分開記主要模型與實際模型 ==")


class FakeClient:
    def __init__(self, behavior):
        self.behavior, self.models = behavior, self

    def generate_content(self, model, contents, config):
        result = self.behavior[model]
        if isinstance(result, Exception):
            raise result
        return result


check("模組對照：classify_v2 → classification", usage.feature_for_module("services.classify_v2") == "classification")
check("未知模組 → other", usage.feature_for_module("tests.whatever") == "other")
with app.app_context():
    reset()
    os.environ.pop("GEMINI_FALLBACK_MODEL", None)
    gc._create_client = lambda: FakeClient({
        "gemini-3.1-flash-lite": RuntimeError("503 UNAVAILABLE"),
        "gemini-3.5-flash-lite": response(300, 30),
    })
    out = gc.GenerativeModel("gemini-3.1-flash-lite", usage_feature="segmentation").generate_content("hi")
    rows = logs()
    check("備援成功仍回傳結果", out.usage_metadata.prompt_token_count == 300)
    check("記兩筆：主要模型失敗 + 備援成功", [x.outcome for x in rows] == ["unavailable", "success"])
    check("預計模型都記主要模型", all(x.requested_model == "gemini-3.1-flash-lite" for x in rows))
    check("實際模型記備援模型（成本依實際模型算）", rows[1].actual_model == "gemini-3.5-flash-lite")
    check("功能代碼帶入", all(x.feature == "segmentation" for x in rows))
    check("記錄延遲時間", rows[1].latency_ms is not None and rows[1].latency_ms >= 0)

print("== 7. 設定：驗證、寫入、操作紀錄、權限 ==")
check("沒有 token → 401", client.get("/api/admin/ai/usage/summary").status_code == 401)
check("一般使用者 token → 403", client.get("/api/admin/ai/usage/summary", headers=USER).status_code == 403)
check("一般使用者不能改設定", client.put("/api/admin/ai/usage/settings", headers=USER, json={}).status_code == 403)
bad = client.put("/api/admin/ai/usage/settings", headers=ADMIN, json={"models": [
    {"model_name": "gemini-3.1-flash-lite", "input_usd_per_mtok": -1}]})
check("負的單價 → 400", bad.status_code == 400)
bad = client.put("/api/admin/ai/usage/settings", headers=ADMIN, json={"models": [
    {"model_name": "<script>", "input_usd_per_mtok": 1}]})
check("不合法的模型名稱 → 400", bad.status_code == 400)
bad = client.put("/api/admin/ai/usage/settings", headers=ADMIN, json={"fx": {"usd_twd": 0}})
check("匯率 0 → 400", bad.status_code == 400)
bad = client.put("/api/admin/ai/usage/settings", headers=ADMIN, json={"models": [
    {"model_name": "gemini-3.1-flash-lite", "rpd_limit": "abc"}]})
check("配額不是整數 → 400", bad.status_code == 400)
ok = client.put("/api/admin/ai/usage/settings", headers=ADMIN, json={
    "models": [
        {"model_name": "gemini-3.1-flash-lite", "input_usd_per_mtok": "0.10", "output_usd_per_mtok": "0.40",
         "rpm_limit": 10, "tpm_limit": 100000, "rpd_limit": 20, "reference_date": "2026-11-01"},
        {"model_name": "gemini-3.8-flash", "input_usd_per_mtok": 0.5, "output_usd_per_mtok": 3,
         "reference_date": "2026-11-01"},
    ],
    "fx": {"usd_twd": "32.5", "reference_date": "2026-11-15"},
})
data = ok.get_json()
check("合法設定 → 200", ok.status_code == 200)
check("回傳已更新的單價", any(x["model_name"] == "gemini-3.1-flash-lite" and x["input_usd_per_mtok"] == 0.1
                         for x in data["models"]))
check("回傳匯率與參考日期", data["fx"] == {"usd_twd": 32.5, "reference_date": "2026-11-15"})
with app.app_context():
    audits = Admin_Audit_Log.query.filter_by(action="ai_pricing_update").all()
    check("每項變更都寫進操作紀錄（2 個模型 + 匯率）", len(audits) == 3 and all(a.admin_id == 1 for a in audits))
again = client.put("/api/admin/ai/usage/settings", headers=ADMIN, json={"fx": {"usd_twd": "32.5", "reference_date": "2026-11-15"}})
check("沒有變更時不重複寫操作紀錄", again.get_json()["changed"] == 0)

print("== 8. 統計：單位平均、P90、成本、資料不足 ==")
NOW = datetime(2026, 11, 20, 10, 30)


def add_log(created, feature, model, inp, out, unit_type=None, unit_id=None, outcome="success", think=0):
    db.session.add(um.AI_Usage_Log(created_at=created, feature=feature, requested_model=model, actual_model=model,
                                   outcome=outcome, input_tokens=inp, output_tokens=out, thinking_tokens=think,
                                   unit_type=unit_type, unit_id=unit_id))


def add_unit(unit_type, unit_id, items=0, chars=0, status="completed", created=NOW - timedelta(days=1)):
    db.session.add(um.AI_Usage_Unit(unit_type=unit_type, unit_id=unit_id, item_count=items, char_count=chars,
                                    status=status, created_at=created))


with app.app_context():
    um.AI_Usage_Log.query.delete()
    um.AI_Usage_Unit.query.delete()
    db.session.commit()
    # 兩份問卷生成（不足 3 份 → 資料不足）
    for i, tokens in enumerate((6000, 8000)):
        add_unit("survey_generation", f"gen{i}")
        add_log(NOW - timedelta(days=1), "survey_generation", "gemini-3.8-flash", tokens, 1000, "survey_generation", f"gen{i}")
    # 三個分析批次：每批 100 筆，token 分別 10k / 20k / 30k（每 100 筆）
    for i, tokens in enumerate((10000, 20000, 30000)):
        add_unit("analysis_batch", f"b{i}", items=100, chars=10000)
        add_log(NOW - timedelta(days=1), "classification", "gemini-3.1-flash-lite", tokens - 1000, 1000, "analysis_batch", f"b{i}")
    # 一個失敗的批次呼叫（不計入平均）
    add_log(NOW - timedelta(days=1), "classification", "gemini-3.1-flash-lite", 0, 0, "analysis_batch", "b0", outcome="quota")
    db.session.commit()
    s = report.build_summary(now=NOW)
    per100 = s["unit_metrics"]["per_100_responses"]
    g2 = s["unit_metrics"]["per_survey_generation"]
    check("問卷生成只有 2 份 → 仍顯示（樣本數 2，前端標示僅供參考）", g2 and g2["tokens"]["n"] == 2)
    check("回傳建議樣本數 3", s["unit_metrics"]["reliable_units"] == 3)
    check("每 100 筆平均 = 20,000 tokens", per100 and abs(per100["tokens"]["avg"] - 20000) < 1e-6)
    check("每 100 筆 P90 = 30,000 tokens", per100["tokens"]["p90"] == 30000)
    check("樣本數 = 3", per100["tokens"]["n"] == 3)
    # 成本：20k 平均 = 19k 輸入 × 0.1 + 1k 輸出 × 0.4（每百萬）= 0.0019 + 0.0004
    check("每 100 筆平均成本（美金）", abs(per100["cost_usd"]["avg"] - 0.0023) < 1e-9)
    check("每 1,000 字平均 = 2,000 tokens", abs(s["unit_metrics"]["per_1000_chars"]["tokens"]["avg"] - 2000) < 1e-6)
    check("步驟拆分：classification 每 100 筆", per100["by_feature"][0]["feature"] == "classification")
    check("匯率一起回傳", s["currency"]["usd_twd"] == 32.5)
    b0 = next(u for u in s["recent_units"] if u["unit_type"] == "analysis_batch" and u["total_tokens"] == 10000)
    check("單份明細：每次分析各自的 token", b0["input_tokens"] == 9000 and b0["output_tokens"] == 1000)
    check("單份明細：失敗呼叫另計、不算成本", b0["failed_calls"] == 1 and abs(b0["cost_usd"] - 0.0013) < 1e-9)
    check("單份明細：回覆筆數與類型", b0["item_count"] == 100 and b0["type_label"] == "回覆分析")

    # 第三份問卷生成 → 可以算了；失敗的生成不算
    add_unit("survey_generation", "gen2")
    add_log(NOW - timedelta(days=1), "survey_generation", "gemini-3.8-flash", 7000, 1000, "survey_generation", "gen2")
    add_unit("survey_generation", "gen-failed", status="failed")
    add_log(NOW - timedelta(days=1), "survey_generation", "gemini-3.8-flash", 99999, 0, "survey_generation", "gen-failed")
    db.session.commit()
    s = report.build_summary(now=NOW)
    gen = s["unit_metrics"]["per_survey_generation"]
    check("3 份成功生成 → 平均 8,000 tokens（失敗的不算）", gen and abs(gen["tokens"]["avg"] - 8000) < 1e-6)
    check("問卷生成平均成本：7k×0.5 + 1k×3（每百萬）", abs(gen["cost_usd"]["avg"] - 0.0065) < 1e-9)

    # 本月、功能別、模型別
    month = s["month"]
    check("本月呼叫次數與 token 有算到（8 次）", month["total_tokens"] > 0 and month["calls"] == 8)
    check("本月失敗次數 = 1", month["failed"] == 1)
    check("功能別占比加總約為 1", abs(sum(x["share"] for x in s["by_feature"]) - 1) < 1e-9)
    check("今日沒有用量", s["today"]["calls"] == 0)

    # 沒設定單價的模型：不估算金額，列出缺單價的模型
    add_log(NOW - timedelta(hours=1), "summary", "gemini-x-unpriced", 100, 10)
    db.session.commit()
    s = report.build_summary(now=NOW)
    check("缺單價的模型被列出", s["missing_price_models"] == ["gemini-x-unpriced"])
    check("本月金額標示為不完整", s["month"].get("cost_usd_partial") is True)

print("== 9. 配額監控 ==")
with app.app_context():
    base = NOW.replace(minute=0)
    for i in range(9):  # 同一分鐘 9 次請求 → 達 RPM 10 的 80%
        add_log(base + timedelta(seconds=i), "classification", "gemini-3.1-flash-lite", 100, 10)
    add_log(base + timedelta(seconds=30), "classification", "gemini-3.1-flash-lite", 0, 0, outcome="quota")
    db.session.commit()
    q = {x["model"]: x for x in report.build_summary(now=NOW)["quota"]}
    lite = q["gemini-3.1-flash-lite"]
    check("今日請求數（含失敗）", lite["requests_today"] == 10)
    check("今日每分鐘尖峰請求數", lite["peak_rpm_today"] == 10)
    check("今日 429 次數", lite["quota_errors_today"] == 1)
    check("提醒：出現 429、接近 RPM", {"quota_errors", "near_rpm"} <= set(lite["warnings"]))
    check("今日 10 次未達 RPD 20 的 80%，不提醒 RPD", "near_rpd" not in lite["warnings"])
    check("帶出配額與參考日期", lite["rpm_limit"] == 10 and lite["reference_date"] == "2026-11-01")

print("== 10. 保留期限：舊明細彙總成每日一筆後刪除 ==")
with app.app_context():
    old = NOW - timedelta(days=200)
    add_log(old, "classification", "gemini-3.1-flash-lite", 1000, 100)
    add_log(old + timedelta(hours=1), "classification", "gemini-3.1-flash-lite", 2000, 200)
    db.session.commit()
    total_before = um.AI_Usage_Log.query.count()
    moved = usage.rollup_and_purge(now=NOW, days=180)
    daily = um.AI_Usage_Daily.query.all()
    check("彙總了 2 筆舊明細", moved == 2)
    check("舊明細已刪除", um.AI_Usage_Log.query.count() == total_before - 2)
    check("每日一筆，token 加總正確", len(daily) == 1 and daily[0].calls == 2
          and daily[0].input_tokens == 3000 and daily[0].output_tokens == 300)
    check("重複執行不會重複彙總", usage.rollup_and_purge(now=NOW, days=180) == 0
          and um.AI_Usage_Daily.query.first().calls == 2)
    s = report.build_summary(now=NOW, month=old.strftime("%Y-%m"))
    check("彙總後的月份仍查得到用量", s["month"]["calls"] == 2 and s["month"]["input_tokens"] == 3000)

print("== 11. API 回應 ==")
resp = client.get("/api/admin/ai/usage/summary", headers=ADMIN)
check("summary → 200", resp.status_code == 200 and "unit_metrics" in resp.get_json())
check("month 格式錯誤 → 400", client.get("/api/admin/ai/usage/summary?month=abc", headers=ADMIN).status_code == 400)
settings = client.get("/api/admin/ai/usage/settings", headers=ADMIN).get_json()
check("設定頁列出程式用到的模型", {"gemini-3.1-flash-lite", "gemini-3.8-flash"} <= {x["model_name"] for x in settings["models"]})

os.unlink(tmp.name)
print("\n" + "=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("全部測試通過！")
