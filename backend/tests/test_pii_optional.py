#!/usr/bin/env python
"""個資最小化：電話／公司／性別為選填；未填存 NULL，不存空字串。"""

from admin_test_support import check, create_app, finish, user_header
import models as m
from extensions import db
from routes.auth.register import register_bp
from routes.users.profile import profile_bp

app = create_app()
for bp in (register_bp, profile_bp):
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
client = app.test_client()

check("模型：三個個資欄位可為 NULL",
      all(getattr(m.UserProfile, c).nullable for c in ("phone_number", "company_name", "gender")))

# 只給姓名／信箱／密碼也能註冊
r = client.post("/api/register", json={"user_name": "小明", "email": "min@example.com", "password": "abc12345"})
check("只填姓名/信箱/密碼可註冊", r.status_code == 201)
uid = (r.get_json() or {}).get("user_id")
with app.app_context():
    p = db.session.query(m.UserProfile).filter_by(user_id=uid).one()
    check("未填欄位存 NULL", p.phone_number is None and p.company_name is None and p.gender is None)

# 空白字串也視為未填
r = client.post("/api/register", json={"user_name": "小華", "email": "hua@example.com", "password": "abc12345",
                                        "phone_number": "  ", "gender": "", "company_name": " "})
check("空白字串可註冊", r.status_code == 201)
with app.app_context():
    p = db.session.query(m.UserProfile).filter_by(user_id=r.get_json()["user_id"]).one()
    check("空白字串存 NULL", p.phone_number is None and p.company_name is None and p.gender is None)

# 仍然填寫時照存（含「不願透露」）
r = client.post("/api/register", json={"user_name": "小美", "email": "mei@example.com", "password": "abc12345",
                                        "phone_number": " 0912345678 ", "gender": "不願透露", "company_name": "ACME"})
check("有填時可註冊", r.status_code == 201)
uid3 = r.get_json()["user_id"]
with app.app_context():
    p = db.session.query(m.UserProfile).filter_by(user_id=uid3).one()
    check("有填時照存並去空白", p.phone_number == "0912345678" and p.gender == "不願透露" and p.company_name == "ACME")

# 必填仍然有效
check("缺姓名 -> 400", client.post("/api/register", json={"email": "x@example.com", "password": "abc12345"}).status_code == 400)
check("缺密碼 -> 400", client.post("/api/register", json={"user_name": "x", "email": "x@example.com"}).status_code == 400)

# 個人資料更新：清空 -> NULL
r = client.put(f"/api/profile/{uid3}", json={"phone_number": "", "company_name": "  ", "gender": "女"},
               headers=user_header(uid3))
check("更新個人資料 200", r.status_code == 200)
with app.app_context():
    p = db.session.query(m.UserProfile).filter_by(user_id=uid3).one()
    check("清空存 NULL、其他照存", p.phone_number is None and p.company_name is None and p.gender == "女")
r = client.get(f"/api/profile/{uid3}", headers=user_header(uid3))
body = r.get_json() or {}
check("讀取時 NULL 以空字串回傳", r.status_code == 200 and body.get("phone_number") == "" and body.get("gender") == "女")

finish()
