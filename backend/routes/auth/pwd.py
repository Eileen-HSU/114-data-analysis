from flask import Blueprint, request, jsonify
from flask_mail import Message
from extensions import mail
import random

pwd_bp = Blueprint('pwd', __name__)

otp_storage = {}

@pwd_bp.route('/api/send-otp', methods=['POST'])
def send_otp():
    data = request.get_json()
    email = data.get('email')
    
    otp = str(random.randint(100000, 999999))
    otp_storage[email] = otp
    
    try:
        msg = Message(
            subject="【DataAnalysis】安全性驗證碼",
            recipients=[email],
            body=f"您正在嘗試修改密碼，您的驗證碼為：{otp}\n請於 10 分鐘內完成驗證。如果這不是您本人的操作，請忽略此信。"
        )
        mail.send(msg)
        return jsonify({"message": "驗證碼已送出"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500