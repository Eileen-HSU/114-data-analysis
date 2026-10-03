#!/usr/bin/env python
"""
新類別候選 → 合併到既有類別：專用 merge-targets API。

涵蓋：
    1. 有 published 版本的主題：用目前 published 版，回傳 topic / version / categories，版本一致
    2. 採用新類別後（舊版 archived、新版 published）：目標用新版；仍綁舊版的回答
       valid_rows 反映哪些類別對它有效，rows_on_other_version 標示出來
    3. 同一組回答綁定不同版本：bound_versions_consistent=False、候選列表標 version_mismatch，
       合併時逐筆驗證（有效的合併、無效的 skipped 並帶 taxonomy_version_id）
    4. 尚未發布的自動主題：用最新 draft（target_source=provisional_draft、has_published=False）
    5. 沒有可用版本（關閉開放模式、只有 draft）：退回綁定版本（bound_fallback），不是空清單
    6. 限定群組只統計該群組；不傳群組統計整個主題
    7. 防呆：缺 topic -> 400、找不到主題 -> 404、非 admin -> 401/403
    8. 既有行為不變：GET /api/classification/<id>/review 的 taxonomy_options 仍是綁定版本清單

執行方式：
    cd backend
    python3 tests/test_new_category_merge_targets.py
"""

import os

from admin_test_support import (
    admin_header, check, create_app, finish, seed_classification, seed_people, seed_topic, seed_upload_batch,
)
import models as m
from extensions import db

os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)  # 預設開放模式

app = create_app()
client = app.test_client()

BASE = "/api/admin/ai/new-categories"


def targets(topic, main=None, sub=None, headers=None):
    params = {"topic": topic} if topic else {}
    if main is not None:
        params["main_category"] = main
    if sub is not None:
        params["sub_category"] = sub
    return client.get(f"{BASE}/merge-targets", query_string=params, headers=headers or admin_header(1))


def candidate(batch, text, main, sub, topic, version_id):
    ids = seed_upload_batch(batch, [text], question_type=topic)
    return seed_classification(ids[0], batch, text, main, sub, version_id=version_id, status="new_category")


def sub_set(body):
    return {c["sub_category"] for c in body["categories"]}


def valid_rows(body, sub):
    return next(c["valid_rows"] for c in body["categories"] if c["sub_category"] == sub)


with app.app_context():
    seed_people()

print("========== 1. published 主題 ==========")
with app.app_context():
    pub_v1 = seed_topic("pub_topic", categories=[("Main A", "A1 Original", "m", "c"), ("Main B", "B1 Candidate", "m", "c")])
    cid1 = candidate("b-pub", "加班太多", "Main A", "工時過長", "pub_topic", pub_v1)
resp = targets("pub_topic", "Main A", "工時過長")
body = resp.get_json()
check("200", resp.status_code == 200)
check("回傳 topic_key / topic_title", body["topic_key"] == "pub_topic" and body["topic_title"] == "Topic pub_topic")
check("回傳 version_id / version_number / version_status",
      body["version_id"] == pub_v1 and body["version_number"] == 1 and body["version_status"] == "published")
check("categories = published 版本全部類別", sub_set(body) == {"A1 Original", "B1 Candidate"} and body["category_count"] == 2)
check("target_source=published、has_published", body["target_source"] == "published" and body["has_published"] is True)
check("單一綁定版本 -> 版本一致、沒有其他版本的回答",
      body["bound_versions_consistent"] is True and body["rows_on_other_version"] == 0 and body["row_total"] == 1)
check("每個類別對這一筆都有效", all(c["valid_rows"] == 1 for c in body["categories"]))
check("不是自動主題", body["is_auto_topic"] is False)

print("\n========== 8. 既有審核 taxonomy_options 不變 ==========")
state = client.get(f"/api/classification/{cid1}/review", headers=admin_header(1)).get_json()
check("review 的 taxonomy_options 仍是綁定版本清單",
      {o["sub_category"] for o in state["taxonomy_options"] if not o["proposed"]} == {"A1 Original", "B1 Candidate"})

