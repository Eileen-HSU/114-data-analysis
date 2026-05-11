import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import axios from "axios";
import { apiUrl } from "../../lib/api";
import "./survey.css";


const QUESTION_TYPES = [
  { value: "short", label: "短答題", icon: "ri-text" },
  { value: "long", label: "詳答題", icon: "ri-align-left" },
  { value: "rating", label: "評分題 0-5", icon: "ri-star-line" },
  { value: "single", label: "單選題", icon: "ri-radio-button-line" },
  { value: "multiple", label: "複選題", icon: "ri-checkbox-multiple-line" },
];

function newQuestion(type = "short") {
  return {
    id: crypto.randomUUID(),
    type,
    title: "",
    required: true,
    options: type === "single" || type === "multiple" ? ["選項 1", "選項 2"] : [],
  };
}

function generateCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from({ length: 6 }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
}

export default function CreateSurveyPage() {
  const navigate = useNavigate();
  const { isLoggedIn, user } = useAuth();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [questions, setQuestions] = useState([
    newQuestion("short") // 預設一題進行對標測試
  ]);
  const [error, setError] = useState("");
  const [generatedCode, setGeneratedCode] = useState("");
  const [copied, setCopied] = useState(false);

  const typeMap = useMemo(() => Object.fromEntries(QUESTION_TYPES.map((item) => [item.value, item])), []);

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div className="survey-page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <LoginRequiredModal
            message="請先登入後再建立問卷。"
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/survey")}
          />
        </div>
      </>
    );
  }

  const updateQuestion = (id, patch) => {
    setQuestions((prev) =>
      prev.map((q) => {
        if (q.id !== id) return q;
        const next = { ...q, ...patch };
        if (patch.type === "single" || patch.type === "multiple") {
          next.options = q.options?.length ? q.options : ["選項 1", "選項 2"];
        } else if (patch.type) {
          next.options = [];
        }
        return next;
      })
    );
  };

  const updateOption = (questionId, optionIndex, value) => {
    setQuestions((prev) =>
      prev.map((q) =>
        q.id === questionId
          ? { ...q, options: q.options.map((option, index) => (index === optionIndex ? value : option)) }
          : q
      )
    );
  };

  const addOption = (questionId) => {
    setQuestions((prev) =>
      prev.map((q) => (q.id === questionId ? { ...q, options: [...q.options, `選項 ${q.options.length + 1}`] } : q))
    );
  };

  const removeOption = (questionId, optionIndex) => {
    setQuestions((prev) =>
      prev.map((q) =>
        q.id === questionId && q.options.length > 2
          ? { ...q, options: q.options.filter((_, index) => index !== optionIndex) }
          : q
      )
    );
  };

  const duplicateQuestion = (question) => {
    setQuestions((prev) => {
      const index = prev.findIndex((q) => q.id === question.id);
      const clone = { ...question, id: crypto.randomUUID(), title: `${question.title}（複本）` };
      return [...prev.slice(0, index + 1), clone, ...prev.slice(index + 1)];
    });
  };

  const validate = () => {
    if (!title.trim()) return "請輸入問卷標題。";
    if (questions.some((q) => !q.title.trim())) return "每個題目都需要填寫題目文字。";
    if (questions.some((q) => (q.type === "single" || q.type === "multiple") && q.options.some((option) => !option.trim()))) {
      return "選擇題的每個選項都需要填寫。";
    }
    return "";
  };

  const handleSaveSurvey = async (e) => {
    if (e) e.preventDefault();

    // 1. 驗證標題
    const validationMessage = validate();
    if (validationMessage) {
      setError(validationMessage);
      return;
    }

    try {
      // 2. 封裝要對象 Aiven 資料庫 question_json 的 payload
      const payload = {
        title: title.trim(),
        description: description.trim(),
        questions: questions.map((q) => ({
          ...q,
          title: q.title.trim(),
          options: q.options.map((opt) => opt.trim()),
        })),
        user_id: user?.user_id
      };

      console.log("[FRONTEND] 🚀 準備發送數據至 Aiven...", payload);

      // 3. 發送請求到後端 Render 部署的 /api/surveys
      const response = await axios.post(apiUrl("/api/surveys"), payload);

      if (response.status === 201 || response.status === 200) {
        console.log("[FRONTEND] ✓ 成功存入 Aiven:", response.data);
        
        // 4. 將後端生成的邀請碼顯示在畫面上
        const accessCode = response.data.access_code;
        const savedSurvey = {
          id: response.data.template_id || `survey-${Date.now()}`,
          title: payload.title,
          description: payload.description,
          questions: payload.questions,
          code: accessCode,
          createdAt: new Date().toISOString().slice(0, 10),
          responses: [],
          ownerId: user?.user_id,
          ownerEmail: user?.email,
        };
        const storedSurveys = JSON.parse(localStorage.getItem("surveys") || "{}");
        storedSurveys[accessCode] = savedSurvey;
        localStorage.setItem("surveys", JSON.stringify(storedSurveys));
        setGeneratedCode(accessCode);
        setError("");
      }
    } catch (error) {
      console.error("[FRONTEND] ✗ 存入失敗:", error);
      alert("資料庫寫入失敗！請確認後端已開啟並連線至 Aiven。");
    }
  };

  return (
    <>
      <Navbar />
      <main className="create-survey-page">
        <div className="create-survey-header">
          <div className="container">
            <div className="d-flex align-items-center gap-3">
              <a href="/survey" style={{ color: "var(--slate-500)", fontWeight: 700, textDecoration: "none" }}>
                <i className="ri-arrow-left-line"></i> 返回問卷中心
              </a>
              <span style={{ color: "var(--slate-300)" }}>|</span>
              <span style={{ fontWeight: 800, color: "var(--slate-800)" }}>建立問卷</span>
            </div>
          </div>
        </div>

        <div className="create-survey-body">
          <section className="survey-meta-card">
            <div className="survey-meta-title">
              <div className="survey-meta-icon"><i className="ri-file-text-line"></i></div>
              問卷資訊
            </div>
            <div className="mb-3">
              <label className="auth-label">問卷標題 <span style={{ color: "#ef4444" }}>*</span></label>
              <input className="survey-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：產品滿意度調查" />
            </div>
            <div>
              <label className="auth-label">問卷說明</label>
              <textarea className="survey-input survey-textarea" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="補充填答說明、用途或注意事項" maxLength={500} />
            </div>
          </section>

          {questions.map((question, index) => (
            <section className="question-card" key={question.id}>
              <div className="question-card-header">
                <div className="question-number">{index + 1}</div>
                <select className="question-type-select" value={question.type} onChange={(e) => updateQuestion(question.id, { type: e.target.value })}>
                  {QUESTION_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>{type.label}</option>
                  ))}
                </select>
                <label className="question-required-toggle ms-auto me-2" style={{ cursor: "pointer" }}>
                  <input type="checkbox" checked={question.required} onChange={(e) => updateQuestion(question.id, { required: e.target.checked })} />
                  <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 700, color: "var(--slate-500)" }}>必填</span>
                </label>
                <button className="question-delete-btn" onClick={() => duplicateQuestion(question)} title="複製題目" type="button">
                  <i className="ri-file-copy-line"></i>
                </button>
                <button className="question-delete-btn" onClick={() => setQuestions((prev) => (prev.length === 1 ? prev : prev.filter((q) => q.id !== question.id)))} title="刪除題目" type="button">
                  <i className="ri-delete-bin-line"></i>
                </button>
              </div>

              <input className="survey-input" value={question.title} onChange={(e) => updateQuestion(question.id, { title: e.target.value })} placeholder={`題目 ${index + 1}`} />

              {(question.type === "single" || question.type === "multiple") && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
                  {question.options.map((option, optionIndex) => (
                    <div className="d-flex gap-2" key={optionIndex}>
                      <input className="survey-input" value={option} onChange={(e) => updateOption(question.id, optionIndex, e.target.value)} />
                      <button className="question-delete-btn" onClick={() => removeOption(question.id, optionIndex)} type="button">
                        <i className="ri-close-line"></i>
                      </button>
                    </div>
                  ))}
                  <button className="btn btn-outline-secondary" onClick={() => addOption(question.id)} type="button" style={{ alignSelf: "flex-start" }}>
                    <i className="ri-add-line me-1"></i>新增選項
                  </button>
                </div>
              )}

              <div className="q-preview" style={{ marginTop: 14 }}>
                <i className={`${typeMap[question.type].icon} me-1`}></i>
                {typeMap[question.type].label}
              </div>
            </section>
          ))}

          <button className="add-question-area" onClick={() => setQuestions((prev) => [...prev, newQuestion()])} type="button">
            <i className="ri-add-circle-line"></i>
            <p>新增題目</p>
          </button>

          {error && <p style={{ color: "#ef4444", fontWeight: 800 }}>{error}</p>}
          <button className="btn-generate" onClick={handleSaveSurvey}>
            <i className="ri-magic-line"></i>
            產生邀請碼並存入雲端
          </button>
        </div>
      </main>

      {generatedCode && (
        <div className="success-modal-backdrop" onClick={() => setGeneratedCode("")}>
          <div className="success-modal" onClick={(e) => e.stopPropagation()}>
            <div className="success-icon"><i className="ri-checkbox-circle-line"></i></div>
            <h2 className="success-title">問卷已建立</h2>
            <p className="success-desc">把邀請碼分享給填答者，就可以開始收集回覆。</p>
            <div className="invite-code-box">
              <div className="invite-code-label">邀請碼</div>
              <div className="invite-code-value">{generatedCode}</div>
            </div>
            <button
              className={`copy-code-btn ${copied ? "copied" : ""}`}
              onClick={() => {
                navigator.clipboard?.writeText(generatedCode);
                setCopied(true);
              }}
            >
              <i className={copied ? "ri-checkbox-circle-line" : "ri-file-copy-line"}></i>
              {copied ? "已複製" : "複製邀請碼"}
            </button>
            <div className="d-flex gap-3">
              <a href="/survey/fill" className="btn-generate" style={{ flex: 1, padding: "14px", textDecoration: "none", justifyContent: "center" }}>
                <i className="ri-pencil-line"></i> 測試填答
              </a>
              <a href="/profile" className="btn-generate" style={{ flex: 1, padding: "14px", background: "var(--slate-100)", color: "var(--slate-600)", textDecoration: "none", justifyContent: "center" }}>
                查看問卷
              </a>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
