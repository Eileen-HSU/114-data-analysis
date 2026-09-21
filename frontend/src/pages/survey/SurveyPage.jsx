import InterfaceText from "../../components/feature/InterfaceText";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import axios from "axios";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useActivity } from "../../hooks/ActivityContext";
import { useAuth } from "../../hooks/AuthContext";
import { useLanguage } from "../../context/LanguageContext";
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
  typeCounts: {
    short: "",
    rating: "",
  },
};

const defaultTopicOptions = ["學習成效", "講師表達"];
const defaultFocusOptions = ["實務應用", "情境模擬"];

const PPT_DRAFT_STORAGE_PREFIX = "ppt-survey-draft:";

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
  const { language } = useLanguage();
  const t = (zh, en) => language === "en" ? en : zh;
  const navigate = useNavigate();
  const location = useLocation();
  // React may reuse this component while changing from /survey to /survey/ppt.
  // Derive the page mode from the current URL so the PPT workspace always
  // renders, even when the previous survey-page state is retained.
  const isPptPage = pptOnly || location.pathname === "/survey/ppt";
  const { isLoggedIn, user } = useAuth();
  const { recordActivity } = useActivity();
  const [apiSurveys, setApiSurveys] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isPptModalOpen, setIsPptModalOpen] = useState(isPptPage);
  const [pptFile, setPptFile] = useState(null);
  const [pptFileName, setPptFileName] = useState("");
  const [pptConfig, setPptConfig] = useState(defaultPptConfig);
  const [checkedTopics, setCheckedTopics] = useState([]);
  const [checkedFocus, setCheckedFocus] = useState([]);
  const [topicPreset, setTopicPreset] = useState("");
  const [focusPreset, setFocusPreset] = useState("");
  const [pptDraft, setPptDraft] = useState(null);
  const [pptError, setPptError] = useState("");
  const [pptTaskStatus, setPptTaskStatus] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [isChatting, setIsChatting] = useState(false);
  const [isAiChatMinimized, setIsAiChatMinimized] = useState(false);
  const [aiMessage, setAiMessage] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [savedResult, setSavedResult] = useState(null);
  const [shareLink, setShareLink] = useState("");
  const [isPptStorageReady, setIsPptStorageReady] = useState(false);
  const [isLeavePptDialogOpen, setIsLeavePptDialogOpen] = useState(false);
  const pptDraftStorageKey = `${PPT_DRAFT_STORAGE_PREFIX}${user?.user_id || user?.email || "current"}`;

  useEffect(() => {
    setIsPptModalOpen(isPptPage);
  }, [isPptPage]);

  useEffect(() => {
    setIsPptStorageReady(false);
    if (!isPptPage) return;

    try {
      const saved = JSON.parse(localStorage.getItem(pptDraftStorageKey) || "null");
      if (saved?.draft) setPptDraft(normalizeDraft(saved.draft));
      setPptFileName(saved?.fileName || "");
      if (saved?.config) {
        setPptConfig({
          ...defaultPptConfig,
          ...saved.config,
          typeCounts: { ...defaultPptConfig.typeCounts, ...saved.config.typeCounts },
        });
      }
      setCheckedTopics(Array.isArray(saved?.checkedTopics) ? saved.checkedTopics : []);
      setCheckedFocus(Array.isArray(saved?.checkedFocus) ? saved.checkedFocus : []);
      setTopicPreset(saved?.topicPreset || "");
      setFocusPreset(saved?.focusPreset || "");
      setChatMessages(Array.isArray(saved?.chatMessages) ? saved.chatMessages : []);
    } catch (error) {
      console.warn("Unable to restore PPT survey draft:", error);
    } finally {
      setIsPptStorageReady(true);
    }
  }, [isPptPage, pptDraftStorageKey]);

  useEffect(() => {
    if (!isPptPage || !isPptStorageReady) return;

    try {
      localStorage.setItem(pptDraftStorageKey, JSON.stringify({
        draft: pptDraft,
        fileName: pptFile?.name || pptFileName,
        config: pptConfig,
        checkedTopics,
        checkedFocus,
        topicPreset,
        focusPreset,
        chatMessages,
      }));
    } catch (error) {
      console.warn("Unable to save PPT survey draft:", error);
    }
  }, [isPptPage, pptDraftStorageKey, isPptStorageReady, pptDraft, pptFile, pptFileName, pptConfig, checkedTopics, checkedFocus, topicPreset, focusPreset, chatMessages]);

  useEffect(() => {
    if (!user?.token || isPptPage) {
      setApiSurveys([]);
      setIsLoading(false);
      return;
    }

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
  }, [user, isPptPage]);

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
    setPptFileName("");
    setPptConfig(defaultPptConfig);
    setCheckedTopics([]);
    setCheckedFocus([]);
    setTopicPreset("");
    setFocusPreset("");
    setPptDraft(null);
    setPptError("");
    setPptTaskStatus("");
    setIsGenerating(false);
    setIsChatting(false);
    setIsAiChatMinimized(false);
    setAiMessage("");
    setChatMessages([]);
    setIsSavingDraft(false);
    setSavedResult(null);
    setShareLink("");
  };

  const hasUnimportedPptWork = () => Boolean(
    pptFile || pptFileName || pptDraft || pptConfig.direction || pptConfig.focus ||
    pptConfig.typeCounts.short !== "" || pptConfig.typeCounts.rating !== ""
  );

  const finishLeavingPptPage = () => {
    try {
      localStorage.removeItem(pptDraftStorageKey);
    } catch (error) {
      console.warn("Unable to clear PPT survey draft:", error);
    }
    setIsLeavePptDialogOpen(false);
    setIsPptModalOpen(false);
    resetPptModal();
    if (isPptPage) navigate("/survey");
  };

  const leavePptPage = () => {
    if (!savedResult && hasUnimportedPptWork()) {
      setIsLeavePptDialogOpen(true);
      return;
    }
    finishLeavingPptPage();
  };

  const closePptModal = () => {
    if (isPptPage) {
      leavePptPage();
      return;
    }
    setIsPptModalOpen(false);
    resetPptModal();
  };

  const updatePptConfig = (patch) => {
    setPptConfig((prev) => ({ ...prev, ...patch }));
  };

  const updateTypeCount = (type, value) => {
    if (value === "") {
      setPptConfig((prev) => ({
        ...prev,
        typeCounts: { ...prev.typeCounts, [type]: "" },
      }));
      return;
    }
    const parsed = Number.parseInt(value, 10);
    const count = Number.isFinite(parsed) ? Math.max(0, Math.min(20, parsed)) : 0;
    setPptConfig((prev) => ({
      ...prev,
      typeCounts: { ...prev.typeCounts, [type]: count },
    }));
  };

  const selectPptPreset = (kind, value) => {
    const isTopic = kind === "topic";
    const setPreset = isTopic ? setTopicPreset : setFocusPreset;
    const setChecked = isTopic ? setCheckedTopics : setCheckedFocus;
    const field = isTopic ? "direction" : "focus";
    setPreset(value);
    setChecked(value && value !== "other" ? [value] : []);
    if (value !== "other") updatePptConfig({ [field]: "" });
  };

  const composeSemanticField = (inputText, checkedValues, inputLabel, presetLabel) => {
    const input = String(inputText || "").trim();
    const checked = checkedValues.filter(Boolean);

    if (input && checked.length) {
      return `${inputLabel}：${input}。${presetLabel}：${checked.join("、")}。`;
    }
    if (input) {
      return `${inputLabel}：${input}。`;
    }
    if (checked.length) {
      return `${presetLabel}：${checked.join("、")}。`;
    }
    return "";
  };

  const buildPptAiConfig = () => ({
    ...pptConfig,
    direction: composeSemanticField(
      pptConfig.direction,
      checkedTopics,
      "自行輸入題目方向",
      "預設參考方向",
    ),
    focus: composeSemanticField(
      pptConfig.focus,
      checkedFocus,
      "自行輸入生成重點",
      "預設參考重點",
    ),
  });

  const buildAiRevisionMessage = (message) => {
    const direction = composeSemanticField(
      pptConfig.direction,
      checkedTopics,
      "目前自行輸入題目方向",
      "目前預設參考方向",
    );
    const focus = composeSemanticField(
      pptConfig.focus,
      checkedFocus,
      "目前自行輸入生成重點",
      "目前預設參考重點",
    );
    const context = [direction, focus].filter(Boolean).join("\n");
    return context ? `${message}\n\n${context}` : message;
  };

  const handleGenerateDraft = async () => {
    if (!pptFile) {
      setPptError("請先上傳 PPT 或 PDF 檔案。");
      return;
    }

    const totalQuestionCount = Number(pptConfig.typeCounts.short || 0) + Number(pptConfig.typeCounts.rating || 0);
    if (totalQuestionCount < 1) {
      setPptError(t("請至少填寫一種題型的題數。", "Enter a question count for at least one type."));
      return;
    }

    setPptError("");
    setPptTaskStatus("正在建立背景任務...");
    setIsGenerating(true);
    setSavedResult(null);
    setShareLink("");

    try {
      const draft = await generateSurveyFromPpt({
        file: pptFile,
        config: buildPptAiConfig(),
        token: user?.token,
        onProgress: (task) => {
          setPptTaskStatus(task?.message || `任務狀態：${task?.status || "processing"}`);
        },
      });
      const normalizedDraft = normalizeDraft(draft);
      setPptDraft(normalizedDraft);
      try {
        const existing = JSON.parse(localStorage.getItem(pptDraftStorageKey) || "{}");
        localStorage.setItem(pptDraftStorageKey, JSON.stringify({ ...existing, draft: normalizedDraft }));
      } catch (storageError) {
        console.warn("Unable to save generated PPT survey draft:", storageError);
      }
      setPptTaskStatus("");
      setChatMessages([
        {
          role: "assistant",
          text: "已依教材內容建立問卷草稿，可直接編輯題目或用右側對話協助修改。",
        },
      ]);
    } catch (error) {
      console.error("Generate PPT survey failed:", error);
      const message = error?.message || "生成草稿失敗，請稍後再試。";
      setPptTaskStatus("");
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
        message: buildAiRevisionMessage(message),
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

      return savedSurvey;
    } catch (error) {
      console.error("Save PPT survey failed:", error);
      setPptError(error?.response?.data?.error || "儲存失敗，請稍後再試。");
    } finally {
      setIsSavingDraft(false);
    }
  };

  const handleImportToSystemSurvey = async () => {
    const savedSurvey = await handleSaveDraft();
    if (!savedSurvey) return;

    try {
      localStorage.removeItem(pptDraftStorageKey);
    } catch (error) {
      console.warn("Unable to clear imported PPT survey draft:", error);
    }

    navigate("/survey", {
      replace: true,
      state: { importedSurvey: savedSurvey.title },
    });
  };

  if (isPptPage && !isLoggedIn) {
    return (
      <>
        <Navbar />
        <div className="survey-page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <LoginRequiredModal
            message="請先登入後再使用 PPT/PDF 產生問卷功能。"
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/survey")}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      {(!isPptPage || !isPptModalOpen) && <main className="survey-page">
        <section className="survey-workspace" data-localized>
          <div className="survey-intro">
            <div className="survey-hero-badge">
              <i className="ri-survey-line"></i>
              <span>Surveys</span>
            </div>
              <h1 className="survey-hero-title">{t("建立問卷與蒐集回饋","Create surveys and collect feedback")}</h1>
              <p className="survey-hero-subtitle">
                {t(
                  "建立評分題與問答題，分享邀請碼給填答者，回收後可交由分析助理整理。",
                  "Create rating and open-ended questions, share an invite code with respondents, and have the Analysis Assistant summarize results after collection."
                )}
              </p>
          </div>

          <div className="survey-board">
            <a className="survey-entry-card create" href="/survey/create">
                <div className="entry-card-topline">
                <div className="entry-card-icon create-icon">
                  <i className="ri-edit-box-line"></i>
                </div>
                <span className="entry-card-kicker">{t("手動建立","Manual creation")}</span>
              </div>
              <div className="entry-card-copy">
                <h2 className="entry-card-title">{t("建立問卷","Create survey")}</h2>
                <p className="entry-card-desc">
                  {t(
                    "自訂題目、設定填答規則，產生邀請碼與專屬連結後即可開始收集回覆。",
                    "Customize questions and response rules, then generate an access code and unique link to start collecting responses."
                  )}
                </p>
              </div>
              <div className="entry-card-footer">
                <span className="entry-card-action">
                  {t("前往建立","Go to create")}
                  <i className="ri-arrow-right-line"></i>
                </span>
                <span className="entry-card-note">{t("評分題 · 問答題 · 邀請碼","Rating · Open-ended · Access code")}</span>
              </div>
            </a>

            <aside className="survey-side-stack">
              <a
                className="survey-entry-card ppt-generate"
                href="/survey/ppt"
                onClick={(event) => {
                  event.preventDefault();
                  navigate("/survey/ppt");
                  window.setTimeout(() => {
                    if (window.location.pathname !== "/survey/ppt") {
                      window.location.assign("/survey/ppt");
                    }
                  }, 0);
                }}
                aria-label={t("上傳 PPT/PDF 生成問卷", "Generate a survey from PPT/PDF")}
              >
                <div className="entry-card-icon ppt-icon">
                  <i className="ri-slideshow-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">{t("AI 生成","AI generation")}</span>
                  <h2 className="entry-card-title">{t("上傳 PPT/PDF 生成問卷","Generate a survey from PPT/PDF")}</h2>
                  <p className="entry-card-desc">{t("依簡報或 PDF 重點產生相容草稿，講師可先編修，再儲存成正式問卷。","Create an editable draft from a presentation or PDF; instructors can edit first, then save as a survey.")}</p>
                </div>
                <span className="entry-card-arrow"><i className="ri-sparkling-line"></i></span>
              </a>

              <a className="survey-entry-card fill" href="/survey/fill">
                <div className="entry-card-icon fill-icon">
                  <i className="ri-file-list-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">{t("填答入口","Response entry")}</span>
                  <h2 className="entry-card-title">{t("填寫問卷","Complete survey")}</h2>
                  <p className="entry-card-desc">{t("輸入邀請碼即可開啟問卷並提交回饋內容。","Enter an invite code to open a survey and submit feedback.")}</p>
                </div>
                <span className="entry-card-arrow"><i className="ri-arrow-right-line"></i></span>
              </a>

              <section className="survey-activity-card">
                <div className="survey-activity-head">
                  <div>
                    <span className="entry-card-kicker">{t("最近建立","Recently created")}</span>
                    <h2>{t("問卷紀錄","Survey history")}</h2>
                    <p className="survey-activity-note">{t("顯示近期建立的問卷與回覆狀態。","Displays recently created surveys and response status.")}</p>
                  </div>
                </div>

                {!user ? (
                  <div className="survey-activity-empty">
                    <i className="ri-lock-line"></i>
                    <span>{t("登入後可查看近期問卷紀錄。","Log in to see recent surveys.")}</span>
                  </div>
                ) : isLoading ? (
                  <div className="survey-activity-empty">
                    <i className="ri-loader-4-line ri-spin"></i>
                    <span>{t("載入問卷中...","Loading surveys...")}</span>
                  </div>
                ) : recentSurveys.length > 0 ? (
                  <div className="survey-activity-list">
                    {recentSurveys.map((survey) => {
                      const code = survey.code || survey.access_code;
                      return (
                        <a className="survey-activity-item" href={`/profile?survey=${encodeURIComponent(code)}`} key={code}>
                          <span className="survey-activity-dot"></span>
                          <div>
                                    <strong>{survey.title || survey.survey_name || t("未命名問卷","Untitled survey")}</strong>
                                    <span>
                                      {survey.responses?.length || survey.response_count || 0} {t("份回覆","responses")} · {code}
                                    </span>
                          </div>
                        </a>
                      );
                    })}
                  </div>
                ) : (
                  <div className="survey-activity-empty">
                    <i className="ri-time-line"></i>
                    <span>{t("建立問卷後，這裡會顯示近期狀態。","After you create surveys, recent status will appear here.")}</span>
                  </div>
                )}
              </section>
            </aside>
          </div>
        </section>
      </main>}

      {isPptModalOpen && (
        <div className={`ppt-modal-backdrop ${isPptPage ? "ppt-page-backdrop" : ""}`} onClick={isPptPage ? undefined : closePptModal}>
          <section className="ppt-modal" onClick={(event) => event.stopPropagation()}>
            {isPptPage && (
              <nav className="ppt-page-breadcrumb" aria-label={t("頁面導覽", "Page navigation")}>
                <button type="button" onClick={leavePptPage}>
                  <i className="ri-arrow-left-line"></i>
                  {t("返回問卷中心", "Back to survey center")}
                </button>
                <span aria-hidden="true">|</span>
                <strong>{t("上傳 PPT/PDF 生成問卷", "Generate a survey from PPT/PDF")}</strong>
              </nav>
            )}
            <header className="ppt-modal-header">
              <div>
                <span className="entry-card-kicker">{t("教材 AI 問卷草稿","PPT AI survey draft")}</span>
                <h2>{t("上傳 PPT/PDF 生成問卷","Generate a survey from PPT/PDF")}</h2>
              </div>
              <button className="ppt-icon-btn" onClick={closePptModal} type="button" aria-label={t("關閉","Close")}> 
                <i className="ri-close-line"></i>
              </button>
            </header>

            <div className={`ppt-modal-body ${(isPptPage || pptDraft) ? "ppt-modal-body-with-chat" : ""}`}>
              <div className="ppt-main-editor-column">
              <div className="ppt-config-panel">
                <label className="ppt-upload-zone">
                  <input
                    type="file"
                    accept=".ppt,.pptx,.pdf,application/pdf,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    onChange={(event) => {
                      const selectedFile = event.target.files?.[0] || null;
                      setPptFile(selectedFile);
                      setPptFileName(selectedFile?.name || "");
                    }}
                  />
                  <i className="ri-upload-cloud-2-line"></i>
                  <strong>{pptFile?.name || pptFileName || t("選擇 PPT 或 PDF 檔案","Choose a PPT or PDF file")}</strong>
                  <span>{t("支援 .ppt、.pptx 與 .pdf","Supports .ppt, .pptx and .pdf")}</span>
                </label>

                <div className="ppt-quick-settings">
                  <div className="ppt-field-grid">
                    <label className="ppt-field">
                      <span>{t("問答題：","Short answer:")}</span>
                      <input
                        type="number"
                        min="0"
                        max="20"
                        value={pptConfig.typeCounts.short}
                        onChange={(event) => updateTypeCount("short", event.target.value)}
                      />
                    </label>
                    <label className="ppt-field">
                      <span>{t("評分題：","Rating:")}</span>
                      <input
                        type="number"
                        min="0"
                        max="20"
                        value={pptConfig.typeCounts.rating}
                        onChange={(event) => updateTypeCount("rating", event.target.value)}
                      />
                    </label>
                  </div>
                </div>

                <div className="ppt-generation-preferences">
                  <label className="ppt-field">
                    <span>{t("題目方向", "Survey direction")}</span>
                    <select value={topicPreset} onChange={(event) => selectPptPreset("topic", event.target.value)}>
                      <option value="">{t("請選擇方向", "Choose a direction")}</option>
                      {defaultTopicOptions.map((option) => <option value={option} key={option}>{option}</option>)}
                      <option value="other">{t("其他（自行填寫）", "Other (enter your own)")}</option>
                    </select>
                  </label>
                  {topicPreset === "other" && <label className="ppt-field"><span>{t("其他題目方向", "Other survey direction")}</span><textarea rows={2} value={pptConfig.direction} onChange={(event) => updatePptConfig({ direction: event.target.value })} placeholder={t("請輸入題目方向", "Enter a survey direction")} /></label>}
                  <label className="ppt-field">
                    <span>{t("生成重點", "Focus")}</span>
                    <select value={focusPreset} onChange={(event) => selectPptPreset("focus", event.target.value)}>
                      <option value="">{t("請選擇重點", "Choose a focus")}</option>
                      {defaultFocusOptions.map((option) => <option value={option} key={option}>{option}</option>)}
                      <option value="other">{t("其他（自行填寫）", "Other (enter your own)")}</option>
                    </select>
                  </label>
                  {focusPreset === "other" && <label className="ppt-field"><span>{t("其他生成重點", "Other focus")}</span><textarea rows={2} value={pptConfig.focus} onChange={(event) => updatePptConfig({ focus: event.target.value })} placeholder={t("請輸入生成重點", "Enter a focus")} /></label>}
                </div>

                <button className="ppt-primary-btn" onClick={handleGenerateDraft} disabled={isGenerating} type="button">
                  <i className={isGenerating ? "ri-loader-4-line" : "ri-sparkling-line"}></i>
                  {isGenerating ? t("生成中...","Generating...") : t("開始生成","Start generating")}
                </button>

                {pptError && <p className="ppt-error">{pptError}</p>}
              </div>

              <div className="ppt-preview-panel">
                <div className="ppt-preview-main">
                  {isGenerating ? (
                  <div className="ppt-loading-state">
                    <i className="ri-loader-4-line"></i>
                    <strong>{t("AI 正在整理教材重點","AI is summarizing presentation highlights")}</strong>
                    <span>{pptTaskStatus || t("背景任務處理中，系統會自動查詢結果。","Background task running; system will automatically fetch results.")}</span>
                  </div>
                ) : pptDraft ? (
                  <div className="ppt-draft-layout">
                    <div className="ppt-draft-editor">
                      <div className="ppt-draft-meta">
                        <label className="ppt-field">
                          <span>{t("問卷標題","Survey title")}</span>
                          <textarea
                            className="ppt-draft-title-input w-full resize-y break-words whitespace-normal overflow-y-auto p-3 leading-relaxed outline-none focus:ring"
                            rows={2}
                            value={pptDraft.title}
                            onChange={(event) => updateDraft({ title: event.target.value })}
                          />
                        </label>
                        <label className="ppt-field">
                          <span>{t("問卷說明","Survey description")}</span>
                          <textarea
                            className="ppt-draft-description-input w-full resize-y break-words whitespace-normal overflow-y-auto p-3 leading-relaxed outline-none focus:ring"
                            rows={4}
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
                                <option value="short">{t("問答題","Short answer")}</option>
                                <option value="rating">{t("評分題","Rating")}</option>
                              </select>
                              <label>
                                <input
                                  type="checkbox"
                                  checked={question.required}
                                  onChange={(event) => updateDraftQuestion(question.id, { required: event.target.checked })}
                                />
                                {t("必填","Required")}
                              </label>
                              <button className="ppt-icon-btn" onClick={() => removeDraftQuestion(question.id)} type="button" aria-label={t("刪除題目","Delete question")}>
                                <i className="ri-delete-bin-line"></i>
                              </button>
                            </div>
                            <textarea
                              className="ppt-question-title w-full resize-y break-words whitespace-normal overflow-y-auto p-3 leading-relaxed outline-none focus:ring"
                              rows={3}
                              value={question.title}
                              onChange={(event) => updateDraftQuestion(question.id, { title: event.target.value })}
                              placeholder={t("輸入題目","Enter question")}
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
                        <button className="ppt-secondary-btn" onClick={() => addDraftQuestion("short") } type="button">
                          <i className="ri-add-line"></i>
                          {t("新增問答題","Add short answer")}
                        </button>
                        <button className="ppt-secondary-btn" onClick={() => addDraftQuestion("rating") } type="button">
                          <i className="ri-star-line"></i>
                          {t("新增評分題","Add rating question")}
                        </button>
                      </div>
                    </div>

                  </div>
                ) : (
                  <div className="ppt-empty-state">
                    <i className="ri-file-text-line"></i>
                    <strong>{t("問卷草稿預覽","Draft preview")}</strong>
                    <span>{t("上傳 PPT 或 PDF 並開始生成後，草稿會顯示在這裡。","Upload a PPT or PDF and start generating; the draft will appear here.")}</span>
                  </div>
                  )}
                </div>

                <div className="ppt-preview-actions">
                  <button className="ppt-secondary-btn" onClick={handleImportToSystemSurvey} disabled={!pptDraft || isSavingDraft || Boolean(savedResult)} type="button">
                    <i className={isSavingDraft ? "ri-loader-4-line" : "ri-upload-2-line"}></i>
                    {t("匯入系統問卷","Import into system surveys")}
                  </button>
                </div>
              </div>
              </div>
              {(isPptPage || pptDraft) && (
                <aside className={`ppt-floating-chat ${isAiChatMinimized ? "is-minimized" : ""}`}>
                  <header className="ppt-floating-chat-header">
                    <div>
                      <strong>{t("AI 對話", "AI Chat")}</strong>
                      <span>{t("調整問卷草稿", "Refine draft")}</span>
                    </div>
                    <button
                      className="ppt-floating-chat-toggle"
                      onClick={() => setIsAiChatMinimized((prev) => !prev)}
                      type="button"
                      aria-label={isAiChatMinimized ? t("展開對話", "Expand chat") : t("最小化對話", "Minimize chat")}
                    >
                      <i className={isAiChatMinimized ? "ri-add-line" : "ri-subtract-line"}></i>
                    </button>
                  </header>

                  {!isAiChatMinimized && (
                    <>
                      <div className="ppt-floating-chat-log">
                        {!pptDraft ? (
                          <div className="ppt-chat-message assistant">
                            {t("完成生成問卷草稿後，即可使用 AI 對話協助修改題目。", "Generate a survey draft first, then use AI Chat to refine the questions.")}
                          </div>
                        ) : chatMessages.map((message, index) => (
                            <div className={`ppt-chat-message ${message.role}`} key={`${message.role}-${index}`}>
                              {message.text}
                            </div>
                          ))}
                        {isChatting && (
                          <div className="ppt-chat-message assistant loading">
                            <i className="ri-loader-4-line"></i>
                            {t("調整中...", "Adjusting...")}
                          </div>
                        )}
                      </div>
                      <div className="ppt-floating-chat-input">
                        <textarea
                          className="w-full resize-y break-words whitespace-normal overflow-y-auto p-3 leading-relaxed outline-none focus:ring"
                          value={aiMessage}
                          onChange={(event) => setAiMessage(event.target.value)}
                          placeholder={t("輸入修改指令，例如：增加一題評分題、題目更精簡", "Enter an edit command, e.g.: add a rating question, shorten questions")}
                          disabled={!pptDraft}
                        />
                        <button className="ppt-primary-btn" onClick={handleAiRevise} disabled={!pptDraft || isChatting || !aiMessage.trim()} type="button">
                          <i className="ri-send-plane-line"></i>
                          {t("送出", "Send")}
                        </button>
                      </div>
                    </>
                  )}
                </aside>
              )}
            </div>

          </section>
        </div>
      )}

      {isLeavePptDialogOpen && (
        <div className="ppt-leave-dialog-backdrop" role="presentation">
          <section className="ppt-leave-dialog" role="dialog" aria-modal="true" aria-labelledby="ppt-leave-dialog-title">
            <div className="ppt-leave-dialog-icon"><i className="ri-draft-line"></i></div>
            <div>
              <h2 id="ppt-leave-dialog-title">{t("尚未匯入系統問卷", "Survey not imported yet")}</h2>
              <p>{t("離開後目前的 PPT 問卷草稿將不會保存。確定要離開嗎？", "Leaving will discard the current PPT survey draft. Are you sure you want to leave?")}</p>
            </div>
            <div className="ppt-leave-dialog-actions">
              <button className="ppt-secondary-btn" type="button" onClick={() => setIsLeavePptDialogOpen(false)}>{t("繼續編輯", "Keep editing")}</button>
              <button className="ppt-danger-btn" type="button" onClick={finishLeavingPptPage}>{t("不保存並離開", "Discard and leave")}</button>
            </div>
          </section>
        </div>
      )}

    </>
  );
}
