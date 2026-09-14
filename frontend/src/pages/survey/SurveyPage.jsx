import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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

export default function SurveyPage({ pptOnly = false }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { recordActivity } = useActivity();
  const [apiSurveys, setApiSurveys] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isPptModalOpen, setIsPptModalOpen] = useState(pptOnly);
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
    if (pptOnly) navigate("/survey");
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
      setPptError("請先上傳 PPT 或 PDF 檔案。");
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
          text: "已依教材內容建立問卷草稿，可直接編輯題目或用右側對話協助修改。",
        },
      ]);
    } catch (error) {
      console.error("Generate PPT survey failed:", error);
      const message = error?.message || "生成草稿失敗，請稍後再試。";
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
        { role: "assistant", text: "已依指令更新問卷草稿，請確認左側預覽內容。" },
      ]);
    } catch (error) {
      console.error("Revise PPT survey failed:", error);
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", text: error?.message || "這次修改沒有成功，請換個說法再試一次。" },
      ]);
    } finally {
      setIsChatting(false);
    }
  };

  const validateDraft = () => {
    if (!pptDraft?.title?.trim()) return "請輸入問卷標題。";
    if (!pptDraft.questions?.length) return "請至少保留一題。";
    if (pptDraft.questions.some((question) => !question.title.trim())) {
      return "請確認每一題都有題目文字。";
    }
    return "";
  };

  const handleSaveDraft = async () => {
    if (!user?.token) {
      setPptError("請先登入後再儲存問卷。");
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
        text: `建立 AI 教材問卷「${payload.title}」`,
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
      setPptError(error?.response?.data?.error || "儲存失敗，請稍後再試。");
    } finally {
      setIsSavingDraft(false);
    }
  };

  return (
    <>
      <Navbar />
      {(!pptOnly || !isPptModalOpen) && <main className="survey-page">
        <section className="survey-workspace">
          <div className="survey-intro">
            <div className="survey-hero-badge">
              <i className="ri-survey-line"></i>
              <span>問卷調查</span>
            </div>
            <h1 className="survey-hero-title">建立問卷與蒐集回饋</h1>
            <p className="survey-hero-subtitle">
              建立評分題與問答題，分享邀請碼給填答者，回收後可交由分析助理整理。
            </p>
          </div>

          <div className="survey-board">
            <a className="survey-entry-card create" href="/survey/create">
              <div className="entry-card-topline">
                <div className="entry-card-icon create-icon">
                  <i className="ri-edit-box-line"></i>
                </div>
                <span className="entry-card-kicker">手動建立</span>
              </div>
              <div className="entry-card-copy">
                <h2 className="entry-card-title">建立問卷</h2>
                <p className="entry-card-desc">
                  自訂題目、設定填答規則，產生邀請碼與專屬連結後即可開始收集回覆。
                </p>
              </div>
              <div className="entry-card-footer">
                <span className="entry-card-action">
                  前往建立
                  <i className="ri-arrow-right-line"></i>
                </span>
                <span className="entry-card-note">評分題 · 問答題 · 邀請碼</span>
              </div>
            </a>

            <aside className="survey-side-stack">
              <button
                className="survey-entry-card ppt-generate"
                onClick={() => navigate("/survey/ppt")}
                type="button"
              >
                <div className="entry-card-icon ppt-icon">
                  <i className="ri-slideshow-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">AI 生成</span>
                  <h2 className="entry-card-title">上傳 PPT/PDF 生成問卷</h2>
                  <p className="entry-card-desc">
                    依簡報或 PDF 重點產生相容草稿，講師可先編修，再儲存成正式問卷。
                  </p>
                </div>
                <span className="entry-card-arrow"><i className="ri-sparkling-line"></i></span>
              </button>

              <a className="survey-entry-card fill" href="/survey/fill">
                <div className="entry-card-icon fill-icon">
                  <i className="ri-file-list-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">填答入口</span>
                  <h2 className="entry-card-title">填寫問卷</h2>
                  <p className="entry-card-desc">輸入邀請碼即可開啟問卷並提交回饋內容。</p>
                </div>
                <span className="entry-card-arrow"><i className="ri-arrow-right-line"></i></span>
              </a>

              <section className="survey-activity-card">
                <div className="survey-activity-head">
                  <div>
                    <span className="entry-card-kicker">最近建立</span>
                    <h2>問卷紀錄</h2>
                    <p className="survey-activity-note">顯示近期建立的問卷與回覆狀態。</p>
                  </div>
                </div>

                {!user ? (
                  <div className="survey-activity-empty">
                    <i className="ri-lock-line"></i>
                    <span>登入後可查看近期問卷紀錄。</span>
                  </div>
                ) : isLoading ? (
                  <div className="survey-activity-empty">
                    <i className="ri-loader-4-line ri-spin"></i>
                    <span>載入問卷中...</span>
                  </div>
                ) : recentSurveys.length > 0 ? (
                  <div className="survey-activity-list">
                    {recentSurveys.map((survey) => {
                      const code = survey.code || survey.access_code;
                      return (
                        <a className="survey-activity-item" href={`/profile?survey=${encodeURIComponent(code)}`} key={code}>
                          <span className="survey-activity-dot"></span>
                          <div>
                            <strong>{survey.title || survey.survey_name || "未命名問卷"}</strong>
                            <span>
                              {survey.responses?.length || survey.response_count || 0} 份回覆 · {code}
                            </span>
                          </div>
                        </a>
                      );
                    })}
                  </div>
                ) : (
                  <div className="survey-activity-empty">
                    <i className="ri-time-line"></i>
                    <span>建立問卷後，這裡會顯示近期狀態。</span>
                  </div>
                )}
              </section>
            </aside>
          </div>
        </section>
      </main>}

      {isPptModalOpen && (
        <div className={`ppt-modal-backdrop ${pptOnly ? "ppt-page-backdrop" : ""}`} onClick={pptOnly ? undefined : closePptModal}>
          <section className="ppt-modal" onClick={(event) => event.stopPropagation()}>
            <header className="ppt-modal-header">
              <div>
                <span className="entry-card-kicker">教材 AI 問卷草稿</span>
                <h2>上傳 PPT/PDF 生成問卷</h2>
              </div>
              <button className="ppt-icon-btn" onClick={closePptModal} type="button" aria-label="關閉">
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
                  <strong>{pptFile ? pptFile.name : "選擇 PPT 或 PDF 檔案"}</strong>
                  <span>支援 .ppt、.pptx 與 .pdf</span>
                </label>

                <div className="ppt-field-grid">
                  <label className="ppt-field">
                    <span>題目數量</span>
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
                  <span>題型限制</span>
                  <label>
                    <input
                      type="checkbox"
                      checked={pptConfig.typeLimits.short}
                      onChange={(event) => updateTypeLimit("short", event.target.checked)}
                    />
                    問答題
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={pptConfig.typeLimits.rating}
                      onChange={(event) => updateTypeLimit("rating", event.target.checked)}
                    />
                    評分題
                  </label>
                </div>

                <button className="ppt-primary-btn" onClick={handleGenerateDraft} disabled={isGenerating} type="button">
                  <i className={isGenerating ? "ri-loader-4-line" : "ri-sparkling-line"}></i>
                  {isGenerating ? "生成中..." : "開始生成"}
                </button>

                {pptError && <p className="ppt-error">{pptError}</p>}
              </div>

              <div className="ppt-preview-panel">
                <div className="ppt-preview-main">
                  {isGenerating ? (
                  <div className="ppt-loading-state">
                    <i className="ri-loader-4-line"></i>
                    <strong>AI 正在整理教材重點</strong>
                    <span>正在連接正式 API，請稍候。</span>
                  </div>
                ) : pptDraft ? (
                  <div className="ppt-draft-layout">
                    <div className="ppt-draft-editor">
                      <div className="ppt-draft-meta">
                        <label className="ppt-field">
                          <span>問卷標題</span>
                          <input
                            value={pptDraft.title}
                            onChange={(event) => updateDraft({ title: event.target.value })}
                          />
                        </label>
                        <label className="ppt-field">
                          <span>問卷說明</span>
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
                                <option value="short">問答題</option>
                                <option value="rating">評分題</option>
                              </select>
                              <label>
                                <input
                                  type="checkbox"
                                  checked={question.required}
                                  onChange={(event) => updateDraftQuestion(question.id, { required: event.target.checked })}
                                />
                                必填
                              </label>
                              <button className="ppt-icon-btn" onClick={() => removeDraftQuestion(question.id)} type="button" aria-label="刪除題目">
                                <i className="ri-delete-bin-line"></i>
                              </button>
                            </div>
                            <input
                              className="ppt-question-title"
                              value={question.title}
                              onChange={(event) => updateDraftQuestion(question.id, { title: event.target.value })}
                              placeholder="輸入題目"
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
                          新增問答題
                        </button>
                        <button className="ppt-secondary-btn" onClick={() => addDraftQuestion("rating")} type="button">
                          <i className="ri-star-line"></i>
                          新增評分題
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
                            調整中...
                          </div>
                        )}
                      </div>
                      <div className="ppt-chat-box">
                        <textarea
                          value={aiMessage}
                          onChange={(event) => setAiMessage(event.target.value)}
                          placeholder="輸入修改指令，例如：增加一題評分題、題目更精簡"
                        />
                        <button className="ppt-primary-btn" onClick={handleAiRevise} disabled={isChatting || !aiMessage.trim()} type="button">
                          <i className="ri-send-plane-line"></i>
                          送出
                        </button>
                      </div>
                    </aside>
                  </div>
                ) : (
                  <div className="ppt-empty-state">
                    <i className="ri-file-text-line"></i>
                    <strong>問卷草稿預覽</strong>
                    <span>上傳 PPT 或 PDF 並開始生成後，草稿會顯示在這裡。</span>
                  </div>
                  )}
                </div>

                <div className="ppt-preview-settings">
                  <label className="ppt-field">
                    <span>題目方向</span>
                    <input
                      value={pptConfig.direction}
                      onChange={(event) => updatePptConfig({ direction: event.target.value })}
                      placeholder="例如：課後滿意度、學習成效"
                    />
                  </label>
                  <label className="ppt-field">
                    <span>生成重點</span>
                    <textarea
                      value={pptConfig.focus}
                      onChange={(event) => updatePptConfig({ focus: event.target.value })}
                      placeholder="例如：聚焦課程內容、講師表達、實務應用"
                    />
                  </label>
                </div>

                <div className="ppt-preview-actions">
                  <button className="ppt-secondary-btn" type="button">
                    <i className="ri-download-2-line"></i>
                    匯出
                  </button>
                </div>
              </div>
            </div>

            {pptDraft && (
              <footer className="ppt-modal-footer">
                {savedResult ? (
                  <div className="ppt-save-result">
                    <strong>已建立問卷：{savedResult.accessCode}</strong>
                    <span>{shareLink || "專屬連結產生中..."}</span>
                    <a href={buildSurveyFillPath(savedResult.accessCode)}>測試填答</a>
                  </div>
                ) : (
                  <span>儲存後會走原本問卷 API，自動取得邀請碼與專屬連結。</span>
                )}
                <button className="ppt-primary-btn" onClick={handleSaveDraft} disabled={isSavingDraft || Boolean(savedResult)} type="button">
                  <i className={isSavingDraft ? "ri-loader-4-line" : "ri-save-3-line"}></i>
                  {isSavingDraft ? "儲存中..." : "完成並儲存"}
                </button>
              </footer>
            )}
          </section>
        </div>
      )}
    </>
  );
}
