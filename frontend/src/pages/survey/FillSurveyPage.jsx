import { useCallback, useEffect, useMemo, useState } from "react";
import Navbar from "../../components/feature/Navbar";
import "./survey.css";
import { useNavigate, useSearchParams } from 'react-router-dom';
import { apiUrl } from "../../lib/api";
import { useActivity } from "../../hooks/ActivityContext";

function getStoredSurveys() {
  try {
    return JSON.parse(localStorage.getItem("surveys") || "{}");
  } catch {
    return {};
  }
}

function saveStoredSurvey(code, survey) {
  const storedSurveys = getStoredSurveys();
  storedSurveys[code] = survey;
  localStorage.setItem("surveys", JSON.stringify(storedSurveys));
}

function isSurveyExpired(deadlineAt) {
  if (!deadlineAt) return false;
  const deadlineTime = new Date(deadlineAt).getTime();
  return Number.isFinite(deadlineTime) && Date.now() > deadlineTime;
}

function formatDeadline(deadlineAt) {
  if (!deadlineAt) return "";
  const date = new Date(deadlineAt);
  if (Number.isNaN(date.getTime())) return deadlineAt;
  return date.toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function FillSurveyPage() {
  const navigate = useNavigate(); // 修正點 1：將 navigate 移入組件內部
  const [searchParams] = useSearchParams();
  const { recordActivity } = useActivity();
  const [code, setCode] = useState("");
  const [survey, setSurvey] = useState(null);
  const [answers, setAnswers] = useState({});
  const [respondentIdentity, setRespondentIdentity] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loadingSurvey, setLoadingSurvey] = useState(false);
  const [expiredSurvey, setExpiredSurvey] = useState(null);

  const questionCount = survey?.questions.length ?? 0;
  const answeredCount = useMemo(() => Object.values(answers).filter((value) => Array.isArray(value) ? value.length > 0 : String(value ?? "").trim()).length, [answers]);

  const openSurvey = useCallback((found, normalized) => {
    if (isSurveyExpired(found.deadlineAt)) {
      setSurvey(null);
      setExpiredSurvey({ title: found.title, code: normalized, deadlineAt: found.deadlineAt });
      setError("");
      setSubmitted(false);
      return;
    }
    setSurvey({ ...found, code: normalized, responses: found.responses || [] });
    setExpiredSurvey(null);
    setAnswers({});
    setRespondentIdentity("");
    setError("");
    setSubmitted(false);
  }, []);

  const loadSurveyByCode = async (rawCode) => {
    const normalized = rawCode.trim().toUpperCase();
    if (!normalized) {
      setError("請輸入邀請碼。");
      return;
    }

    const localSurvey = getStoredSurveys()[normalized];

    setLoadingSurvey(true);
    setError("");
    try {
      const response = await fetch(apiUrl(`/api/surveys/${encodeURIComponent(normalized)}`), {
        cache: "no-store",
      });
      if (response.status === 410) {
        const expiredData = await response.json().catch(() => ({}));
        setSurvey(null);
        setExpiredSurvey({
          title: expiredData.title || "此問卷",
          code: expiredData.access_code || normalized,
          deadlineAt: expiredData.deadline_at || "",
        });
        setError("");
        return;
      }
      if (!response.ok) {
        setError("找不到這組邀請碼，請確認後再試一次。");
        return;
      }

      const data = await response.json();
      const loadedSurvey = {
        id: data.template_id || normalized,
        title: data.title,
        description: data.description || "",
        identityMode: data.identity_mode || "anonymous",
        deadlineAt: data.deadline_at || "",
        questions: data.questions || [],
        code: data.access_code || normalized,
        createdAt: data.created_at ? data.created_at.slice(0, 10) : "",
        responses: localSurvey?.responses || [],
        ownerId: localSurvey?.ownerId,
        ownerEmail: localSurvey?.ownerEmail,
        createdAtMs: localSurvey?.createdAtMs,
      };
      saveStoredSurvey(normalized, loadedSurvey);
      openSurvey(loadedSurvey, normalized);
    } catch (error) {
      if (localSurvey) {
        openSurvey(localSurvey, normalized);
        return;
      }
      console.error("讀取問卷失敗:", error);
      setError("伺服器連線失敗，請稍後再試。");
    } finally {
      setLoadingSurvey(false);
    }
  };

  const handleEnterCode = () => {
    loadSurveyByCode(code);
  };

  useEffect(() => {
    const codeFromLink = searchParams.get("code");
    if (!codeFromLink || survey) return;

    const normalized = codeFromLink.trim().toUpperCase();
    setCode(normalized);
    loadSurveyByCode(normalized);
  }, [searchParams, survey]);

  useEffect(() => {
    const refreshOpenSurvey = (event) => {
      const activeCode = (survey?.code || expiredSurvey?.code || code).trim().toUpperCase();
      const updatedCode = event?.detail?.code ? String(event.detail.code).trim().toUpperCase() : "";
      if (!activeCode || (updatedCode && updatedCode !== activeCode)) return;

      const latestSurvey = getStoredSurveys()[activeCode];
      if (latestSurvey) openSurvey(latestSurvey, activeCode);
    };
    const handleStorage = (event) => {
      if (event.key === "surveys") refreshOpenSurvey(event);
    };

    window.addEventListener("dataanalysis:surveys-updated", refreshOpenSurvey);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener("dataanalysis:surveys-updated", refreshOpenSurvey);
      window.removeEventListener("storage", handleStorage);
    };
  }, [code, expiredSurvey?.code, openSurvey, survey?.code]);

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

    if (isSurveyExpired(survey.deadlineAt)) {
      setSurvey(null);
      setExpiredSurvey({ title: survey.title, code: survey.code, deadlineAt: survey.deadlineAt });
      setError("");
      return;
    }

    // 檢查必填項目
    if (survey.identityMode === "identified" && !respondentIdentity.trim()) {
      setError("請填寫身分後再送出問卷。");
      return;
    }

    const missing = survey.questions.some((q) => {
      const value = answers[q.id];
      return q.required && (Array.isArray(value) ? value.length === 0 : !String(value ?? "").trim());
    });

    if (missing) {
      setError("請完成所有必填題目。");
      return;
    }

    try {
      const response = await fetch(apiUrl(`/api/surveys/${survey.code}/responses`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          answers,
          respondent_identity: survey.identityMode === "identified" ? respondentIdentity.trim() : "",
        }),
      });

      if (response.ok) {
        const storedSurveys = getStoredSurveys();
        const existingSurvey = storedSurveys[survey.code] || survey;
        storedSurveys[survey.code] = {
          ...existingSurvey,
          responses: [
            ...(existingSurvey.responses || []),
            {
              answers,
              respondentIdentity: survey.identityMode === "identified" ? respondentIdentity.trim() : "",
              submittedAt: new Date().toISOString(),
            },
          ],
        };
        localStorage.setItem("surveys", JSON.stringify(storedSurveys));
        recordActivity({
          text: `提交問卷回覆「${survey.title}」`,
          icon: "ri-send-plane-line",
          iconBg: "bg-stat-teal",
          iconColor: "text-stat-teal",
        });
        setSubmitted(true);
        setError("");
      } else if (response.status === 410) {
        const expiredData = await response.json().catch(() => ({}));
        setSurvey(null);
        setExpiredSurvey({
          title: survey.title,
          code: survey.code,
          deadlineAt: expiredData.deadline_at || survey.deadlineAt,
        });
        setError("");
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
          {!survey && !expiredSurvey && (
            <section className="code-entry-card">
              <div className="code-entry-icon"><i className="ri-key-2-line"></i></div>
              <h2 style={{ textAlign: "center", fontSize: 18, fontWeight: 800 }}>輸入邀請碼</h2>
              <p style={{ textAlign: "center", color: "var(--slate-500)" }}>請輸入問卷建立後產生的邀請碼</p>
              <div className="code-input-wrapper">
                <input className={`code-input ${error ? "error" : ""}`} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && handleEnterCode()} maxLength={12} placeholder="輸入邀請碼" />
                <button className="btn-enter-code" onClick={handleEnterCode} disabled={loadingSurvey}>
                  <i className={loadingSurvey ? "ri-loader-4-line" : "ri-arrow-right-line"}></i>{loadingSurvey ? "讀取中" : "進入"}
                </button>
              </div>
              {error && <p className="code-error-msg" style={{ display: "flex" }}>{error}</p>}
            </section>
          )}

          {expiredSurvey && !survey && (
            <section className="survey-expired-card">
              <div className="survey-expired-icon"><i className="ri-time-line"></i></div>
              <h2 className="survey-expired-title">問卷已截止</h2>
              <p className="survey-expired-desc">
                {expiredSurvey.title ? `「${expiredSurvey.title}」` : "這份問卷"}已超過填答期限，無法再送出回覆。
              </p>
              {expiredSurvey.deadlineAt && (
                <div className="survey-expired-time">
                  截止時間：{formatDeadline(expiredSurvey.deadlineAt)}
                </div>
              )}
              <button
                className="btn-enter-code expired-back-btn"
                type="button"
                onClick={() => {
                  setExpiredSurvey(null);
                  setCode("");
                }}
              >
                <i className="ri-arrow-left-line"></i>輸入其他邀請碼
              </button>
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
                  <div className="survey-form-meta-item">
                    <i className={survey.identityMode === "identified" ? "ri-user-line" : "ri-shield-user-line"}></i>
                    <span>{survey.identityMode === "identified" ? "非匿名" : "匿名"}</span>
                  </div>
                  {survey.deadlineAt && (
                    <div className="survey-form-meta-item">
                      <i className="ri-time-line"></i>
                      <span>截止 {formatDeadline(survey.deadlineAt)}</span>
                    </div>
                  )}
                </div>
              </div>

              {survey.identityMode === "identified" && (
                <div className="respondent-identity-card">
                  <label className="answer-question-label">
                    <i className="ri-user-line"></i>
                    填答人身分
                    <span className="required-star">*</span>
                  </label>
                  <input
                    className="answer-text-input"
                    value={respondentIdentity}
                    onChange={(e) => setRespondentIdentity(e.target.value)}
                    placeholder="請輸入姓名、學號、員工編號或可辨識身分"
                  />
                </div>
              )}

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
