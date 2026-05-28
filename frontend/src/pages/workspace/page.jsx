import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import { useActivity } from "../../hooks/ActivityContext";
import { apiUrl } from "../../lib/api";
import "./workspace.css";

const WELCOME_MSG = {
  id: "welcome",
  role: "assistant",
  content:
    "您好！我是 DataAnalysis AI 助手。請上傳您的資料檔案（CSV、Excel、JSON 或 TXT），或直接輸入您的分析問題，我將為您提供深度洞察。",
};
const ACTIVE_WORKSPACE_KEY = "dataanalysis_active_workspace";
const EMPTY_SURVEY_TABLE_MARKER = "[[EMPTY_SURVEY_TABLE]]";

function getAuthHeader() {
  try {
    const user = JSON.parse(localStorage.getItem("dataanalysis_auth"));
    const token = user?.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

function normalizeSurveyDetail(survey) {
  const code = survey?.code || survey?.access_code;
  return {
    ...survey,
    id: survey?.id || survey?.template_id || code,
    title: survey?.title || survey?.survey_name || "未命名問卷",
    code,
    createdAt: survey?.createdAt || survey?.created_at || "",
    questions: Array.isArray(survey?.questions) ? survey.questions : [],
    responses: Array.isArray(survey?.responses) ? survey.responses : [],
  };
}

function getStoredSurveyRecords(user, apiSurveys = []) {
  let surveys = [];
  try {
    const stored = JSON.parse(localStorage.getItem("surveys") || "{}");
    surveys = Object.values(stored || {});
  } catch {
    surveys = [];
  }

  const localRecords = surveys
    .filter((survey) => {
      if (!user) return false;
      if (!survey.ownerId && !survey.ownerEmail) return false;
      return survey.ownerId === user?.user_id || survey.ownerEmail === user?.email;
    })
    .map((survey) => ({
      id: survey.id || survey.code,
      title: survey.title,
      code: survey.code,
      createdAt: survey.createdAt,
      responseCount: survey.responses?.length || 0,
      detail: survey,
    }));

  const backendRecords = apiSurveys
    .map(normalizeSurveyDetail)
    .filter((survey) => survey.code)
    .map((survey) => ({
      id: survey.id,
      title: survey.title,
      code: survey.code,
      createdAt: survey.createdAt,
      responseCount: survey.responses.length,
      detail: survey,
    }));
  const backendCodes = new Set(backendRecords.map((survey) => survey.code).filter(Boolean));
  const uniqueLocalRecords = localRecords.filter((survey) => !backendCodes.has(survey.code));

  return [...backendRecords, ...uniqueLocalRecords];
}

function buildSurveyChatContent(survey) {
  const detail = normalizeSurveyDetail(survey);
  const ratingQuestions = detail.questions.filter((q) => (q.type || q.question_type) === "rating");
  const textQuestions = detail.questions.filter((q) => (q.type || q.question_type) !== "rating");
  const lines = [];
  lines.push(`📋 問卷名稱：${detail.title}`);
  lines.push(`🔑 問卷代碼：${detail.code}`);
  lines.push(`📅 建立日期：${detail.createdAt}`);
  lines.push(`👥 回覆人數：${detail.responses.length} 人`);
  lines.push(`❓ 題目數量：${detail.questions.length} 道`);
  lines.push("");
  if (ratingQuestions.length > 0) {
    lines.push("── 評分題統計 ──");
    ratingQuestions.forEach((q) => {
      const qId = q.id !== undefined ? q.id : q.question_id;
      let total = 0;
      let cnt = 0;
      detail.responses.forEach((r) => {
        const v = Number(r.answers?.[qId]);
        if (!isNaN(v) && r.answers?.[qId] !== "") { total += v; cnt++; }
      });
      const avg = cnt > 0 ? (total / cnt).toFixed(1) : "無資料";
      lines.push(`Q${detail.questions.indexOf(q) + 1}. ${q.title || q.question_title}`);
      lines.push(`   平均分：${avg} / 5（${cnt} 人作答）`);
    });
    lines.push("");
  }
  if (textQuestions.length > 0) {
    lines.push("── 問答題回覆 ──");
    textQuestions.forEach((q) => {
      const qId = q.id !== undefined ? q.id : q.question_id;
      const answers = detail.responses
        .map((response) => ({
          answer: response.answers?.[qId],
          respondentIdentity: response.respondentIdentity || response.respondent_identity,
        }))
        .filter(({ answer }) => answer && (Array.isArray(answer) ? answer.length > 0 : answer !== ""));
      lines.push(`Q${detail.questions.indexOf(q) + 1}. ${q.title || q.question_title}（${answers.length} 人回答）`);
      answers.forEach(({ answer, respondentIdentity }, i) => {
        const text = Array.isArray(answer) ? answer.join("、") : String(answer);
        const identityLabel = respondentIdentity ? `填答人：${respondentIdentity}，` : "";
        lines.push(`   ${i + 1}. ${identityLabel}${text}`);
      });
      lines.push("");
    });
  }
  lines.push("請根據以上問卷資料，幫我進行深度分析，包含：關鍵發現、趨勢洞察、以及改善建議。");
  return lines.join("\n");
}

function hasAnswerValue(answer) {
  if (Array.isArray(answer)) return answer.length > 0;
  return answer !== undefined && answer !== null && String(answer).trim() !== "";
}

function getSurveyStats(survey) {
  const detail = normalizeSurveyDetail(survey);
  const questions = detail.questions;
  const responses = detail.responses;
  const ratingQuestions = questions.filter((q) => (q.type || q.question_type) === "rating");
  const textQuestions = questions.filter((q) => (q.type || q.question_type) !== "rating");
  const answeredValues = [];
  const ratingValues = [];
  const textAnswers = [];

  responses.forEach((response) => {
    questions.forEach((question) => {
      const qId = question.id !== undefined ? question.id : question.question_id;
      const answer = response.answers?.[qId];
      if (!hasAnswerValue(answer)) return;
      answeredValues.push(answer);
      if ((question.type || question.question_type) === "rating") {
        const value = Number(answer);
        if (!Number.isNaN(value)) ratingValues.push(value);
        return;
      }
      textAnswers.push(Array.isArray(answer) ? answer.join("、") : String(answer));
    });
  });

  const ratingAverage = ratingValues.length
    ? (ratingValues.reduce((sum, value) => sum + value, 0) / ratingValues.length).toFixed(1)
    : null;

  return {
    questions,
    responses,
    ratingQuestions,
    textQuestions,
    answeredValues,
    ratingAverage,
    textAnswers,
  };
}

function isSurveyContentTooSmall(stats) {
  return stats.questions.length === 0 || stats.responses.length < 2 || stats.answeredValues.length < 2;
}

function buildSurveyAnalysisReplyFromSurvey(survey, fallbackTitle = "問卷") {
  const stats = getSurveyStats(survey);
  const title = survey?.title || survey?.survey_name || fallbackTitle;
  const intro = `我已收到「${title}」的問卷資料，以下是初步分析結果：`;

  if (isSurveyContentTooSmall(stats)) {
    return `${EMPTY_SURVEY_TABLE_MARKER}\n${intro}`;
  }

  const rows = [];
  if (stats.ratingQuestions.length > 0) {
    rows.push(`評分題洞察：共 ${stats.ratingQuestions.length} 題評分題，平均分為 ${stats.ratingAverage ?? "無資料"} / 5，可優先觀察低於平均的題目。`);
  }
  if (stats.textQuestions.length > 0) {
    const sampleTitle = stats.textQuestions[0]?.title || stats.textQuestions[0]?.question_title;
    const sampleQuestion = sampleTitle ? `「${sampleTitle}」` : "開放題";
    rows.push(`問答題主題分析：共收集 ${stats.textAnswers.length} 筆文字回覆，可先從 ${sampleQuestion} 的常見關鍵字整理主要意見。`);
  }
  rows.push(`回覆概況：目前共有 ${stats.responses.length} 位填答者、${stats.questions.length} 道題目，已累積 ${stats.answeredValues.length} 筆可分析答案。`);
  rows.push("改善建議：建議後續比較不同題型或族群的差異，並針對低分題與高頻文字回覆安排追問。");

  return `${intro}\n\n${rows.join("\n")}`;
}

function parseBuiltInSurveyText(content) {
  const isEmojiSurvey = content.includes("📋 問卷名稱：") && content.includes("🔑 問卷代碼：");
  const isProfileSurvey = content.includes("問卷：") && content.includes("邀請碼：") && content.includes("回覆數：");
  if (!isEmojiSurvey && !isProfileSurvey) return null;

  const title = (isEmojiSurvey
    ? content.match(/📋 問卷名稱：(.+)/)?.[1]
    : content.match(/問卷：(.+)/)?.[1])?.trim() || "問卷";
  const responseCount = Number((isEmojiSurvey
    ? content.match(/👥 回覆人數：(\d+)/)?.[1]
    : content.match(/回覆數：(\d+)/)?.[1]) || 0);
  const questionCount = Number((isEmojiSurvey
    ? content.match(/❓ 題目數量：(\d+)/)?.[1]
    : (content.match(/^Q\d+\./gm) || []).length) || 0);
  const answerCount = (content.match(/^\s+\d+\.\s+/gm) || []).length;
  const hasRating = content.includes("── 評分題統計 ──") || /^\s+\d+\.\s*[0-5](?:\.0)?\s*$/m.test(content);
  const hasText = content.includes("── 問答題回覆 ──") || answerCount > 0;
  return { title, responseCount, questionCount, answerCount, hasRating, hasText };
}

function buildSurveyAnalysisReplyFromText(content) {
  const survey = parseBuiltInSurveyText(content);
  if (!survey) return null;
  const intro = `我已收到「${survey.title}」的問卷資料，以下是初步分析結果：`;

  if (survey.questionCount === 0 || survey.answerCount < 2) {
    return `${EMPTY_SURVEY_TABLE_MARKER}\n${intro}`;
  }

  const rows = [];
  if (survey.hasRating) {
    rows.push("評分題洞察：已偵測到評分題資料，可依各題平均分比較滿意度與落差。");
  }
  if (survey.hasText) {
    rows.push(`問答題主題分析：已偵測到 ${survey.answerCount} 筆文字回覆，可整理高頻主題與正負向意見。`);
  }
  rows.push(`回覆概況：目前共有 ${survey.responseCount} 位填答者、${survey.questionCount} 道題目，可進行初步趨勢判讀。`);
  rows.push("改善建議：建議補充分群欄位或提高回覆數，以提升分析可信度。");

  return `${intro}\n\n${rows.join("\n")}`;
}

function isGreetingInput(text) {
  const normalized = text.trim().toLowerCase().replace(/[，。！？、,.!?\s]/g, "");
  return ["hi", "hello", "hey", "你好", "哈囉", "嗨", "您好"].includes(normalized);
}

function buildAssistantReply(content, surveyDetail = null, surveyTitle = "問卷") {
  if (surveyDetail) return buildSurveyAnalysisReplyFromSurvey(surveyDetail, surveyTitle);
  if (isGreetingInput(content)) return "您好！很高興見到您，請提供要分析的資料或選擇系統內建問卷，我會協助您整理重點。";
  const surveyReply = buildSurveyAnalysisReplyFromText(content);
  if (surveyReply) return surveyReply;
  return "資料不足，無法進行有效分析。請提供系統內建問卷、完整資料檔案，或更明確的分析問題。";
}

function cleanMessageText(text) {
  return text
    .replace(/\*\*/g, "")
    .replace(/^[\s\-•]+/, "")
    .trim();
}

function parseAssistantTableRows(content) {
  const rows = [];
  const introLines = [];
  let currentSection = "";
  let isSuggestionSection = false;
  const visibleContent = content.replace(EMPTY_SURVEY_TABLE_MARKER, "");

  const isSuggestionLabel = (value) => ["建議", "可進一步詢問"].includes(value.replace(/[💡]/g, "").trim());

  visibleContent.split("\n").forEach((rawLine) => {
    const line = cleanMessageText(rawLine);
    if (!line) return;

    if (line.startsWith("我已收到")) {
      introLines.push(line);
      return;
    }

    if (isSuggestionSection) return;

    const numbered = line.match(/^(\d+)\.\s*(.+)$/);
    const bullet = line.match(/^[-]\s*(.+)$/);
    const colonIndex = line.indexOf("：");

    if (colonIndex > 0) {
      const label = line.slice(0, colonIndex).trim();
      const value = line.slice(colonIndex + 1).trim();
      if (isSuggestionLabel(label)) {
        isSuggestionSection = true;
        currentSection = "";
        return;
      }
      const item = isSuggestionSection ? "建議" : numbered ? numbered[2].split("：")[0].trim() : label.replace(/[💡]/g, "").trim();
      const description = numbered ? numbered[2].slice(numbered[2].indexOf("：") + 1).trim() : value;
      rows.push({ item, description });
      return;
    }

    if (numbered || bullet) {
      const item = isSuggestionSection ? "建議" : numbered ? `項目 ${numbered[1]}` : currentSection || "重點";
      const description = numbered ? numbered[2] : bullet[1];
      rows.push({ item, description });
      return;
    }

    if (line.length <= 18) {
      isSuggestionSection = line.includes("建議");
      currentSection = isSuggestionSection ? "" : line;
      return;
    }

    if (!currentSection && !isSuggestionSection) {
      introLines.push(line);
      return;
    }

    const item = isSuggestionSection ? "建議" : currentSection || "摘要";
    rows.push({ item, description: line });
  });

  return { intro: introLines.join("\n"), rows };
}

function PlainMessageContent({ content }) {
  const lines = content.split("\n");
  return lines.map((line, i) => (
    <span key={i}>{line}{i < lines.length - 1 && <br />}</span>
  ));
}

function AssistantTableContent({ content }) {
  const navigate = useNavigate();
  const { intro, rows } = parseAssistantTableRows(content);
  const isSurveyAnalysisReply = intro.includes("問卷資料") && intro.includes("初步分析結果");
  const shouldFillEmptySurveyRow = rows.length === 0 && (content.includes(EMPTY_SURVEY_TABLE_MARKER) || isSurveyAnalysisReply);
  const displayRows = shouldFillEmptySurveyRow
    ? [{ item: "資料不足", description: "目前問卷內容過少，暫無足夠資料可進行分析。" }]
    : rows;

  if (displayRows.length < 2 && !shouldFillEmptySurveyRow) {
    return <PlainMessageContent content={content} />;
  }

  return (
    <div className="assistant-output-panel">
      {intro && <div className="assistant-output-intro"><PlainMessageContent content={intro} /></div>}
      <div className="assistant-output-table-wrap">
        <table className="assistant-output-table">
          <thead>
            <tr>
              <th>分類</th>
              <th>分析內容</th>
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, index) => (
              <tr key={`${row.item}-${index}`} className={row.tone ? `assistant-output-row-${row.tone}` : ""}>
                <td>{row.item}</td>
                <td>{row.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="assistant-output-actions">
        <button
          className="assistant-export-btn"
          type="button"
          onClick={() => navigate("/collection", { state: { activeView: "exports" } })}
        >
          <i className="ri-download-cloud-2-line"></i>
          匯出檔案
        </button>
      </div>
    </div>
  );
}

function MessageContent({ message }) {
  if (message.role === "assistant") {
    return <AssistantTableContent content={message.content} />;
  }

  return <PlainMessageContent content={message.content} />;
}

function buildAutoSessionTitle(text, file) {
  if (file?.name) {
    const baseName = file.name.replace(/\.[^/.]+$/, "");
    return `分析：${baseName}`.slice(0, 28);
  }

  const cleaned = text
    .replace(/\s+/g, " ")
    .replace(/[，。！？、,.!?]/g, " ")
    .trim();

  if (!cleaned) return "新工作區";
  return cleaned.length > 18 ? `${cleaned.slice(0, 18)}...` : cleaned;
}

export default function WorkspacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isLoggedIn, user } = useAuth();
  const { recordActivity } = useActivity();

  const { addChatToCollection, addFileToCollection, syncChatTitle, deleteChatSession, updateSessionId, workspaceSessions: sessions, setWorkspaceSessions: setSessions } = useCollection();  const [activeSessionId, setActiveSessionId] = useState(null);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [attachedFile, setAttachedFile] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [showSurveyPicker, setShowSurveyPicker] = useState(false);
  const [showShareMenu, setShowShareMenu] = useState(false);
  const [surveyPickerSearch, setSurveyPickerSearch] = useState("");
  const [apiSurveys, setApiSurveys] = useState([]);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [toastMsg, setToastMsg] = useState(null);
  const toastTimerRef = useRef(null);

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const surveyImportHandled = useRef(false);
  const surveyPickerRef = useRef(null);
  const shareMenuRef = useRef(null);

  const showToast = (msg) => {
    setToastMsg(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToastMsg(null), 3000);
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;
  const messages = activeSession?.messages ?? [];

  useEffect(() => {
    const headers = getAuthHeader();
    if (!isLoggedIn || !headers.Authorization) {
      setApiSurveys([]);
      return;
    }

    let cancelled = false;

    const fetchSurveyDetails = async () => {
      try {
        const res = await fetch(apiUrl("/api/surveys/mine"), { headers });
        if (!res.ok) return;
        const data = await res.json();
        const surveys = Array.isArray(data) ? data : [];
        const detailed = await Promise.all(
          surveys.map(async (survey) => {
            const code = survey.code || survey.access_code;
            if (!code) return normalizeSurveyDetail(survey);
            try {
              const [surveyRes, responsesRes] = await Promise.all([
                fetch(apiUrl(`/api/surveys/${encodeURIComponent(code)}`), { headers }),
                fetch(apiUrl(`/api/surveys/${encodeURIComponent(code)}/responses`), { headers }),
              ]);
              const surveyData = surveyRes.ok ? await surveyRes.json() : {};
              const responsesData = responsesRes.ok ? await responsesRes.json() : {};
              return normalizeSurveyDetail({
                ...survey,
                ...surveyData,
                code,
                access_code: code,
                responses: responsesData.responses || [],
              });
            } catch {
              return normalizeSurveyDetail(survey);
            }
          })
        );
        if (!cancelled) setApiSurveys(detailed);
      } catch (err) {
        console.error("載入問卷清單失敗", err);
      }
    };

    fetchSurveyDetails();
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn, user]);

  // ── 登入後從後端載入 workspace 列表 ──────────────────────
  useEffect(() => {
    if (!isLoggedIn) return;

    const fetchWorkspaces = async () => {
      try {
        const res = await fetch(apiUrl("/api/workspace/user"), {
          headers: getAuthHeader(),
        });
        if (!res.ok) return;
        const data = await res.json();

        setSessions((prev) => {
          const backendIds = new Set(data.map((w) => String(w.project_id)));

          // 保留本地有但後端沒有的 session（例如問卷分析、尚未存到後端的）
          const localOnly = prev.filter(
            (s) => !s.project_id || !backendIds.has(String(s.project_id))
          );

          // 把後端資料轉成 session 格式，保留本地已有的 messages
          const fromBackend = data.map((w) => {
            const existing = prev.find((s) => String(s.project_id) === String(w.project_id));
            return {
              id: existing?.id || String(w.project_id),
              project_id: w.project_id,
              title: w.project_name,
              folder_name: w.folder_name ?? null,
              date: w.created_at ? new Date(w.created_at).toLocaleDateString() : "",
              messages: existing?.messages || [WELCOME_MSG],
            };
          });

          return [...localOnly, ...fromBackend];
        });
      } catch (err) {
        console.error("載入 workspace 失敗", err);
      }
    };

    fetchWorkspaces();
  }, [isLoggedIn]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeSessionId || sessions.length === 0) return;
    const savedId = localStorage.getItem(ACTIVE_WORKSPACE_KEY);
    const restored = sessions.find((s) => s.id === savedId);
    setActiveSessionId(restored?.id || sessions[0].id);
  }, [activeSessionId, sessions]);

  useEffect(() => {
    if (!activeSessionId) return;
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (surveyPickerRef.current && !surveyPickerRef.current.contains(e.target)) {
        setShowSurveyPicker(false);
      }
      if (shareMenuRef.current && !shareMenuRef.current.contains(e.target)) {
        setShowShareMenu(false);
      }
    };
    if (showSurveyPicker || showShareMenu) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showSurveyPicker, showShareMenu]);

  // Handle open session from collection
  useEffect(() => {
    const state = location.state;
    if (!state?.openSession) return;
    const { sessionId } = state.openSession;
    setActiveSessionId(sessionId);
    window.history.replaceState({}, "");
  }, [location.state]);

  // Handle survey import from profile page
  useEffect(() => {
    const state = location.state;
    if (!state?.surveyImport || surveyImportHandled.current) return;
    surveyImportHandled.current = true;
    const { sessionTitle, message } = state.surveyImport;
    const newId = `survey-${Date.now()}`;
    const userMsg = { id: `u-${Date.now()}`, role: "user", content: message };
    const newSession = {
      id: newId,
      title: sessionTitle,
      date: new Date().toLocaleDateString(),
      messages: [WELCOME_MSG, userMsg],
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newId);
    setIsTyping(true);
    setTimeout(() => {
      const aiReply = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: buildAssistantReply(message),
      };
      setSessions((prev) =>
        prev.map((s) => s.id === newId ? { ...s, messages: [...s.messages, aiReply] } : s)
      );
      setIsTyping(false);
    }, 1800);
    window.history.replaceState({}, "");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const appendMessage = useCallback((sessionId, msg) => {
    setSessions((prev) =>
      prev.map((s) => s.id === sessionId ? { ...s, messages: [...s.messages, msg] } : s)
    );
  }, []);

  const handleSelectSurvey = async (record) => {
    const detail = normalizeSurveyDetail(record.detail);
    if (!detail) return;
    const content = buildSurveyChatContent(detail);
    const title = `問卷分析：${record.title}`;
    const tempId = `survey-${Date.now()}`;
    const userMsg = { id: `u-${Date.now()}`, role: "user", content };
    const newSession = {
      id: tempId,
      title,
      date: new Date().toLocaleDateString(),
      messages: [WELCOME_MSG, userMsg],
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(tempId);
    setShowSurveyPicker(false);
    setSurveyPickerSearch("");

    try {
      const res = await fetch(apiUrl("/api/workspace"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
        },
        body: JSON.stringify({ project_name: title }),
      });
      if (res.ok) {
        const data = await res.json();
        const newId = String(data.project_id);
        setSessions((prev) =>
          prev.map((s) =>
            s.id === tempId
              ? { ...s, id: newId, project_id: data.project_id }
              : s
          )
        );
        updateSessionId(tempId, newId);
        setActiveSessionId(newId);
      }
    } catch (err) {
      console.error("建立問卷工作區失敗", err);
    }

    setIsTyping(true);
    setTimeout(() => {
      const aiReply = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: buildAssistantReply(content, detail, record.title),
      };
      setSessions((prev) =>
        prev.map((s) =>
          s.id === tempId || s.project_id === parseInt(tempId)
            ? { ...s, messages: [...s.messages, aiReply] }
            : s
        )
      );
      setIsTyping(false);
    }, 1800);
  };

  const surveyPickerRecords = getStoredSurveyRecords(user, apiSurveys);
  const filteredSurveyPicker = surveyPickerRecords.filter(
    (s) =>
      String(s.title || "").toLowerCase().includes(surveyPickerSearch.toLowerCase()) ||
      String(s.code || "").toLowerCase().includes(surveyPickerSearch.toLowerCase())
  );

  const sendMessage = () => {
    if (!input.trim() && !attachedFile) return;
    if (!activeSessionId) return;
    const content = attachedFile ? `[檔案：${attachedFile.name}] ${input}` : input;
    const autoTitle = buildAutoSessionTitle(input, attachedFile);
    const userMsg = { id: Date.now().toString(), role: "user", content };
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== activeSessionId) return s;
        const shouldAutoTitle = s.title === "新工作區";
        return {
          ...s,
          title: shouldAutoTitle ? autoTitle : s.title,
          messages: [...s.messages, userMsg],
        };
      })
    );
    const session = sessions.find((s) => s.id === activeSessionId);
    if (session?.title === "新工作區") {
      syncChatTitle(activeSessionId, autoTitle);
    }
    recordActivity({
      text: `在工作區送出訊息「${autoTitle}」`,
      icon: "ri-message-3-line",
      iconBg: "bg-stat-mauve",
      iconColor: "text-stat-mauve",
    });
    setInput("");
    setAttachedFile(null);
    setIsTyping(true);
    const sid = activeSessionId;
    setTimeout(() => {
      const reply = buildAssistantReply(content);
      appendMessage(sid, { id: Date.now().toString(), role: "assistant", content: reply });
      setIsTyping(false);
    }, 1500);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleTextareaInput = () => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 144) + "px";
    }
  };

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const startRename = (s) => {
    setRenamingId(s.id);
    setRenameValue(s.title);
  };

  // ── 重新命名：同時更新後端 ────────────────────────────────
  const saveRename = async (id) => {
    const trimmed = renameValue.trim();
    if (trimmed) {
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: trimmed } : s)));
      syncChatTitle(id, trimmed);

      const session = sessions.find((s) => s.id === id);
      if (session?.project_id) {
        try {
          await fetch(apiUrl(`/api/workspace/${session.project_id}`), {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
              ...getAuthHeader(),
            },
            body: JSON.stringify({ project_name: trimmed }),
          });
        } catch (err) {
          console.error("重新命名失敗", err);
        }
      }
    }
    setRenamingId(null);
  };

  const deleteSession = (sessionId) => {
    const session = sessions.find((s) => s.id === sessionId);
    if (!session) return;
    const ok = window.confirm(`確定要刪除「${session.title}」嗎？刪除後可在作品集的最近刪除中還原。`);
    if (!ok) return;

    deleteChatSession(sessionId);
    setRenamingId(null);
    setSearchQuery("");
    if (activeSessionId === sessionId) {
      const nextSession = sessions.find((s) => s.id !== sessionId);
      setActiveSessionId(nextSession?.id || null);
      if (nextSession?.id) {
        localStorage.setItem(ACTIVE_WORKSPACE_KEY, nextSession.id);
      } else {
        localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
      }
    }
    showToast("已刪除工作區，並移至最近刪除");
  };

  const requestDeleteSession = (sessionId) => {
    const session = sessions.find((s) => s.id === sessionId);
    if (!session) return;
    setDeleteTarget(session);
  };

  const confirmDeleteSession = () => {
    if (!deleteTarget) return;
    const sessionId = deleteTarget.id;
    deleteChatSession(sessionId);
    setRenamingId(null);
    setSearchQuery("");
    if (activeSessionId === sessionId) {
      const nextSession = sessions.find((s) => s.id !== sessionId);
      setActiveSessionId(nextSession?.id || null);
      if (nextSession?.id) {
        localStorage.setItem(ACTIVE_WORKSPACE_KEY, nextSession.id);
      } else {
        localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
      }
    }
    setDeleteTarget(null);
    showToast("已刪除工作區，並移至最近刪除");
  };

  // ── 建立新工作區 ─────────────
  const createNewSession = async () => {
    const title = "新工作區";
    const tempId = `temp-${Date.now()}`;

    const tempSession = {
      id: tempId,
      title,
      date: new Date().toLocaleDateString(),
      messages: [WELCOME_MSG],
    };
    setSessions((prev) => [tempSession, ...prev]);
    setActiveSessionId(tempId);
    addChatToCollection(title, tempId);

    try {
      const res = await fetch(apiUrl("/api/workspace"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
        },
        body: JSON.stringify({ project_name: title }),
      });

      if (res.ok) {
        const data = await res.json();
        const newId = String(data.project_id);
        setSessions((prev) =>
          prev.map((s) =>
            s.id === tempId
              ? { ...s, id: String(data.project_id), project_id: data.project_id }
              : s
          )
        );
        updateSessionId(tempId, newId);
        setActiveSessionId(String(data.project_id));
      }
    } catch (err) {
      console.error("新增工作區失敗", err);
    }
  };

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div className="workspace-page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <LoginRequiredModal
            message="新增工作區需要登入帳號才能使用，登入後即可開始分析資料。"
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/")}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      {/* Toast */}
      {toastMsg && (
        <div style={{
          position: "fixed", bottom: 32, left: "50%", transform: "translateX(-50%)",
          background: "#3d2b2b", color: "#fff", borderRadius: 10,
          padding: "10px 22px", fontSize: 14, fontWeight: 600,
          zIndex: 9999, display: "flex", alignItems: "center", gap: 8,
          boxShadow: "0 4px 16px rgba(0,0,0,0.18)", whiteSpace: "nowrap",
        }}>
          <i className="ri-checkbox-circle-line" style={{ color: "#a8e6a3", fontSize: 16 }}></i>
          {toastMsg}
        </div>
      )}
      <div className="workspace-page">
        <div className="workspace-body">
          {/* Sidebar */}
          <aside className="workspace-sidebar">
            <div className="sidebar-header">
              <div className="d-flex align-items-center mb-3">
                <span className="sidebar-title">歷史紀錄</span>
              </div>
              <div className="sidebar-search">
                <i className="ri-search-line"></i>
                <input
                  type="text"
                  placeholder="搜尋歷史紀錄..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searchQuery && (
                  <button className="search-clear" onClick={() => setSearchQuery("")}>
                    <i className="ri-close-line"></i>
                  </button>
                )}
              </div>
            </div>
            <div className="sidebar-list">
              {sessions.length === 0 ? (
                <div className="sidebar-empty">
                  <i className="ri-chat-ai-line"></i>
                  <p>尚無工作區紀錄</p>
                  <button
                    onClick={createNewSession}
                    style={{
                      marginTop: 8, background: "#c9a0a0", color: "white",
                      border: "none", borderRadius: 8, padding: "6px 14px",
                      fontSize: 12, fontWeight: 700, cursor: "pointer",
                    }}
                  >
                    新增工作區
                  </button>
                </div>
              ) : filteredSessions.length === 0 ? (
                <div className="sidebar-empty">
                  <i className="ri-search-line"></i>
                  <p>找不到相關紀錄</p>
                </div>
              ) : (
                filteredSessions.map((s) => (
                  <div
                    key={s.id}
                    className={`session-item ${activeSessionId === s.id ? "active" : ""}`}
                    onClick={() => setActiveSessionId(s.id)}
                  >
                    <div className="session-info flex-grow-1">
                      {renamingId === s.id ? (
                        <input
                          className="form-control form-control-sm"
                          value={renameValue}
                          autoFocus
                          onChange={(e) => setRenameValue(e.target.value)}
                          onBlur={() => saveRename(s.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") saveRename(s.id);
                            if (e.key === "Escape") setRenamingId(null);
                          }}
                          onClick={(e) => e.stopPropagation()}
                          style={{ fontSize: 14, fontWeight: 600 }}
                        />
                      ) : (
                        <p className="session-title" onDoubleClick={() => startRename(s)}>
                          {s.title}
                        </p>
                      )}
                      <p className="session-date">{s.date}</p>
                    </div>
                    <button
                      className="session-edit"
                      onClick={(e) => { e.stopPropagation(); startRename(s); }}
                      title="重新命名"
                    >
                      <i className="ri-pencil-line"></i>
                    </button>
                    <button
                      className="session-delete"
                      onClick={(e) => { e.stopPropagation(); requestDeleteSession(s.id); }}
                      title="刪除工作區"
                    >
                      <i className="ri-delete-bin-line"></i>
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className="sidebar-footer">
              <button className="btn-new-session sidebar-bottom-add" onClick={createNewSession} title="新增工作區">
                <i className="ri-add-line"></i>
              </button>
            </div>
          </aside>

          {/* Main Chat */}
          <main className="workspace-main">
            <div className="workspace-share-float" ref={shareMenuRef}>
              <button
                className={`workspace-share-btn${showShareMenu ? " active" : ""}`}
                type="button"
                onClick={() => setShowShareMenu((open) => !open)}
                aria-expanded={showShareMenu}
              >
                <i className="ri-share-forward-line"></i>
                <span>分享</span>
              </button>
              {showShareMenu && (
                <div className="workspace-share-menu">
                  <button className="workspace-share-option" type="button">
                    <i className="ri-team-line"></i>
                    <span>邀請協作</span>
                  </button>
                  <button className="workspace-share-option" type="button">
                    <i className="ri-eye-line"></i>
                    <span>邀請預覽</span>
                  </button>
                </div>
              )}
            </div>
            {activeSession === null ? (
              <div style={{
                flex: 1, display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center",
                color: "#b08080", gap: 16,
              }}>
                <div style={{
                  width: 64, height: 64, background: "#f5e8e6",
                  borderRadius: "50%", display: "flex", alignItems: "center",
                  justifyContent: "center", fontSize: 28,
                }}>
                  <i className="ri-chat-ai-line"></i>
                </div>
                <p style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>選擇或新增一個工作區開始分析</p>
                <button
                  onClick={createNewSession}
                  style={{
                    background: "#c9a0a0", color: "white", border: "none",
                    borderRadius: 10, padding: "10px 24px", fontSize: 14,
                    fontWeight: 700, cursor: "pointer",
                  }}
                >
                  <i className="ri-add-line" style={{ marginRight: 6 }}></i>新增工作區
                </button>
              </div>
            ) : (
              <>
                <div className="messages-area">
                  {messages.map((msg) => (
                    <div key={msg.id} className={`message-row ${msg.role === "user" ? "user" : ""}`}>
                      <div className={`message-avatar ${msg.role === "user" ? "user-avatar" : "assistant-avatar"}`}>
                        <i className={msg.role === "user" ? "ri-user-line" : "ri-robot-line"}></i>
                      </div>
                      <div className={`message-bubble ${msg.role === "user" ? "user-bubble" : "assistant-bubble"}`}>
                        <MessageContent message={msg} />
                      </div>
                    </div>
                  ))}
                  {isTyping && (
                    <div className="message-row">
                      <div className="message-avatar assistant-avatar">
                        <i className="ri-robot-line"></i>
                      </div>
                      <div className="message-bubble assistant-bubble typing-bubble">
                        <div className="typing-dots">
                          <span></span><span></span><span></span>
                        </div>
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef}></div>
                </div>

                {/* Input Area */}
                <div className="input-area">
                  {attachedFile && (
                    <div className="file-attachment">
                      <i className="ri-attachment-line"></i>
                      <span>{attachedFile.name}</span>
                      <button onClick={() => setAttachedFile(null)}>
                        <i className="ri-close-line"></i>
                      </button>
                    </div>
                  )}
                  <div className="input-wrapper">
                    {/* Survey Picker Button */}
                    <div className="survey-picker-wrapper" ref={surveyPickerRef}>
                      <button
                        className={`attach-btn survey-pick-btn${showSurveyPicker ? " active" : ""}`}
                        onClick={() => setShowSurveyPicker((v) => !v)}
                        title="選擇問卷分析"
                      >
                        <i className="ri-survey-line"></i>
                      </button>
                      {showSurveyPicker && (
                        <div className="survey-picker-panel">
                          <div className="survey-picker-header">
                            <span className="survey-picker-title">
                              <i className="ri-survey-line"></i>
                              選擇問卷進行分析
                            </span>
                            <button className="survey-picker-close" onClick={() => setShowSurveyPicker(false)}>
                              <i className="ri-close-line"></i>
                            </button>
                          </div>
                          <div className="survey-picker-search">
                            <i className="ri-search-line"></i>
                            <input
                              type="text"
                              placeholder="搜尋問卷名稱或代碼..."
                              value={surveyPickerSearch}
                              onChange={(e) => setSurveyPickerSearch(e.target.value)}
                              autoFocus
                            />
                            {surveyPickerSearch && (
                              <button onClick={() => setSurveyPickerSearch("")}>
                                <i className="ri-close-circle-line"></i>
                              </button>
                            )}
                          </div>
                          <div className="survey-picker-list">
                            {filteredSurveyPicker.length === 0 ? (
                              <div className="survey-picker-empty">
                                <i className="ri-search-line"></i>
                                <p>找不到相關問卷</p>
                              </div>
                            ) : (
                              filteredSurveyPicker.map((s) => (
                                <button
                                  key={s.id}
                                  className="survey-picker-item"
                                  onClick={() => handleSelectSurvey(s)}
                                >
                                  <div className={`survey-picker-icon${s.status === "active" ? " active" : ""}`}>
                                    <i className="ri-survey-line"></i>
                                  </div>
                                  <div className="survey-picker-info">
                                    <span className="survey-picker-name">{s.title}</span>
                                    <div className="survey-picker-meta">
                                      <span><i className="ri-key-2-line"></i>{s.code}</span>
                                      <span><i className="ri-user-line"></i>{s.responseCount} 人回覆</span>
                                      <span><i className="ri-calendar-line"></i>{s.createdAt}</span>
                                    </div>
                                  </div>
                                  <span className={`survey-picker-status${s.status === "active" ? " active" : ""}`}>
                                    {s.status === "active" ? "進行中" : "已結束"}
                                  </span>
                                </button>
                              ))
                            )}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* File Attach Button */}
                    <button
                      className="attach-btn"
                      onClick={() => fileInputRef.current?.click()}
                      title="附加檔案"
                    >
                      <i className="ri-attachment-line"></i>
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="d-none"
                      accept=".csv,.xlsx,.json,.txt"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setAttachedFile(f);
                        addFileToCollection(f);
                        showToast(`「${f.name}」已加入作品集`);
                        e.target.value = "";
                      }}
                    />
                    <textarea
                      ref={textareaRef}
                      rows={1}
                      placeholder="輸入您的問題或上傳檔案進行分析..."
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onInput={handleTextareaInput}
                      onKeyDown={handleKeyDown}
                    />
                    <button
                      className="send-btn"
                      onClick={sendMessage}
                      disabled={!input.trim() && !attachedFile}
                    >
                      <i className="ri-send-plane-line"></i>
                    </button>
                  </div>
                  <p className="input-hint">
                    <i className="ri-survey-line" style={{ marginRight: 4 }}></i>
                    點擊問卷圖示可直接選擇問卷分析 · 支援 CSV、Excel、JSON、TXT · Enter 發送
                  </p>
                </div>
              </>
            )}
          </main>
        </div>
      </div>
      {deleteTarget && (
        <div className="workspace-modal-backdrop" onClick={() => setDeleteTarget(null)}>
          <div className="workspace-alert-modal" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-alert-icon">
              <i className="ri-error-warning-line"></i>
            </div>
            <h3>刪除工作區</h3>
            <p>確定要刪除「{deleteTarget.title}」嗎？刪除後可在作品集的最近刪除中還原。</p>
            <div className="workspace-alert-actions">
              <button className="workspace-alert-primary" onClick={confirmDeleteSession} type="button">
                確定
              </button>
              <button className="workspace-alert-secondary" onClick={() => setDeleteTarget(null)} type="button">
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