print("\n========== 2. 採用後：新版 published、舊版 archived，回答仍綁舊版 ==========")
with app.app_context():
    old = db.session.get(m.Taxonomy_Version, pub_v1)
    old.status = "archived"
    db.session.commit()
    pub_v2 = seed_topic("pub_topic", version_number=2, categories=[
        ("Main A", "A1 Original", "m", "c"), ("Main B", "B1 Candidate", "m", "c"), ("Main C", "C1 Adopted", "m", "c")])
body = targets("pub_topic", "Main A", "工時過長").get_json()
check("目標改用目前 published（v2）", body["version_id"] == pub_v2 and body["version_number"] == 2 and body["version_status"] == "published")
check("列出新版全部類別（含採用的）", sub_set(body) == {"A1 Original", "B1 Candidate", "C1 Adopted"})
check("綁定舊版的回答被標示（rows_on_other_version=1）", body["rows_on_other_version"] == 1)
check("bound_versions 列出舊版（v1 archived，1 筆）",
      [(b["version_number"], b["version_status"], b["row_count"]) for b in body["bound_versions"]] == [(1, "archived", 1)])
check("舊版就有的類別對這筆有效；新採用的類別對這筆無效（valid_rows=0）",
      valid_rows(body, "A1 Original") == 1 and valid_rows(body, "C1 Adopted") == 0)
resp = client.post(f"{BASE}/merge", headers=admin_header(1), json={
    "topic_key": "pub_topic", "main_category": "Main A", "sub_category": "工時過長", "target_sub_category": "C1 Adopted"})
body = resp.get_json()
check("合併到對該筆無效的類別：逐筆驗證 -> 該筆 skipped（INVALID_CATEGORY），帶綁定版本",
      resp.status_code == 200 and body["merged_count"] == 0
      and body["skipped"][0]["code"] == "INVALID_CATEGORY" and body["skipped"][0]["taxonomy_version_id"] == pub_v1)
with app.app_context():
    check("被略過的仍是待處理", db.session.get(m.Response_Classification, cid1).review_status == "pending_review")
resp = client.post(f"{BASE}/merge", headers=admin_header(1), json={
    "topic_key": "pub_topic", "main_category": "Main A", "sub_category": "工時過長", "target_sub_category": "A1 Original"})
check("合併到有效類別仍成功（既有 merge 行為不變）", resp.status_code == 200 and resp.get_json()["merged_ids"] == [cid1])

print("\n========== 3. 同一組回答綁定不同版本 ==========")
with app.app_context():
    mm_a = candidate("b-mm-a", "薪水偏低", "Main A", "薪資不透明", "pub_topic", pub_v1)  # 舊版
    mm_b = candidate("b-mm-b", "薪水不公開", "Main A", "薪資不透明", "pub_topic", pub_v2)  # 新版
body = targets("pub_topic", "Main A", "薪資不透明").get_json()
check("bound_versions_consistent=False", body["bound_versions_consistent"] is False)
check("bound_versions 兩個版本各 1 筆",
      [(b["version_number"], b["row_count"]) for b in body["bound_versions"]] == [(1, 1), (2, 1)])
check("rows_on_other_version = 1（綁舊版那筆）", body["rows_on_other_version"] == 1 and body["row_total"] == 2)
check("valid_rows：A1 兩筆都有效、C1 只有新版那筆有效", valid_rows(body, "A1 Original") == 2 and valid_rows(body, "C1 Adopted") == 1)
items = client.get(BASE, headers=admin_header(1)).get_json()["items"]
item = next(i for i in items if i["sub_category"] == "薪資不透明")
check("候選列表標示 version_mismatch 與各綁定版本", item["version_mismatch"] is True and item["taxonomy_version_ids"] == sorted([pub_v1, pub_v2]))
resp = client.post(f"{BASE}/merge", headers=admin_header(1), json={
    "topic_key": "pub_topic", "main_category": "Main A", "sub_category": "薪資不透明", "target_sub_category": "C1 Adopted"})
