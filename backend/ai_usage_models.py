"""
AI 用量與成本管理的資料表（Admin「AI 用量與成本」頁使用）。

設計原則：
    - 只記錄「數字」：時間、功能、模型、呼叫結果、token 數、所屬單位。
      不存 prompt、問卷原文、使用者回答、AI 回應內容，也不存 email，
      避免用量紀錄本身變成另一份敏感資料。
    - 寫入由 services/ai_usage_service.py 集中處理，使用獨立的資料庫
      連線與交易：寫紀錄失敗只寫 log，不影響原本的 AI 分析流程，也不會
      連帶 rollback 分析結果。
    - 單價、匯率、配額都存在資料表裡由 Admin 調整，並記錄參考日期，
      不寫死在程式中（Google 會調價、改配額）。
    - 時間一律存台灣時間（naive datetime），跟專案其他表一致。
"""

from extensions import db


# 每一次 AI 呼叫一筆（含失敗的呼叫：失敗不計 token，但會佔用請求次數配額）。
# 明細保留 AI_USAGE_RETENTION_DAYS 天（預設 180），之後彙總進 AI_Usage_Daily 再刪除。
class AI_Usage_Log(db.Model):
    __tablename__ = "AI_Usage_Log"

    log_id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, nullable=False, index=True)

    # 功能代碼：classification / segmentation / routing / summary / second_opinion /
    # review_chat / taxonomy_generation / translation / chat_ask /
    # survey_generation / survey_revision / other（對照表見 ai_usage_service.FEATURES）
    feature = db.Column(db.String(40), nullable=False, index=True)
    # 預計使用的模型（主要模型）與實際回應的模型（備援時兩者不同；成本依實際模型計算）
    requested_model = db.Column(db.String(64), nullable=True)
    actual_model = db.Column(db.String(64), nullable=False)
    # success / quota（429）/ unavailable（503）/ error（其他）
    outcome = db.Column(db.String(20), nullable=False)
    # 失敗時的 HTTP 狀態碼（只存數字代碼，不存錯誤訊息內容）
    error_code = db.Column(db.String(10), nullable=True)

    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    # thinking 模型的思考 token（Gemini 依輸出單價計費）
    thinking_tokens = db.Column(db.Integer, nullable=False, default=0)
    latency_ms = db.Column(db.Integer, nullable=True)

    # 所屬單位：survey_generation（一次問卷生成，unit_id = task_id）/
    # analysis_batch（一次分析批次，unit_id = upload_batch_id 或問卷分析批次 id）
    unit_type = db.Column(db.String(30), nullable=True)
    unit_id = db.Column(db.String(64), nullable=True, index=True)
    # 只存 user_id；要知道是誰用 user_id 去關聯 User 表，這裡不存 email
    user_id = db.Column(db.Integer, nullable=True)


# 每個「單位」一筆：一次問卷生成、一次分析批次。用來算「每份問卷平均」、
# 「每 100 筆回覆平均」、「每 1,000 字平均」。只存筆數與字數，不存內容。
class AI_Usage_Unit(db.Model):
    __tablename__ = "AI_Usage_Unit"
    __table_args__ = (db.UniqueConstraint("unit_type", "unit_id", name="uq_ai_usage_unit"),)

    unit_pk = db.Column(db.Integer, primary_key=True, autoincrement=True)
    unit_type = db.Column(db.String(30), nullable=False)
    unit_id = db.Column(db.String(64), nullable=False)
    user_id = db.Column(db.Integer, nullable=True)
    # 送進 AI 分析的回覆筆數與總字數（字元數）；問卷生成為 0
    item_count = db.Column(db.Integer, nullable=False, default=0)
    char_count = db.Column(db.Integer, nullable=False, default=0)
    # completed / failed
    status = db.Column(db.String(20), nullable=False, default="completed")
    created_at = db.Column(db.DateTime, nullable=False, index=True)
    finished_at = db.Column(db.DateTime, nullable=True)


# 超過保留期限的明細彙總成每日一筆（日期 × 功能 × 實際模型 × 呼叫結果），
# 長期趨勢仍查得到，但資料表不會無限增長。
class AI_Usage_Daily(db.Model):
    __tablename__ = "AI_Usage_Daily"
    __table_args__ = (
        db.UniqueConstraint("day", "feature", "actual_model", "outcome", name="uq_ai_usage_daily"),
    )

    daily_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    day = db.Column(db.Date, nullable=False, index=True)
    feature = db.Column(db.String(40), nullable=False)
    actual_model = db.Column(db.String(64), nullable=False)
    outcome = db.Column(db.String(20), nullable=False)
    calls = db.Column(db.Integer, nullable=False, default=0)
    input_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    output_tokens = db.Column(db.BigInteger, nullable=False, default=0)
    thinking_tokens = db.Column(db.BigInteger, nullable=False, default=0)


# 各模型的單價（美金／每百萬 token）與官方配額（RPM / TPM / RPD），Admin 可調整。
# 數值都可以是空的：沒填單價的模型不估算金額，沒填配額的模型只顯示用量不比對上限。
class AI_Model_Price(db.Model):
    __tablename__ = "AI_Model_Price"

    model_name = db.Column(db.String(64), primary_key=True)
    input_usd_per_mtok = db.Column(db.Numeric(12, 6), nullable=True)
    output_usd_per_mtok = db.Column(db.Numeric(12, 6), nullable=True)
    rpm_limit = db.Column(db.Integer, nullable=True)
    tpm_limit = db.Column(db.Integer, nullable=True)
    rpd_limit = db.Column(db.Integer, nullable=True)
    # 單價／配額參考的官方公告日期
    reference_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)
    updated_by_admin_id = db.Column(db.Integer, nullable=True)


# 其他設定（目前只有匯率 fx_usd_twd：1 美金 = ? 新台幣）
class AI_Usage_Setting(db.Model):
    __tablename__ = "AI_Usage_Setting"

    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.String(100), nullable=True)
    reference_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)
    updated_by_admin_id = db.Column(db.Integer, nullable=True)


AI_USAGE_MODELS = (AI_Usage_Log, AI_Usage_Unit, AI_Usage_Daily, AI_Model_Price, AI_Usage_Setting)
