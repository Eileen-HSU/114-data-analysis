from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from datetime import datetime
from zoneinfo import ZoneInfo

db = SQLAlchemy()
mail = Mail()

def taiwan_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Taipei"))
