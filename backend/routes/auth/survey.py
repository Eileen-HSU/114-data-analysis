from flask import Blueprint, request, jsonify
from extensions import db
import traceback
import sys
import random
import string
from sqlalchemy import text
# 確保從 models.py 引入你的資料表實體
from models import Survey_Template
survey_bp = Blueprint('survey', __name__)

@survey_bp.route('/api/surveys', methods=['POST'])
def create_survey():
    print("\n[CREATE_SURVEY] ========== 接收到 /api/surveys 請求 ==========")
    print(f"[CREATE_SURVEY] Request Headers: {dict(request.headers)}")
    print(f"[CREATE_SURVEY] Request JSON: {request.json}")
    
    data = request.json
    if not data:
        print("[CREATE_SURVEY] 錯誤：request.json 為空或無法解析")
        return jsonify({"error": "request body 為空或格式錯誤"}), 400
    
    try:
        print(f"[CREATE_SURVEY] 收到的數據: title='{data.get('title')}', questions_count={len(data.get('questions', []))} ")
        
        # 獲取第一個可用的 project_id
        result = db.session.execute(text("SELECT project_id FROM Workspace LIMIT 1"))
        workspace_row = result.fetchone()
        if not workspace_row:
            print("[CREATE_SURVEY] 錯誤：Workspace 表中沒有可用的 project_id")
            return jsonify({"error": "沒有可用的工作區，請先建立工作區"}), 400
        
        project_id = workspace_row[0]
        print(f"[CREATE_SURVEY] 已取得 project_id: {project_id}")
        
        # 自動產生一組 5 碼的隨機邀請碼 (對應 access_code)
        generated_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        print(f"[CREATE_SURVEY] 產生的 access_code: {generated_code}")
        
        # 將前端傳來的 title, description, questions 全部包進 question_json
        survey_content = {
            "title": data.get('title'),
            "description": data.get('description'),
            "items": data.get('questions')
        }

        new_template = Survey_Template(
            project_id=project_id,  # 使用有效的 project_id
            access_code=generated_code,
            question_json=survey_content
            # share_uuid 會自動生成，template_id 資料庫會自動遞增
        )
        
        print("[CREATE_SURVEY] 準備插入資料庫...")
        db.session.add(new_template)
        db.session.commit()
        print(f"[CREATE_SURVEY] ✓ 成功插入資料庫，template_id={new_template.template_id}")
        
        return jsonify({
            "message": "問卷建立成功", 
            "access_code": generated_code
        }), 201
        
    except Exception as e:
        print(f"[CREATE_SURVEY] ✗ 寫入失敗: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": str(e)}), 500