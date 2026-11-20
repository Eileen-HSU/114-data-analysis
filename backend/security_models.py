"""CSP 違規回報彙總（相同違規合併計數，只存網域與路徑，不存查詢參數）。"""

from extensions import db


class CspViolation(db.Model):
    __tablename__ = "Csp_Violation"

    violation_key = db.Column(db.String(64), primary_key=True)
    directive = db.Column(db.String(40), nullable=False)
    blocked = db.Column(db.String(200), nullable=False)
    document_path = db.Column(db.String(200), nullable=False, default="")
    hit_count = db.Column(db.Integer, nullable=False, default=1)
    first_seen = db.Column(db.DateTime, nullable=False)
    last_seen = db.Column(db.DateTime, nullable=False, index=True)
