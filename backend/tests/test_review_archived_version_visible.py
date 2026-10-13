#!/usr/bin/env python
"""
回歸：發布新版分類架構後，舊版本（archived）底下還在待審的分類、以及「重新開啟審核」的分類，
不能從人工待處理清單與待審數字消失；只有「版本還是草稿／審核中」的暫定分類才維持隱藏。

執行：cd backend && JWT_SECRET_KEY=t python3 tests/test_review_archived_version_visible.py
"""
from admin_test_support import admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic, seed_upload_batch
import models as m
from extensions import db
from services import review_service

app = create_app()
client = app.test_client()
H = admin_header(1)

with app.app_context():
    seed_people()
    v1 = seed_topic("t_arch", status="published", version_number=1)
    ids = seed_upload_batch("b-arch", [f"回答{i}" for i in range(4)], question_type="t_arch")
    pending = seed_classification(ids[0], "b-arch", "回答0", "Main A", "A1 Original", version_id=v1, needs_human_review=True)
    confirmed = seed_classification(ids[1], "b-arch", "回答1", "Main A", "A1 Original", version_id=v1, review_status="confirmed")
    v_draft = seed_topic("t_draft_only", status="draft", version_number=1)
    ids2 = seed_upload_batch("b-draft", ["草稿主題的回答"], question_type="t_draft_only")
    draft_row = seed_classification(ids2[0], "b-draft", "草稿主題的回答", "Main A", "A1 Original", version_id=v_draft, needs_human_review=True)


def listing():
    d = client.get("/api/admin/ai/classifications?state=pending_review", headers=H).get_json()
    return [i["classification_id"] for i in d["classifications"]], d["status_counts"]["pending_review"]


def overview_total():
    return client.get("/api/admin/ai/overview", headers=H).get_json()["needs_person"]["other_pending"]


print("========== 發布前 ==========")
ids_now, count_now = listing()
check("已發布版本底下的待審：在待處理清單", pending in ids_now)
check("草稿版本底下的暫定分類：維持隱藏", draft_row not in ids_now)

print("========== 發布新版（舊版變 archived）==========")
with app.app_context():
    old = db.session.get(m.Taxonomy_Version, v1)
    old.status = "archived"
    seed_topic("t_arch", status="published", version_number=2)
    db.session.commit()
ids_now, count_now = listing()
check("舊版本變 archived 後：待審分類仍在待處理清單", pending in ids_now)
check("舊版本 archived：待審計數沒有變成 0", count_now >= 1)
check("草稿版本底下的暫定分類：仍然隱藏", draft_row not in ids_now)

print("========== 重新開啟「已確認」==========")
with app.app_context():
    review_service.reopen_review(confirmed, 1, "測試")
ids_now, count_now = listing()
check("archived 版本底下重新開啟的分類：出現在待處理", confirmed in ids_now)
resp = client.get("/api/admin/ai/classifications?state=confirmed", headers=H).get_json()
check("重新開啟後：不再留在已確認", confirmed not in [i["classification_id"] for i in resp["classifications"]])

finish()
