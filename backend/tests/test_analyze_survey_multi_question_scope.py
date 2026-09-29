#!/usr/bin/env python
"""
回歸測試：analyze_survey() 多題問卷的自動主題範圍（scope）不可被覆寫。

舊版 analyze_survey() 先用 scope = "user:<id>" 當自動主題範圍，之後逐則
回答迴圈又把 scope 改成單筆回答的 attempt scope（dict）。第一題跑完後，
第二題如果需要重新 routing 或自動主題，就會拿到上一題最後一則回答的 dict。

涵蓋：
    A. q1 已路由到既有主題；q2 建立問卷時 routing 失敗 -> 分析時重新 routing
       （模型判斷沒有適合主題）-> 自動主題，範圍必須是 user:1
    B. （另一位使用者）q1 已路由；q2 建立時就判斷「沒有適合主題」(undetermined)
       -> 直接走自動主題，範圍必須是 user:2；再次分析沿用同一個自動主題（冪等）

執行方式：
    cd backend
    python3 tests/test_analyze_survey_multi_question_scope.py
"""

import os

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)

from admin_test_support import GEMINI_CALLS, GEMINI_QUEUE, check, create_app, finish, q, seed_people, seed_topic, user_header  # noqa: E402
import models as m  # noqa: E402
from extensions import db  # noqa: E402
from services.privacy_service import mask_pii  # noqa: E402

app = create_app()
client = app.test_client()

with app.app_context():
    seed_people()
    db.session.add(m.User(user_id=2, user_name="other", email="other@example.com", password_hash="x"))
    seed_topic("career", categories=[("職涯發展", "A1 教育訓練", "m", "c"), ("職涯發展", "A2 升遷制度", "m", "c")])


def classify(text, main, sub):
    q({"segments": [mask_pii(text)]})
    q({"classifications": [{"index": 0, "main_category": main, "sub_category": sub, "secondary_categories": [],
                             "reasoning": "r", "summary": "s", "confidence": 0.9}]})


def make_survey(code, q2_status, user_id=1):
    with app.app_context():
        tpl = m.Survey_Template(
            user_id=user_id, title=f"多題問卷 {code}", access_code=code,
            question_json={"items": [
                {"id": "q1", "type": "short", "title": "對訓練的建議", "question_type": "career", "routing_status": "routed"},
                {"id": "r1", "type": "rating", "title": "滿意度", "max": 5},
                {"id": "q2", "type": "short", "title": "其他想法", "question_type": None, "routing_status": q2_status},
            ]},
        )
        db.session.add(tpl)
        db.session.flush()
        db.session.add_all([
            m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q1": "希望多開訓練課程", "r1": 4, "q2": "希望多辦員工旅遊"}}),
            m.Survey_Response(template_id=tpl.template_id, answer_json={"answers": {"q1": "希望升遷制度更透明", "r1": 5, "q2": "想要更多社團活動"}}),
        ])
        db.session.commit()


def auto_topics():
    with app.app_context():
        return [(t.topic_key, t.auto_scope) for t in m.Topic.query.filter(m.Topic.topic_key.like("auto\\_%", escape="\\")).all()]


def q2_rows(code):
    with app.app_context():
        tpl = m.Survey_Template.query.filter_by(access_code=code).one()
        ids = [r.response_id for r in tpl.responses]
        return m.Response_Classification.query.filter(
            m.Response_Classification.response_id.in_(ids), m.Response_Classification.question_id == "q2",
        ).all()


print("========== A. 第二題需要重新 routing + 自動主題 ==========")
make_survey("AAAAA", "routing_failed")
GEMINI_QUEUE.clear()
classify("希望多開訓練課程", "職涯發展", "A1 教育訓練")
classify("希望升遷制度更透明", "職涯發展", "A2 升遷制度")
q({"question_type": None})  # q2 重新 routing：模型判斷沒有適合主題
q({"categories": [{"main_category": "福利", "sub_category": "員工活動", "definition": "d"}]})  # 自動歸納
classify("希望多辦員工旅遊", "福利", "員工活動")
classify("想要更多社團活動", "福利", "員工活動")
resp = client.post("/api/surveys/AAAAA/analyze", headers=user_header(1))
body = resp.get_json() or {}
check("HTTP 200", resp.status_code == 200)
check("兩題都有分析", sorted(body.get("analyzed_question_ids") or []) == ["q1", "q2"])
check("4 則回答全部分類", body.get("newly_classified_count") == 4)
topics = auto_topics()
check("建立 1 個自動主題", len(topics) == 1)
check("自動主題範圍是字串 user:1（不是上一題回答的 dict）", topics and topics[0][1] == "user:1")
routing_calls = [c for c in GEMINI_CALLS if "question_type" in str(c.get("system_instruction") or "")]
check("q2 routing 呼叫有送出", len(routing_calls) >= 1)
rows = q2_rows("AAAAA")
check("q2 分類結果掛在自動主題的 taxonomy version",
      len(rows) == 2 and all(r.taxonomy_version_id is not None for r in rows)
      and all(r.sub_category == "員工活動" for r in rows))
check("rating 題獨立統計不受影響", any(s.get("question_id") == "r1" for s in (body.get("rating_stats") or []))
      or bool(body.get("rating_stats")))
with app.app_context():
    item = m.Survey_Template.query.filter_by(access_code="AAAAA").one().question_json["items"][2]
    check("q2 routing 結果已記錄", item["routing_status"] == "undetermined")


print("\n========== B. 第二題直接走自動主題（建立時已判斷 undetermined）==========")
make_survey("BBBBB", "undetermined", user_id=2)  # 另一個使用者：自動主題不會沿用 A 的
GEMINI_QUEUE.clear()
del GEMINI_CALLS[:]
classify("希望多開訓練課程", "職涯發展", "A1 教育訓練")
classify("希望升遷制度更透明", "職涯發展", "A2 升遷制度")
q({"categories": [{"main_category": "福利", "sub_category": "員工活動", "definition": "d"}]})
classify("希望多辦員工旅遊", "福利", "員工活動")
classify("想要更多社團活動", "福利", "員工活動")
before = auto_topics()
resp = client.post("/api/surveys/BBBBB/analyze", headers=user_header(2))
body = resp.get_json() or {}
check("HTTP 200", resp.status_code == 200)
check("兩題都有分析", sorted(body.get("analyzed_question_ids") or []) == ["q1", "q2"])
check("q2 兩則回答都有分類", len(q2_rows("BBBBB")) == 2)
check("新增 1 個自動主題，範圍是 user:2", sorted(s for _, s in auto_topics()) == ["user:1", "user:2"])
check("沒有對 q2 重新 routing（undetermined 直接走自動主題）",
      not any("question_type" in str(c.get("system_instruction") or "") for c in GEMINI_CALLS))

GEMINI_QUEUE.clear()
resp = client.post("/api/surveys/BBBBB/analyze", headers=user_header(2))
check("再次分析：冪等，沒有新分類", resp.status_code == 200 and resp.get_json()["newly_classified_count"] == 0)
check("再次分析：沒有多建自動主題", len(auto_topics()) == len(before) + 1)

finish()
