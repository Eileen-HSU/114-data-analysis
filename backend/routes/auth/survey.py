from flask import Blueprint, request, jsonify
from extensions import db
import traceback
import sys
import random
import string
from sqlalchemy import text
from models import Survey_Template, Survey_Response
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
    if not data.get('title') or not isinstance(data.get('questions'), list):
        return jsonify({"error": "缺少問卷標題或題目資料"}), 400
    
    try:
        print(f"[CREATE_SURVEY] 收到的數據: title='{data.get('title')}', questions_count={len(data.get('questions', []))} ")
        
        # 問卷可以先獨立建立；若有 Workspace，再附上第一個可用的 project_id。
        project_id = None
        try:
            result = db.session.execute(text("SELECT project_id FROM Workspace LIMIT 1"))
            workspace_row = result.fetchone()
            if workspace_row:
                project_id = workspace_row[0]
                print(f"[CREATE_SURVEY] 已取得 project_id: {project_id}")
            else:
                print("[CREATE_SURVEY] Workspace 表中沒有資料，將以 project_id=None 建立問卷")
        except Exception as workspace_error:
            print(f"[CREATE_SURVEY] 無法取得 Workspace project_id，將略過: {workspace_error}")
        
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
            project_id=project_id,
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
            "access_code": generated_code,
            "template_id": new_template.template_id
        }), 201
        
    except Exception as e:
        print(f"[CREATE_SURVEY] ✗ 寫入失敗: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@survey_bp.route('/api/surveys/<access_code>/responses', methods=['POST'])
def submit_survey_response(access_code):
    data = request.get_json()
    if not data or not isinstance(data.get('answers'), dict):
        return jsonify({"error": "缺少問卷答案資料"}), 400

    try:
        survey = Survey_Template.query.filter_by(access_code=access_code.upper()).first()
        if not survey:
            return jsonify({"error": "找不到此邀請碼對應的問卷"}), 404

        response = Survey_Response(
            template_id=survey.template_id,
            answer_json=data.get('answers')
        )
        db.session.add(response)
        db.session.commit()

        return jsonify({
            "message": "問卷送出成功",
            "response_id": response.response_id
        }), 201

    except Exception as e:
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
