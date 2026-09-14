import { useMemo, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import DeadlineDateTimePicker from "../../components/feature/DeadlineDateTimePicker";
import { useAuth } from "../../hooks/AuthContext";
import { useActivity } from "../../hooks/ActivityContext";
import axios from "axios";
import { apiUrl } from "../../lib/api";
import { buildExternalSurveyShortUrl, buildSurveyFillPath } from "../../lib/surveyLinks";
import "./survey.css";


const QUESTION_TYPES = [
  { value: "short", label: "Open-ended question", icon: "ri-question-answer-line" },
  { value: "rating", label: "Rating (0–5)", icon: "ri-star-line" },
];

function newQuestion(type = "short") {
  return {
    id: crypto.randomUUID(),
    type,
    title: "",
    required: true,
    options: [],
  };
}

function generateCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from({ length: 6 }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
}

function toDateTimeLocalValue(date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function getNextDeadlineMin() {
  const nextMinute = new Date(Date.now() + 60000);
  nextMinute.setSeconds(0, 0);
  return toDateTimeLocalValue(nextMinute);
}

export default function CreateSurveyPage() {
  const navigate = useNavigate();
  const { isLoggedIn, user } = useAuth();
  const { recordActivity } = useActivity();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [identityMode, setIdentityMode] = useState("anonymous");
  const [deadlineAt, setDeadlineAt] = useState("");
  const [questions, setQuestions] = useState([
    newQuestion("short")
  ]);
  const [error, setError] = useState("");
  const [minDeadlineAt, setMinDeadlineAt] = useState(() => getNextDeadlineMin());
  const [generatedCode, setGeneratedCode] = useState("");
  const [generatedShortCode, setGeneratedShortCode] = useState("");
  const [externalShareLink, setExternalShareLink] = useState("");
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const shareLink = externalShareLink;

  // 檢查本地 token 是否對本機後端有效，若無效則清除並導向登入
  useEffect(() => {
    (async () => {
      if (!isLoggedIn) return;
      try {
        const auth = user || JSON.parse(localStorage.getItem("dataanalysis_auth") || "{}");
        const token = auth?.token;
        if (!token) return;
        const res = await fetch(apiUrl(`/api/profile/${auth.user_id || auth.user_id}`), { headers: { Authorization: `Bearer ${token}` } });
        if (res.status === 401) {
          localStorage.removeItem('dataanalysis_auth');
          navigate('/login');
        }
      } catch (e) {
        // ignore network errors here; creation flow will handle them
      }
    })();
  }, [isLoggedIn, user, navigate]);

  useEffect(() => {
    const updateMinDeadline = () => setMinDeadlineAt(getNextDeadlineMin());
    updateMinDeadline();
    const timer = window.setInterval(updateMinDeadline, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const typeMap = useMemo(() => Object.fromEntries(QUESTION_TYPES.map((item) => [item.value, item])), []);
  const getQuestionType = (type) => typeMap[type] || typeMap.short;

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div className="survey-page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <LoginRequiredModal
            message="Please log in to create a survey."
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
        return { ...q, ...patch, ...(patch.type ? { options: [] } : {}) };
      })
    );
  };

  const duplicateQuestion = (question) => {
    setQuestions((prev) => {
      const index = prev.findIndex((q) => q.id === question.id);
      const clone = { ...question, id: crypto.randomUUID(), title: `${question.title} (copy)` };
      return [...prev.slice(0, index + 1), clone, ...prev.slice(index + 1)];
    });
  };

  const validate = () => {
    if (!title.trim()) return "Please enter a survey title.";
    if (deadlineAt && new Date(deadlineAt).getTime() <= Date.now()) return "The survey deadline must be later than now.";
    if (questions.some((q) => !q.title.trim())) return "Please enter text for every question.";
    return "";
  };

  const handleSaveSurvey = async (e) => {
    if (e) e.preventDefault();
    if (isSaving) return;

    const validationMessage = validate();
    if (validationMessage) {
      setError(validationMessage);
      return;
    }

    setIsSaving(true);
    try {
      const auth = user || JSON.parse(localStorage.getItem("dataanalysis_auth") || "{}");
      const token = auth?.token;

      const payload = {
        title: title.trim(),
        description: description.trim(),
        identity_mode: identityMode,
        deadline_at: deadlineAt,
        questions: questions.map((q) => ({
          ...q,
          title: q.title.trim(),
          options: (q.options || []).map((opt) => opt.trim()),
        })),
        user_id: user?.user_id
      };

      console.log("[FRONTEND] Sending data to database", payload);

      const response = await axios.post(apiUrl("/api/surveys"), payload, {
        headers: {
          Authorization: `Bearer ${token}`
        },
        timeout: 60000,
      });

      if (response.status === 201 || response.status === 200) {
        console.log("[FRONTEND] Saved to database:", response.data);

        const accessCode = response.data.access_code;
        const shortCode = response.data.short_code || accessCode;
        setExternalShareLink("");
        setGeneratedCode(accessCode);
        setGeneratedShortCode(shortCode);
        setCopiedCode(false);
        setCopiedLink(false);
        setError("");

        const createdAtMs = Date.now();
        const savedSurvey = {
          id: response.data.template_id || `survey-${Date.now()}`,
          title: payload.title,
          description: payload.description,
          identityMode: payload.identity_mode,
          deadlineAt: payload.deadline_at,
          questions: payload.questions,
          code: accessCode,
          shortCode,
          createdAt: new Date(createdAtMs).toISOString().slice(0, 10),
          createdAtMs,
          responses: [],
          ownerId: user?.user_id,
          ownerEmail: user?.email,
        };
        try {
          const storedSurveys = JSON.parse(localStorage.getItem("surveys") || "{}");
          storedSurveys[accessCode] = savedSurvey;
          localStorage.setItem("surveys", JSON.stringify(storedSurveys));
        } catch (storageError) {
          console.warn("[FRONTEND] localStorage survey cache failed:", storageError);
        }
        recordActivity({
          text: `Created survey: ${payload.title}`,
          icon: "ri-survey-line",
          iconBg: "bg-stat-coral",
          iconColor: "text-stat-coral",
        });
        buildExternalSurveyShortUrl(accessCode).then((externalLink) => {
          setExternalShareLink(externalLink);
        }).catch((linkError) => {
          console.warn("[FRONTEND] short link creation failed:", linkError);
        });
      }
    } catch (error) {
      console.error("[FRONTEND] Save failed:", error);
      const status = error?.response?.status;
      if (status === 401) {
        alert("Your session has expired or is invalid. Please log in again. Redirecting to login.");
        localStorage.removeItem("dataanalysis_auth");
        navigate('/login');
        return;
      }
      if (error?.code === "ECONNABORTED") {
        setError("The server is taking longer than expected. Check your profile's survey list before retrying.");
        return;
      }
      if (error?.response?.data?.error) {
        setError(error.response.data.error);
        return;
      }
      alert("Unable to save the survey. Please try again later.");
    } finally {
      setIsSaving(false);
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
                <i className="ri-arrow-left-line"></i> Back to surveys
              </a>
              <span style={{ color: "var(--slate-300)" }}>|</span>
              <span style={{ fontWeight: 800, color: "var(--slate-800)" }}>Create survey</span>
            </div>
          </div>
        </div>

        <div className="create-survey-body">
          <section className="survey-meta-card">
            <div className="survey-meta-title">
              <div className="survey-meta-icon"><i className="ri-file-text-line"></i></div>
              Survey information
            </div>
            <div className="mb-3">
              <label className="auth-label">Survey title <span style={{ color: "#ef4444" }}>*</span></label>
              <input className="survey-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Product satisfaction survey" />
            </div>
            <div>
              <label className="auth-label">Survey description</label>
              <textarea className="survey-input survey-textarea" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Add instructions, purpose, or notes for respondents" maxLength={500} />
            </div>
            <div className="survey-identity-setting">
              <label className="auth-label">Respondent identity <span style={{ color: "#ef4444" }}>*</span></label>
              <div className="survey-identity-options" role="radiogroup" aria-label="Respondent identity settings">
                <label className={`survey-identity-option ${identityMode === "anonymous" ? "active" : ""}`}>
                  <input
                    type="radio"
                    name="identity_mode"
                    value="anonymous"
                    checked={identityMode === "anonymous"}
                    onChange={() => setIdentityMode("anonymous")}
                  />
                  <span className="identity-option-title">Anonymous</span>
                  <span className="identity-option-desc">Respondents do not need to provide their identity.</span>
                </label>
                <label className={`survey-identity-option ${identityMode === "identified" ? "active" : ""}`}>
                  <input
                    type="radio"
                    name="identity_mode"
                    value="identified"
                    checked={identityMode === "identified"}
                    onChange={() => setIdentityMode("identified")}
                  />
                  <span className="identity-option-title">Identified</span>
                  <span className="identity-option-desc">Respondents must provide their identity before submitting.</span>
                </label>
              </div>
            </div>
            <div className="survey-deadline-setting">
              <label className="auth-label">Survey deadline</label>
              <DeadlineDateTimePicker value={deadlineAt} min={minDeadlineAt} onChange={setDeadlineAt} />
              <p className="survey-field-hint">Responses can only be submitted before the deadline.</p>
            </div>
          </section>

          {questions.map((question, index) => {
            const questionType = getQuestionType(question.type);

            return (
              <section className="question-card" key={question.id}>
              <div className="question-card-header">
                <div className="question-number">{index + 1}</div>
                <select className="question-type-select" value={questionType.value} onChange={(e) => updateQuestion(question.id, { type: e.target.value })}>
                  {QUESTION_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>{type.label}</option>
                  ))}
                </select>
                <label className="question-required-toggle ms-auto me-2" style={{ cursor: "pointer" }}>
                  <input type="checkbox" checked={question.required} onChange={(e) => updateQuestion(question.id, { required: e.target.checked })} />
                  <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 700, color: "var(--slate-500)" }}>Required</span>
                </label>
                <button className="question-delete-btn" onClick={() => duplicateQuestion(question)} title="Duplicate question" type="button">
                  <i className="ri-file-copy-line"></i>
                </button>
                <button className="question-delete-btn" onClick={() => setQuestions((prev) => (prev.length === 1 ? prev : prev.filter((q) => q.id !== question.id)))} title="Delete question" type="button">
                  <i className="ri-delete-bin-line"></i>
                </button>
              </div>

              <input className="survey-input" value={question.title} onChange={(e) => updateQuestion(question.id, { title: e.target.value })} placeholder={`Question  ${index + 1}`} />

              <div className="q-preview" style={{ marginTop: 14 }}>
                <i className={`${questionType.icon} me-1`}></i>
                {questionType.label}
              </div>
              </section>
            );
          })}

          <button className="add-question-area" onClick={() => setQuestions((prev) => [...prev, newQuestion()])} type="button">
            <i className="ri-add-circle-line"></i>
            <p>Add question</p>
          </button>

          {error && <p style={{ color: "#ef4444", fontWeight: 800 }}>{error}</p>}
          <button className="btn-generate" onClick={handleSaveSurvey} disabled={isSaving}>
            <i className={isSaving ? "ri-loader-4-line" : "ri-magic-line"}></i>
            {isSaving ? "Saving…" : "Finish creating survey"}
          </button>
        </div>
      </main>

      {generatedCode && (
        <div className="success-modal-backdrop" onClick={() => setGeneratedCode("")}>
          <div className="success-modal" onClick={(e) => e.stopPropagation()}>
            <div className="success-icon"><i className="ri-checkbox-circle-line"></i></div>
            <h2 className="success-title">Survey created</h2>
            <p className="success-desc">Share the invite code with respondents to start collecting responses.</p>
            <div className="invite-code-box">
              <div className="invite-code-label">Invite code</div>
              <div className="invite-code-value">{generatedCode}</div>
            </div>
            <button
              className={`copy-code-btn ${copiedCode ? "copied" : ""}`}
              onClick={() => {
                navigator.clipboard?.writeText(generatedCode);
                setCopiedCode(true);
              }}
            >
              <i className={copiedCode ? "ri-checkbox-circle-line" : "ri-file-copy-line"}></i>
              {copiedCode ? "Copied" : "Copy invite code"}
            </button>
            <div className="invite-link-box">
              <div className="invite-code-label">Survey link</div>
              <div className="invite-link-value">{shareLink || "Creating short link..."}</div>
            </div>
            <button
              className={`copy-code-btn ${copiedLink ? "copied" : ""}`}
              disabled={!shareLink}
              onClick={() => {
                if (!shareLink) return;
                navigator.clipboard?.writeText(shareLink);
                setCopiedLink(true);
              }}
            >
              <i className={copiedLink ? "ri-checkbox-circle-line" : "ri-link"}></i>
              {copiedLink ? "Link copied" : "Copy survey link"}
            </button>
            <div className="d-flex gap-3">
              <a href={buildSurveyFillPath(generatedCode)} className="btn-generate" style={{ flex: 1, padding: "14px", textDecoration: "none", justifyContent: "center" }}>
                <i className="ri-pencil-line"></i> Test survey
              </a>
              <a href="/profile" className="btn-generate" style={{ flex: 1, padding: "14px", background: "var(--slate-100)", color: "var(--slate-600)", textDecoration: "none", justifyContent: "center" }}>
                View survey
              </a>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
