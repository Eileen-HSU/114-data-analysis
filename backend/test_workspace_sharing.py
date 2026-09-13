"""Run with: python -m unittest test_workspace_sharing -v"""
import os
import unittest
from datetime import datetime
os.environ.setdefault("JWT_SECRET_KEY", "sharing-test-only")
import jwt
from flask import Flask
from extensions import db
from models import User, Workspace, Chat_History
from routes.workspaces.workspace import workspace_bp
from routes.chats.chat import chat_bp

class WorkspaceSharingTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
        db.init_app(self.app)
        self.app.register_blueprint(workspace_bp)
        self.app.register_blueprint(chat_bp)
        self.context = self.app.app_context()
        self.context.push()
        db.metadata.create_all(bind=db.engine, tables=[User.__table__, Workspace.__table__, Chat_History.__table__])
        db.session.add_all([
            User(user_id=1, user_name="Owner", email="owner@example.test", password_hash="x"),
            User(user_id=2, user_name="Other", email="other@example.test", password_hash="x"),
        ])
        db.session.add_all([
            Workspace(project_id=1, user_id=1, project_name="Shared chat"),
            Workspace(project_id=2, user_id=1, project_name="Private chat"),
        ])
        db.session.add_all([
            Chat_History(project_id=1, sender_type="user", message_content="Question", created_at=datetime(2026, 1, 1)),
            Chat_History(project_id=1, sender_type="ai", message_content="Answer", created_at=datetime(2026, 1, 2)),
            Chat_History(project_id=2, sender_type="user", message_content="Private"),
        ])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def auth(self, user_id=1):
        return {"Authorization": "Bearer " + jwt.encode({"user_id": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")}

    def share(self):
        response = self.client.post("/api/workspace/1/share", headers=self.auth())
        self.assertEqual(response.status_code, 200)
        return response.json["share_code"]

    def test_owner_only_and_stable_link(self):
        self.assertEqual(self.client.post("/api/workspace/1/share").status_code, 401)
        self.assertEqual(self.client.post("/api/workspace/1/share", headers=self.auth(2)).status_code, 404)
        code = self.share()
        self.assertEqual(code, self.share())
        self.assertEqual(len(code), 10)

    def test_anonymous_read_is_scoped_and_not_cached(self):
        code = self.share()
        response = self.client.get("/api/public/workspace/" + code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["content"] for m in response.json["messages"]], ["Question", "Answer"])
        self.assertEqual(set(response.json), {"project_name", "messages"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_invalid_and_deleted_links(self):
        self.assertEqual(self.client.get("/api/public/workspace/invalid").status_code, 404)
        code = self.share()
        db.session.get(Workspace, 1).is_deleted = True
        db.session.commit()
        self.assertEqual(self.client.get("/api/public/workspace/" + code).status_code, 404)

    def test_link_cannot_authorize_writes(self):
        code = self.share()
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)("/api/public/workspace/" + code).status_code, 405)
        payload = {"project_id": 1, "sender_type": "user", "message_content": "Unauthorized"}
        self.assertEqual(self.client.post("/api/chat/history", json=payload).status_code, 401)
        self.assertEqual(self.client.post("/api/chat/history", json=payload, headers={"Authorization": "Bearer " + code}).status_code, 401)
        self.assertEqual(self.client.post("/api/chat/history", json=payload, headers=self.auth(2)).status_code, 404)
        self.assertEqual(self.client.post("/api/chat/1/files").status_code, 401)
        self.assertEqual(self.client.put("/api/workspace/1", json={"project_name": "Changed"}).status_code, 401)
        self.assertEqual(Chat_History.query.count(), 3)

if __name__ == "__main__":
    unittest.main()
