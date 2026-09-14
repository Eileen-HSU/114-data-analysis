"""English API copy and registration regression tests; no external services used."""
import ast
import os
import re
import unittest
from pathlib import Path
from flask import Flask
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.mysql import MEDIUMTEXT

@compiles(MEDIUMTEXT, "sqlite")
def compile_mediumtext_for_test(element, compiler, **kw):
    return "TEXT"

from extensions import db
from models import User, UserProfile
from routes.auth.register import register_bp, is_valid_password

os.environ.setdefault("JWT_SECRET_KEY", "english-interface-regression-test-secret-2026")
HAN = re.compile(r"[\u3400-\u9fff]")

class EnglishMessagesTests(unittest.TestCase):
    def test_route_response_copy_is_english(self):
        for file in (Path(__file__).parent / "routes").rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "jsonify":
                    continue
                for argument in node.args:
                    for value in ast.walk(argument):
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            self.assertIsNone(HAN.search(value.value), f"{file.name}:{value.lineno}: {value.value}")

    def test_password_help_matches_validator(self):
        self.assertTrue(is_valid_password("letters1"))  # Uppercase is not required by the API.
        self.assertTrue(is_valid_password("LongerPassword123"))
        for value in ("short1", "12345678", "lettersOnly"):
            self.assertFalse(is_valid_password(value))

    def test_registration_errors_are_english(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
        db.init_app(app)
        app.register_blueprint(register_bp)
        with app.app_context():
            db.metadata.create_all(bind=db.engine, tables=[User.__table__, UserProfile.__table__])
            client = app.test_client()
            base = dict(user_name="Test", email="test@example.com", phone_number="0912345678", gender="女", password="short1")
            for body, expected in [({}, 400), ({"email": "test@example.com"}, 400), ({**base, "email": "invalid"}, 400), (base, 400)]:
                response = client.post("/api/register", json=body)
                self.assertEqual(response.status_code, expected)
                self.assertTrue(response.json["error"])
                self.assertIsNone(HAN.search(response.json["error"]))
            response = client.post("/api/register", json={**base, "password": "letters1"})
            self.assertEqual(response.status_code, 201)
            self.assertIn("Account created successfully", response.json["message"])
            duplicate = client.post("/api/register", json={**base, "password": "letters1"})
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(duplicate.json["error"], "This email address is already registered")
            db.session.remove()

if __name__ == "__main__":
    unittest.main()
