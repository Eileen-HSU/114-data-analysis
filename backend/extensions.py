from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from datetime import datetime
from zoneinfo import ZoneInfo

db = SQLAlchemy()
mail = Mail()
   
def taiwan_now() -> datetime:
    """回傳目前台灣時間（UTC+8，timezone-aware）。
 
    專案內所有需要「建立/更新時間」的欄位一律呼叫此函式，
    不要各自用 datetime.utcnow() + timedelta(hours=8) 之類的寫法，
    以免產生 naive datetime 而在比較/序列化時出錯。
    """
    return datetime.now(ZoneInfo("Asia/Taipei"))