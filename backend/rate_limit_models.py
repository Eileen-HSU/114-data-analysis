"""頻率限制計數表（固定時間窗；存 MySQL，不引入 Redis）。"""

from extensions import db


class RateLimitCounter(db.Model):
    __tablename__ = "Rate_Limit_Counter"

    # key 內含：scope + 識別雜湊 + 時間窗起點，例如 login:acct:<hash>:<window>
    counter_key = db.Column(db.String(190), primary_key=True)
    hit_count = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
