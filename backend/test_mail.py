from app import app, mail
from flask_mail import Message

with app.app_context():
    try:
        msg = Message(
            subject='測試信件',
            recipients=['bingq7943@gmail.com'], 
            body='如果收到這封信，代表 Mail 設定正確！'
        )
        mail.send(msg)
        print("✅ 寄信成功！")
    except Exception as e:
        print(f"❌ 寄信失敗：{e}")