import { useMemo, useState } from "react";
import Navbar from "../../components/feature/Navbar";
import "./survey.css";
import { useNavigate } from 'react-router-dom';
import { apiUrl } from "../../lib/api";

function getStoredSurveys() {
  return JSON.parse(localStorage.getItem("surveys") || "{}");
}

export default function FillSurveyPage() {
  const navigate = useNavigate(); // 修正點 1：將 navigate 移入組件內部
  const [code, setCode] = useState("");
  const [survey, setSurvey] = useState(null);
  const [answers, setAnswers] = useState({});
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const questionCount = survey?.questions.length ?? 0;
  const answeredCount = useMemo(() => Object.values(answers).filter((value) => Array.isArray(value) ? value.length > 0 : String(value ?? "").trim()).length, [answers]);

  const handleEnterCode = () => {
    const normalized = code.trim().toUpperCase();
    const found = getStoredSurveys()[normalized];
    if (!found) {
      setError("找不到這組邀請碼，請確認後再試一次。");
      return;
    }
    setSurvey({ ...found, code: normalized, responses: found.responses || [] });
    setAnswers({});
    setError("");
    setSubmitted(false);
  };

  const setAnswer = (questionId, value) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
  };

  const toggleMultiple = (questionId, option) => {
    setAnswers((prev) => {
      const current = Array.isArray(prev[questionId]) ? prev[questionId] : [];
      return {
        ...prev,
        [questionId]: current.includes(option) ? current.filter((item) => item !== option) : [...current, option],
      };
    });
  };

  // 修正點 2：合併後的唯一 handleSubmit
  const handleSubmit = async (e) => {
    if (e) e.preventDefault(); 

    // 檢查必填項目
    const missing = survey.questions.some((q) => {
      const value = answers[q.id];
      return q.required && (Array.isArray(value) ? value.length === 0 : !String(value ?? "").trim());
    });

    if (missing) {
      setError("請完成所有必填題目。");
      return;
    }

    try {
      const response = await fetch(apiUrl("/api/submit_form"), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(answers), // 送出使用者回答
      });

      if (response.ok) {
        setSubmitted(true);
        setError("");
        // 成功後跳轉
        setTimeout(() => navigate('/workspace'), 1500); 
      } else {
        setError("伺服器儲存失敗，請檢查後端連線。");
      }
    } catch (error) {
      console.error("提交失敗:", error);
      setError("伺服器連線失敗，請確認後端 Python 是否已啟動。");
    }
  };

  const renderQuestionInput = (question) => {
    if (question.type === "rating") {
      return (
        <div className="rating-row">
          {[0, 1, 2, 3, 4, 5].map((value) => (
            <button key={value} className={`rating-btn ${answers[question.id] === String(value) ? "selected" : ""}`} onClick={() => setAnswer(question.id, String(value))} type="button">
              {value}
            </button>
          ))}
        </div>
      );
    }

    if (question.type === "single") {
      return (
        <div style={{ display: "grid", gap: 10 }}>
          {question.options.map((option) => (
            <label className="profile-field" key={option} style={{ cursor: "pointer" }}>
              <input type="radio" name={question.id} checked={answers[question.id] === option} onChange={() => setAnswer(question.id, option)} />
              <span className="field-value">{option}</span>
            </label>
          ))}
        </div>
      );
    }

    if (question.type === "multiple") {
      return (
        <div style={{ display: "grid", gap: 10 }}>
          {question.options.map((option) => (
            <label className="profile-field" key={option} style={{ cursor: "pointer" }}>
              <input type="checkbox" checked={(answers[question.id] || []).includes(option)} onChange={() => toggleMultiple(question.id, option)} />
              <span className="field-value">{option}</span>
            </label>
          ))}
        </div>
      );
    }

    if (question.type === "long") {
      return <textarea className="answer-text-input" style={{ minHeight: 120 }} value={answers[question.id] || ""} onChange={(e) => setAnswer(question.id, e.target.value)} placeholder="請輸入回答" />;
    }

    return <input className="answer-text-input" value={answers[question.id] || ""} onChange={(e) => setAnswer(question.id, e.target.value)} placeholder="請輸入回答" />;
  };

  return (
    <>
      <Navbar />
      <main className="fill-survey-page">
        <section className="fill-survey-hero">
          <div className="container">
            <h1 className="fill-survey-title">填寫問卷</h1>
            <p className="fill-survey-subtitle">輸入邀請碼即可開始作答。</p>
          </div>
        </section>

        <div className="container pb-5">
          {!survey && (
            <section className="code-entry-card">
              <div className="code-entry-icon"><i className="ri-key-2-line"></i></div>
              <h2 style={{ textAlign: "center", fontSize: 18, fontWeight: 800 }}>輸入邀請碼</h2>
              <p style={{ textAlign: "center", color: "var(--slate-500)" }}>請輸入問卷建立後產生的邀請碼</p>
              <div className="code-input-wrapper">
                <input className={`code-input ${error ? "error" : ""}`} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && handleEnterCode()} maxLength={12} placeholder="輸入邀請碼" />
                <button className="btn-enter-code" onClick={handleEnterCode}>
                  <i className="ri-arrow-right-line"></i>進入
                </button>
              </div>
              {error && <p className="code-error-msg" style={{ display: "flex" }}>{error}</p>}
            </section>
          )}

          {survey && !submitted && (
            <section className="survey-form-card">
              <div className="survey-form-header">
                <h2 className="survey-form-title">{survey.title}</h2>
                {survey.description && <p className="survey-form-desc">{survey.description}</p>}
                <div className="survey-form-meta">
                  <div className="survey-form-meta-item"><i className="ri-question-line"></i><span>{questionCount} 題</span></div>
                  <div className="survey-form-meta-item"><i className="ri-check-line"></i><span>{answeredCount} 題已填</span></div>
                </div>
              </div>

              {survey.questions.map((question, index) => (
                <div className="answer-question" key={question.id}>
                  <div className="answer-question-label">
                    <span style={{ color: "var(--slate-400)", fontWeight: 800 }}>{index + 1}.</span>
                    {question.title}
                    {question.required && <span className="required-star">*</span>}
                  </div>
                  {renderQuestionInput(question)}
                </div>
              ))}

              {error && <p className="code-error-msg" style={{ display: "flex" }}>{error}</p>}
              <button className="btn-submit-survey" onClick={handleSubmit}>
                <i className="ri-send-plane-line"></i>送出問卷
              </button>
            </section>
          )}

          {submitted && (
            <section className="thankyou-card">
              <div className="thankyou-icon"><i className="ri-checkbox-circle-line"></i></div>
              <h2 className="thankyou-title">謝謝你的回覆</h2>
              <p className="thankyou-desc">你的問卷回覆已送出。</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <button className="btn-submit-survey" onClick={() => { setSurvey(null); setCode(""); }}>填寫另一份</button>
                <a href="/survey" style={{ textAlign: "center", color: "var(--slate-500)", fontWeight: 700, textDecoration: "none" }}>返回問卷中心</a>
              </div>
            </section>
          )}
        </div>
      </main>
    </>
  );
}
