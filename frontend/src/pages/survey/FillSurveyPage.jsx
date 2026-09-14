import { useCallback, useEffect, useMemo, useState } from "react";
import Navbar from "../../components/feature/Navbar";
import "./survey.css";
import { useParams, useSearchParams } from 'react-router-dom';
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
  return date.toLocaleString("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function FillSurveyPage() {
  const { code: codeFromPath } = useParams();
  const [searchParams] = useSearchParams();
  const { recordActivity } = useActivity();
  const [code, setCode] = useState("");
  const [survey, setSurvey] = useState(null);
  const [answers, setAnswers] = useState({});
  const [respondentIdentity, setRespondentIdentity] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loadingSurvey, setLoadingSurvey] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
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
      setError("Please enter an invite code.");
      return;
    }

    const localSurvey = getStoredSurveys()[normalized];

    setLoadingSurvey(true);
    setError("");

    try {
      const response = await fetch(apiUrl(`/api/public/surveys/${encodeURIComponent(normalized)}`), {
        cache: "no-store",
      });
      if (response.status === 410) {
        const expiredData = await response.json().catch(() => ({}));
        setSurvey(null);
        setExpiredSurvey({
          title: expiredData.title || "This survey",
          code: expiredData.access_code || normalized,
          shortCode: expiredData.short_code || "",
          deadlineAt: expiredData.deadline_at || "",
        });
        setError("");
        return;
      }
      if (!response.ok) {
        setError("Invite code not found. Please check it and try again.");
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
        shortCode: data.short_code || "",
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
      console.error("Failed to load survey:", error);
      setError("Unable to connect to the server. Please try again later.");
    } finally {
      setLoadingSurvey(false);
    }
  };

  const handleEnterCode = () => {
    loadSurveyByCode(code);
  };

  const resetForAnotherSurvey = () => {
    window.location.replace("/survey/fill");
  };

  useEffect(() => {
    const codeFromLink = codeFromPath || searchParams.get("code");
    if (!codeFromLink || survey) return;

    const normalized = codeFromLink.trim().toUpperCase();
    setCode(normalized);
    loadSurveyByCode(normalized);
  }, [codeFromPath, searchParams, survey]);

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
    if (isSubmitting) return;

    if (isSurveyExpired(survey.deadlineAt)) {
      setSurvey(null);
      setExpiredSurvey({ title: survey.title, code: survey.code, deadlineAt: survey.deadlineAt });
      setError("");
      return;
    }

    // 檢查必填項目
    if (survey.identityMode === "identified" && !respondentIdentity.trim()) {
      setError("Please provide your identity before submitting the survey.");
      return;
    }

    const missing = survey.questions.some((q) => {
      const value = answers[q.id];
      return q.required && (Array.isArray(value) ? value.length === 0 : !String(value ?? "").trim());
    });

    if (missing) {
      setError("Please complete all required questions.");
      return;
    }

    setIsSubmitting(true);
    setError("");
    const submitStartedAt = Date.now();

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
      const elapsed = Date.now() - submitStartedAt;
      if (elapsed < 900) {
        await new Promise((resolve) => setTimeout(resolve, 900 - elapsed));
      }

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
          text: `Submitted response to survey: ${survey.title}`,
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
        setError("The server could not save your response. Please try again.");
      }
    } catch (error) {
      console.error("Submission failed:", error);
      setError("Unable to connect to the server. Please try again later.");
    } finally {
      setIsSubmitting(false);
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
      return <textarea className="answer-text-input" style={{ minHeight: 120 }} value={answers[question.id] || ""} onChange={(e) => setAnswer(question.id, e.target.value)} placeholder="Enter your answer" />;
    }

    return <input className="answer-text-input" value={answers[question.id] || ""} onChange={(e) => setAnswer(question.id, e.target.value)} placeholder="Enter your answer" />;
  };

  return (
    <>
      <Navbar />
      <main className="fill-survey-page">
        <section className="fill-survey-hero">
          <div className="container">
            <h1 className="fill-survey-title">Complete survey</h1>
            <p className="fill-survey-subtitle">Enter an invite code to begin.</p>
          </div>
        </section>

        <div className="container pb-5">
          {!survey && !expiredSurvey && !submitted && (
            <section className="code-entry-card">
              <div className="code-entry-icon"><i className="ri-key-2-line"></i></div>
              <h2 style={{ textAlign: "center", fontSize: 18, fontWeight: 800 }}>Enter invite code</h2>
              <p style={{ textAlign: "center", color: "var(--slate-500)" }}>Enter the invite code generated for the survey</p>
              <div className="code-input-wrapper">
                <input className={`code-input ${error ? "error" : ""}`} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && handleEnterCode()} maxLength={12} placeholder="Enter invite code" />
                <button className="btn-enter-code" onClick={handleEnterCode} disabled={loadingSurvey}>
                  <i className={loadingSurvey ? "ri-loader-4-line" : "ri-arrow-right-line"}></i>{loadingSurvey ? "Loading" : "Open survey"}
                </button>
              </div>
              {error && <p className="code-error-msg" style={{ display: "flex" }}>{error}</p>}
            </section>
          )}

          {expiredSurvey && !survey && (
            <section className="survey-expired-card">
              <div className="survey-expired-icon"><i className="ri-time-line"></i></div>
              <h2 className="survey-expired-title">Survey closed</h2>
              <p className="survey-expired-desc">
                {expiredSurvey.title ? `「${expiredSurvey.title}」` : "This survey"}has passed its deadline and no longer accepts responses.
              </p>
              {expiredSurvey.deadlineAt && (
                <div className="survey-expired-time">
                  Deadline: {formatDeadline(expiredSurvey.deadlineAt)}
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
                <i className="ri-arrow-left-line"></i>Enter another invite code
              </button>
            </section>
          )}

          {survey && isSubmitting && !submitted && (
            <section className="submit-loading-card" role="status" aria-live="polite">
              <div className="submit-loading-icon"><i className="ri-loader-4-line"></i></div>
              <h2 className="submit-loading-title">Submitting</h2>
              <p className="submit-loading-desc">Submitting your survey response. Please wait.</p>
            </section>
          )}

          {survey && !submitted && !isSubmitting && (
            <section className="survey-form-card">
              <div className="survey-form-header">
                <h2 className="survey-form-title">{survey.title}</h2>
                {survey.description && <p className="survey-form-desc">{survey.description}</p>}
                <div className="survey-form-meta">
                  <div className="survey-form-meta-item"><i className="ri-question-line"></i><span>{questionCount}  questions</span></div>
                  <div className="survey-form-meta-item"><i className="ri-check-line"></i><span>{answeredCount}  answered</span></div>
                  <div className="survey-form-meta-item">
                    <i className={survey.identityMode === "identified" ? "ri-user-line" : "ri-shield-user-line"}></i>
                    <span>{survey.identityMode === "identified" ? "Identified" : "Anonymous"}</span>
                  </div>
                  {survey.deadlineAt && (
                    <div className="survey-form-meta-item">
                      <i className="ri-time-line"></i>
                      <span>Deadline {formatDeadline(survey.deadlineAt)}</span>
                    </div>
                  )}
                </div>
              </div>

              {survey.identityMode === "identified" && (
                <div className="respondent-identity-card">
                  <label className="answer-question-label">
                    <i className="ri-user-line"></i>
                    Respondent identity
                    <span className="required-star">*</span>
                  </label>
                  <input
                    className="answer-text-input"
                    value={respondentIdentity}
                    onChange={(e) => setRespondentIdentity(e.target.value)}
                    placeholder="Enter your name, student ID, employee ID, or another identifier"
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
              <button className="btn-submit-survey" onClick={handleSubmit} disabled={isSubmitting}>
                <i className={isSubmitting ? "ri-loader-4-line ri-spin" : "ri-send-plane-line"}></i>{isSubmitting ? "Submitting" : "Submit survey"}
              </button>
            </section>
          )}

          {submitted && (
            <section className="thankyou-card">
              <div className="thankyou-icon"><i className="ri-checkbox-circle-line"></i></div>
              <h2 className="thankyou-title">Thank you for your response</h2>
              <p className="thankyou-desc">Your survey response has been submitted.</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <button className="btn-submit-survey" onClick={resetForAnotherSurvey}>Complete another survey</button>
                <a href="/survey" style={{ textAlign: "center", color: "var(--slate-500)", fontWeight: 700, textDecoration: "none" }}>Back to surveys</a>
              </div>
            </section>
          )}
        </div>
      </main>
    </>
  );
}
