import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import Navbar from "../../components/feature/Navbar";
import { useActivity } from "../../hooks/ActivityContext";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";
import { buildExternalSurveyShortUrl, buildSurveyFillPath } from "../../lib/surveyLinks";
import {
  generateSurveyFromPpt,
  reviseSurveyWithAi,
  toCompatibleSurveyPayload,
} from "../../lib/pptSurveyAi";
import "./survey.css";

const defaultPptConfig = {
  direction: "",
  focus: "",
  questionCount: 5,
  typeLimits: {
    short: true,
    rating: true,
  },
};

function getSurveyTime(createdAt) {
  const time = new Date(createdAt || 0).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function newDraftQuestion(type = "short") {
  return {
    id: crypto.randomUUID(),
    type,
    title: "",
    required: true,
    options: [],
  };
}

function normalizeDraft(draft) {
  return toCompatibleSurveyPayload({
    ...draft,
    questions: draft.questions?.length ? draft.questions : [newDraftQuestion()],
  });
}

export default function SurveyPage() {
  const { user } = useAuth();
  const { recordActivity } = useActivity();
  const [apiSurveys, setApiSurveys] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isPptModalOpen, setIsPptModalOpen] = useState(false);
  const [pptFile, setPptFile] = useState(null);
  const [pptConfig, setPptConfig] = useState(defaultPptConfig);
  const [pptDraft, setPptDraft] = useState(null);
  const [pptError, setPptError] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [isChatting, setIsChatting] = useState(false);
  const [aiMessage, setAiMessage] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [savedResult, setSavedResult] = useState(null);
  const [shareLink, setShareLink] = useState("");

  useEffect(() => {
    if (!user?.token) return;

    setIsLoading(true);
    fetch(apiUrl("/api/surveys/mine?limit=3"), {
      headers: { Authorization: `Bearer ${user.token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("Load surveys failed");
        return res.json();
      })
      .then((data) => {
        setApiSurveys(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        console.error("Load recent surveys failed:", err);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [user]);

  const recentSurveys = useMemo(() => {
    if (!user) return [];

    return [...apiSurveys]
      .sort((a, b) => {
        const timeA = getSurveyTime(a.createdAt || a.created_at);
        const timeB = getSurveyTime(b.createdAt || b.created_at);
        return timeB - timeA;
      })
      .slice(0, 3);
  }, [apiSurveys, user]);

  const resetPptModal = () => {
    setPptFile(null);
    setPptConfig(defaultPptConfig);
    setPptDraft(null);
    setPptError("");
    setIsGenerating(false);
    setIsChatting(false);
    setAiMessage("");
    setChatMessages([]);
    setIsSavingDraft(false);
    setSavedResult(null);
    setShareLink("");
  };

  const closePptModal = () => {
    setIsPptModalOpen(false);
    resetPptModal();
  };

  const updatePptConfig = (patch) => {
    setPptConfig((prev) => ({ ...prev, ...patch }));
  };

  const updateTypeLimit = (type, checked) => {
    setPptConfig((prev) => {
      const nextLimits = { ...prev.typeLimits, [type]: checked };
      if (!nextLimits.short && !nextLimits.rating) {
        nextLimits[type] = true;
      }
      return { ...prev, typeLimits: nextLimits };
    });
  };

  const handleGenerateDraft = async () => {
    if (!pptFile) {
      setPptError("Please upload a PPT or PDF file first.");
      return;
    }

    setPptError("");
    setIsGenerating(true);
    setSavedResult(null);
    setShareLink("");

    try {
      const draft = await generateSurveyFromPpt({
        file: pptFile,
        config: pptConfig,
        token: user?.token,
      });
      setPptDraft(normalizeDraft(draft));
      setChatMessages([
        {
          role: "assistant",
          text: "A survey draft has been created from your material. Edit the questions directly or use the chat on the right.",
        },
      ]);
    } catch (error) {
      console.error("Generate PPT survey failed:", error);
      const message = error?.message || "Failed to generate a draft. Please try again later.";
      setPptError(message);
      window.alert(message);
    } finally {
      setIsGenerating(false);
    }
  };

  const updateDraft = (patch) => {
    setPptDraft((prev) => normalizeDraft({ ...prev, ...patch }));
  };

  const updateDraftQuestion = (id, patch) => {
    setPptDraft((prev) => normalizeDraft({
      ...prev,
      questions: prev.questions.map((question) => (
        question.id === id ? { ...question, ...patch } : question
      )),
    }));
  };

  const addDraftQuestion = (type = "short") => {
    setPptDraft((prev) => normalizeDraft({
      ...prev,
      questions: [...prev.questions, newDraftQuestion(type)],
    }));
  };

  const removeDraftQuestion = (id) => {
    setPptDraft((prev) => normalizeDraft({
      ...prev,
      questions: prev.questions.length === 1
        ? prev.questions
        : prev.questions.filter((question) => question.id !== id),
    }));
  };

  const handleAiRevise = async () => {
    if (!pptDraft || !aiMessage.trim() || isChatting) return;

    const message = aiMessage.trim();
    setAiMessage("");
    setIsChatting(true);
    setChatMessages((prev) => [...prev, { role: "user", text: message }]);

    try {
      const revisedDraft = await reviseSurveyWithAi({
        draft: pptDraft,
        message,
        token: user?.token,
      });
      setPptDraft(normalizeDraft(revisedDraft));
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", text: "The draft has been updated. Review the preview on the left." },
      ]);
    } catch (error) {
      console.error("Revise PPT survey failed:", error);
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", text: error?.message || "The edit failed. Try rephrasing your instructions." },
      ]);
    } finally {
      setIsChatting(false);
    }
  };

  const validateDraft = () => {
    if (!pptDraft?.title?.trim()) return "Please enter a survey title.";
    if (!pptDraft.questions?.length) return "Please keep at least one question.";
    if (pptDraft.questions.some((question) => !question.title.trim())) {
      return "Please enter text for every question.";
    }
    return "";
  };

  const handleSaveDraft = async () => {
    if (!user?.token) {
      setPptError("Please log in to save the survey.");
      return;
    }

    const validationMessage = validateDraft();
    if (validationMessage) {
      setPptError(validationMessage);
      return;
    }

    setPptError("");
    setIsSavingDraft(true);
    setShareLink("");

    try {
      const payload = toCompatibleSurveyPayload(pptDraft);
      const response = await axios.post(apiUrl("/api/surveys"), payload, {
        headers: { Authorization: `Bearer ${user.token}` },
        timeout: 60000,
      });

      const accessCode = response.data.access_code;
      const shortCode = response.data.short_code || accessCode;
      const savedSurvey = {
        id: response.data.template_id || `survey-${Date.now()}`,
        title: payload.title,
        description: payload.description,
        identityMode: payload.identity_mode,
        deadlineAt: payload.deadline_at,
        questions: payload.questions,
        code: accessCode,
        shortCode,
        createdAt: new Date().toISOString().slice(0, 10),
        createdAtMs: Date.now(),
        responses: [],
        ownerId: user?.user_id,
        ownerEmail: user?.email,
        source: "ppt-ai",
      };

      try {
        const storedSurveys = JSON.parse(localStorage.getItem("surveys") || "{}");
        storedSurveys[accessCode] = savedSurvey;
        localStorage.setItem("surveys", JSON.stringify(storedSurveys));
      } catch (storageError) {
        console.warn("Local survey cache failed:", storageError);
      }

      recordActivity({
        text: `Created AI-generated survey: ${payload.title}`,
        icon: "ri-slideshow-3-line",
        iconBg: "bg-stat-coral",
        iconColor: "text-stat-coral",
      });

      setApiSurveys((prev) => [
        {
          template_id: savedSurvey.id,
          title: savedSurvey.title,
          access_code: accessCode,
          short_code: shortCode,
          created_at: new Date().toISOString(),
          deadline_at: payload.deadline_at,
          response_count: 0,
        },
        ...prev,
      ]);
      setSavedResult({ accessCode, shortCode });

      buildExternalSurveyShortUrl(accessCode)
        .then(setShareLink)
        .catch((error) => {
          console.warn("Short link creation failed:", error);
          setShareLink(buildSurveyFillPath(accessCode));
        });
    } catch (error) {
      console.error("Save PPT survey failed:", error);
      setPptError(error?.response?.data?.error || "Save failed. Please try again later.");
    } finally {
      setIsSavingDraft(false);
    }
  };

  return (
    <>
      <Navbar />
      <main className="survey-page">
        <section className="survey-workspace">
          <div className="survey-intro">
            <div className="survey-hero-badge">
              <i className="ri-survey-line"></i>
              <span>Surveys</span>
            </div>
            <h1 className="survey-hero-title">Create surveys and collect feedback</h1>
            <p className="survey-hero-subtitle">
              Create rating and open-ended questions, share an invite code, and organize responses with the Analysis Assistant.
            </p>
          </div>

          <div className="survey-board">
            <a className="survey-entry-card create" href="/survey/create">
              <div className="entry-card-topline">
                <div className="entry-card-icon create-icon">
                  <i className="ri-edit-box-line"></i>
                </div>
                <span className="entry-card-kicker">Create manually</span>
              </div>
              <div className="entry-card-copy">
                <h2 className="entry-card-title">Create survey</h2>
                <p className="entry-card-desc">
                  Customize questions and response rules, then generate an invite code and survey link to start collecting responses.
                </p>
              </div>
              <div className="entry-card-footer">
                <span className="entry-card-action">
                  Create survey
                  <i className="ri-arrow-right-line"></i>
                </span>
                <span className="entry-card-note">Ratings · Open-ended questions · Invite codes</span>
              </div>
            </a>

            <aside className="survey-side-stack">
              <button
                className="survey-entry-card ppt-generate"
                onClick={() => setIsPptModalOpen(true)}
                type="button"
              >
                <div className="entry-card-icon ppt-icon">
                  <i className="ri-slideshow-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">AI generation</span>
                  <h2 className="entry-card-title">Generate a survey from PPT/PDF</h2>
                  <p className="entry-card-desc">
                    Generate a draft from presentation or PDF highlights, review and edit it, then save your survey.
                  </p>
                </div>
                <span className="entry-card-arrow"><i className="ri-sparkling-line"></i></span>
              </button>

              <a className="survey-entry-card fill" href="/survey/fill">
                <div className="entry-card-icon fill-icon">
                  <i className="ri-file-list-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">Respond to a survey</span>
                  <h2 className="entry-card-title">Complete survey</h2>
                  <p className="entry-card-desc">Enter an invite code to open a survey and submit feedback.</p>
                </div>
                <span className="entry-card-arrow"><i className="ri-arrow-right-line"></i></span>
              </a>

              <section className="survey-activity-card">
                <div className="survey-activity-head">
                  <div>
                    <span className="entry-card-kicker">Recently created</span>
                    <h2>Survey history</h2>
                    <p className="survey-activity-note">View recently created surveys and their response status.</p>
                  </div>
                </div>

                {!user ? (
                  <div className="survey-activity-empty">
                    <i className="ri-lock-line"></i>
                    <span>Log in to view recent survey activity.</span>
                  </div>
                ) : isLoading ? (
                  <div className="survey-activity-empty">
                    <i className="ri-loader-4-line ri-spin"></i>
                    <span>Loading surveys...</span>
                  </div>
                ) : recentSurveys.length > 0 ? (
                  <div className="survey-activity-list">
                    {recentSurveys.map((survey) => {
                      const code = survey.code || survey.access_code;
                      return (
                        <a className="survey-activity-item" href={`/profile?survey=${encodeURIComponent(code)}`} key={code}>
                          <span className="survey-activity-dot"></span>
                          <div>
                            <strong>{survey.title || survey.survey_name || "Untitled survey"}</strong>
                            <span>
                              {survey.responses?.length || survey.response_count || 0} responses ·  {code}
                            </span>
                          </div>
                        </a>
                      );
                    })}
                  </div>
                ) : (
                  <div className="survey-activity-empty">
                    <i className="ri-time-line"></i>
                    <span>Recent activity will appear here after you create a survey.</span>
                  </div>
                )}
              </section>
            </aside>
          </div>
        </section>
      </main>

      {isPptModalOpen && (
        <div className="ppt-modal-backdrop" onClick={closePptModal}>
          <section className="ppt-modal" onClick={(event) => event.stopPropagation()}>
            <header className="ppt-modal-header">
              <div>
                <span className="entry-card-kicker">AI survey draft from learning material</span>
                <h2>Generate a survey from PPT/PDF</h2>
              </div>
              <button className="ppt-icon-btn" onClick={closePptModal} type="button" aria-label="Close">
                <i className="ri-close-line"></i>
              </button>
            </header>

            <div className="ppt-modal-body">
              <div className="ppt-config-panel">
                <label className="ppt-upload-zone">
                  <input
                    type="file"
                    accept=".ppt,.pptx,.pdf,application/pdf,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    onChange={(event) => setPptFile(event.target.files?.[0] || null)}
                  />
                  <i className="ri-upload-cloud-2-line"></i>
                  <strong>{pptFile ? pptFile.name : "Choose a PPT or PDF file"}</strong>
                  <span>Supports .ppt, .pptx, and .pdf</span>
                </label>

                <div className="ppt-field-grid">
                  <label className="ppt-field">
                    <span>Question focus</span>
                    <input
                      value={pptConfig.direction}
                      onChange={(event) => updatePptConfig({ direction: event.target.value })}
                      placeholder="e.g. Course satisfaction, learning outcomes"
                    />
                  </label>
                  <label className="ppt-field">
                    <span>Generation priorities</span>
                    <textarea
                      value={pptConfig.focus}
                      onChange={(event) => updatePptConfig({ focus: event.target.value })}
                      placeholder="e.g. Focus on course content, delivery, and practical applications"
                    />
                  </label>
                  <label className="ppt-field">
                    <span>Questions</span>
                    <input
                      type="number"
                      min="1"
                      max="20"
                      value={pptConfig.questionCount}
                      onChange={(event) => updatePptConfig({ questionCount: event.target.value })}
                    />
                  </label>
                </div>

                <div className="ppt-type-limits">
                  <span>Question types</span>
                  <label>
                    <input
                      type="checkbox"
                      checked={pptConfig.typeLimits.short}
                      onChange={(event) => updateTypeLimit("short", event.target.checked)}
                    />
                    Open-ended question
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={pptConfig.typeLimits.rating}
                      onChange={(event) => updateTypeLimit("rating", event.target.checked)}
                    />
                    Rating question
                  </label>
                </div>

                <button className="ppt-primary-btn" onClick={handleGenerateDraft} disabled={isGenerating} type="button">
                  <i className={isGenerating ? "ri-loader-4-line" : "ri-sparkling-line"}></i>
                  {isGenerating ? "Generating..." : "Generate draft"}
                </button>

                {pptError && <p className="ppt-error">{pptError}</p>}
              </div>

              <div className="ppt-preview-panel">
                {isGenerating ? (
                  <div className="ppt-loading-state">
                    <i className="ri-loader-4-line"></i>
                    <strong>AI is reviewing your material</strong>
                    <span>Preparing your survey draft. Please wait.</span>
                  </div>
                ) : pptDraft ? (
                  <div className="ppt-draft-layout">
                    <div className="ppt-draft-editor">
                      <div className="ppt-draft-meta">
                        <label className="ppt-field">
                          <span>Survey title</span>
                          <input
                            value={pptDraft.title}
                            onChange={(event) => updateDraft({ title: event.target.value })}
                          />
                        </label>
                        <label className="ppt-field">
                          <span>Survey description</span>
                          <textarea
                            value={pptDraft.description}
                            onChange={(event) => updateDraft({ description: event.target.value })}
                          />
                        </label>
                      </div>

                      <div className="ppt-draft-question-list">
                        {pptDraft.questions.map((question, index) => (
                          <article className="ppt-draft-question" key={question.id}>
                            <div className="ppt-question-head">
                              <span>Q{index + 1}</span>
                              <select
                                value={question.type}
                                onChange={(event) => updateDraftQuestion(question.id, { type: event.target.value })}
                              >
                                <option value="short">Open-ended question</option>
                                <option value="rating">Rating question</option>
                              </select>
                              <label>
                                <input
                                  type="checkbox"
                                  checked={question.required}
                                  onChange={(event) => updateDraftQuestion(question.id, { required: event.target.checked })}
                                />
                                Required
                              </label>
                              <button className="ppt-icon-btn" onClick={() => removeDraftQuestion(question.id)} type="button" aria-label="Delete question">
                                <i className="ri-delete-bin-line"></i>
                              </button>
                            </div>
                            <input
                              className="ppt-question-title"
                              value={question.title}
                              onChange={(event) => updateDraftQuestion(question.id, { title: event.target.value })}
                              placeholder="Enter question text"
                            />
                            {question.type === "rating" && (
                              <div className="ppt-rating-preview">
                                {[0, 1, 2, 3, 4, 5].map((score) => (
                                  <span key={score}>{score}</span>
                                ))}
                              </div>
                            )}
                          </article>
                        ))}
                      </div>

                      <div className="ppt-draft-actions">
                        <button className="ppt-secondary-btn" onClick={() => addDraftQuestion("short")} type="button">
                          <i className="ri-add-line"></i>
                          Add open-ended question
                        </button>
                        <button className="ppt-secondary-btn" onClick={() => addDraftQuestion("rating")} type="button">
                          <i className="ri-star-line"></i>
                          Add rating question
                        </button>
                      </div>
                    </div>

                    <aside className="ppt-ai-chat">
                      <div className="ppt-chat-log">
                        {chatMessages.map((message, index) => (
                          <div className={`ppt-chat-message ${message.role}`} key={`${message.role}-${index}`}>
                            {message.text}
                          </div>
                        ))}
                        {isChatting && (
                          <div className="ppt-chat-message assistant loading">
                            <i className="ri-loader-4-line"></i>
                            Updating...
                          </div>
                        )}
                      </div>
                      <div className="ppt-chat-box">
                        <textarea
                          value={aiMessage}
                          onChange={(event) => setAiMessage(event.target.value)}
                          placeholder="Enter editing instructions, e.g. add a rating question or shorten the questions"
                        />
                        <button className="ppt-primary-btn" onClick={handleAiRevise} disabled={isChatting || !aiMessage.trim()} type="button">
                          <i className="ri-send-plane-line"></i>
                          Send
                        </button>
                      </div>
                    </aside>
                  </div>
                ) : (
                  <div className="ppt-empty-state">
                    <i className="ri-file-text-line"></i>
                    <strong>Survey draft preview</strong>
                    <span>Upload a PPT or PDF and generate a draft to preview it here.</span>
                  </div>
                )}
              </div>
            </div>

            {pptDraft && (
              <footer className="ppt-modal-footer">
                {savedResult ? (
                  <div className="ppt-save-result">
                    <strong>Survey created: {savedResult.accessCode}</strong>
                    <span>{shareLink || "Creating survey link..."}</span>
                    <a href={buildSurveyFillPath(savedResult.accessCode)}>Test survey</a>
                  </div>
                ) : (
                  <span>Save the survey to get an invite code and a shareable survey link.</span>
                )}
                <button className="ppt-primary-btn" onClick={handleSaveDraft} disabled={isSavingDraft || Boolean(savedResult)} type="button">
                  <i className={isSavingDraft ? "ri-loader-4-line" : "ri-save-3-line"}></i>
                  {isSavingDraft ? "Saving…" : "Finish and save"}
                </button>
              </footer>
            )}
          </section>
        </div>
      )}
    </>
  );
}