body = resp.get_json()
check("版本不一致時逐筆驗證：新版那筆合併、舊版那筆 skipped",
      body["merged_ids"] == [mm_b] and [s["classification_id"] for s in body["skipped"]] == [mm_a])
with app.app_context():
    check("合併成功那筆是 modified 到 C1 Adopted",
          db.session.get(m.Response_Classification, mm_b).final_sub_category == "C1 Adopted")
    check("skipped 那筆維持待處理", db.session.get(m.Response_Classification, mm_a).review_status == "pending_review")

print("\n========== 6. 群組 / 主題範圍 ==========")
with app.app_context():
    candidate("b-other-g", "主管很兇", "Main B", "管理風格", "pub_topic", pub_v2)
group_body = targets("pub_topic", "Main B", "管理風格").get_json()
topic_body = targets("pub_topic").get_json()
check("限定群組：只統計該群組（1 筆）", group_body["row_total"] == 1 and group_body["bound_versions_consistent"] is True)
check("不傳群組：統計主題內全部待處理候選（>=2 組、版本不一致）",
      topic_body["row_total"] >= 2 and topic_body["bound_versions_consistent"] is False)

print("\n========== 4. 尚未發布的自動主題 ==========")
with app.app_context():
    auto_v = seed_topic("auto_demo", status="draft", categories=[("工作環境", "辦公設備", "m", "c"), ("工作環境", "休息空間", "m", "c")])
    candidate("b-auto", "想要按摩椅", "工作環境", "放鬆設施", "auto_demo", auto_v)
body = targets("auto_demo", "工作環境", "放鬆設施").get_json()
check("使用最新 draft 版本", body["version_id"] == auto_v and body["version_status"] == "draft" and body["target_source"] == "provisional_draft")
check("has_published=False、is_auto_topic=True", body["has_published"] is False and body["is_auto_topic"] is True)
check("categories = draft 的類別", sub_set(body) == {"辦公設備", "休息空間"})
with app.app_context():
    seed_topic("auto_demo", status="in_review", version_number=2, categories=[
        ("工作環境", "辦公設備", "m", "c"), ("工作環境", "休息空間", "m", "c"), ("工作環境", "餐飲補給", "m", "c")])
    newer = m.Taxonomy_Version.query.filter_by(topic_key="auto_demo", version_number=2).one().version_id
body = targets("auto_demo", "工作環境", "放鬆設施").get_json()
check("有較新的 in_review 版本 -> 用最新那版", body["version_id"] == newer and body["version_status"] == "in_review"
      and "餐飲補給" in sub_set(body))
check("該回答綁舊 draft：新類別對它無效、舊類別有效",
      valid_rows(body, "餐飲補給") == 0 and valid_rows(body, "辦公設備") == 1 and body["rows_on_other_version"] == 1)

print("\n========== 5. 沒有可用版本：退回綁定版本 ==========")
os.environ["OPEN_CLASSIFICATION_ENABLED"] = "0"
try:
    body = targets("auto_demo", "工作環境", "放鬆設施").get_json()
finally:
    os.environ.pop("OPEN_CLASSIFICATION_ENABLED", None)
check("關閉開放模式且沒有 published -> bound_fallback（綁定版本，非空清單）",
      body["target_source"] == "bound_fallback" and body["version_id"] == auto_v and body["category_count"] == 2)

print("\n========== 7. 防呆 ==========")
resp = targets(None)
check("缺 topic -> 400 TOPIC_REQUIRED", resp.status_code == 400 and resp.get_json()["code"] == "TOPIC_REQUIRED")
resp = targets("no_such_topic")
check("找不到主題 -> 404 TOPIC_NOT_FOUND", resp.status_code == 404 and resp.get_json()["code"] == "TOPIC_NOT_FOUND")
resp = client.get(f"{BASE}/merge-targets", query_string={"topic": "pub_topic"})
check("沒帶 token -> 401/403", resp.status_code in (401, 403))

finish()
