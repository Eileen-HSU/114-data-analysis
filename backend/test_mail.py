import resend

# 填入你的 Key
resend.api_key = "re_8iZoHx8F_6trPstNJy" 

try:
    r = resend.Emails.send({
        "from": "onboarding@resend.dev",
        "to": "bingq7943@gmail.com",
        "subject": "本地測試 Resend",
        "html": "<strong>這是一封從本地發出的測試信！</strong>"
    })
    print("發送成功！", r)
except Exception as e:
    print("發送失敗：", e)