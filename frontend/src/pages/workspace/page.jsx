import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import { useActivity } from "../../hooks/ActivityContext";
import { apiUrl } from "../../lib/api";
// 【修正】原本這裡有 import buildSurveyChatContent，現在不再用它組長文字
// 訊息內容，改成簡短一行，拿掉未使用的 import。
import "./workspace.css";
import ShareWorkspaceDialog from "./ShareWorkspaceDialog";
import ExportActions from "./ExportActions";

export const WELCOME_MSG = {
  id: "welcome",
  role: "assistant",
  content:
    "Hello! I am the DataAnalysis AI assistant. Upload a CSV, Excel, or TXT file, or ask a question to explore your data.",
};
const ACTIVE_WORKSPACE_KEY = "dataanalysis_active_workspace";
const EMPTY_SURVEY_TABLE_MARKER = "[[EMPTY_SURVEY_TABLE]]";
/* ============================================================
 * 【新增｜2026-08-27】串接後端真實 Gemini 分類功能
 * 取代原本 workspace 聊天室裡「純前端算數字套中文句型」的假分析。
 * 對應後端 API：POST /api/classification/upload
 *   （後端會依序做 PII 遮罩 → TF-IDF 去重 → 送 Gemini 分類 → 直接回傳結果）
 * 這一整段（helper function + ClassificationTable 元件 + runExcelClassification
 * + sendMessage 裡的分流判斷 + 附加檔案 UI 的欄位輸入框）都是新增，
 * 用「新增｜2026-08-27」這幾個字搜尋可以找到全部相關區塊。
 * ============================================================ */
const CLASSIFICATION_TABLE_MARKER = "[[CLASSIFICATION_TABLE]]";

// 判斷附加的檔案是不是 Excel（.xlsx / .xls），用來決定要不要走真分類流程
function isExcelFile(file) {
  return !!file && /\.(xlsx|xls)$/i.test(file.name || "");
}

// 把 /api/classification/upload 回傳的 aggregated_groups 陣列存進訊息內容
// （含 marker 方便還原）。分組、過濾「無具體建議」、彙整判斷原因跟建議摘要
// 都已經在後端做完了，這裡不用再處理，直接存、直接顯示。
function buildClassificationMessageContent(aggregatedGroups, meta) {
  const rows = (aggregatedGroups || []).map((g) => ({
    main_category: g.main_category || "",
    sub_category: g.sub_category || "",
    respondent_text: g.respondent_text || "",
    aggregated_reasoning: g.aggregated_reasoning || "",
    aggregated_summary: g.aggregated_summary || "",
    synthesis_status: g.synthesis_status || "ok",
    synthesis_error: g.synthesis_error || null,
    respondent_count: g.respondent_count ?? null,
  }));
  return `${CLASSIFICATION_TABLE_MARKER}${JSON.stringify({ rows, meta: meta || {} })}`;
}

// 跟上面成對：把存起來的字串還原成表格資料。回傳 null 代表「這不是分類結果訊息」。
function parseClassificationMessageContent(content) {
  if (!content || !content.startsWith(CLASSIFICATION_TABLE_MARKER)) return null;
  try {
    return JSON.parse(content.slice(CLASSIFICATION_TABLE_MARKER.length));
  } catch {
    return null; // JSON 壞掉（例如存到一半被截斷）就當作不是分類訊息，退回顯示原始文字
  }
}
/* 【新增區塊到此為止的第 1 段，下面接原本就有的 getAuthHeader】 */

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
  const responses = Array.isArray(survey?.responses) ? survey.responses : [];
  return {
    ...survey,
    id: survey?.id || survey?.template_id || code,
    title: survey?.title || survey?.survey_name || "Untitled survey",
    code,
    createdAt: survey?.createdAt || survey?.created_at || "",
    questions: Array.isArray(survey?.questions) ? survey.questions : [],
    responses,
    responseCount: survey?.responseCount ?? survey?.response_count ?? responses.length,
  };
}

function getSurveyPickerRecords(apiSurveys = []) {
  return apiSurveys
    .map(normalizeSurveyDetail)
    .filter((survey) => survey.code)
    .map((survey) => ({
      id: survey.id,
      title: survey.title,
      code: survey.code,
      createdAt: survey.createdAt,
      responseCount: survey.responseCount,
      status: survey.status || "active",
      detail: survey,
    }));
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

function buildSurveyAnalysisReplyFromSurvey(survey, fallbackTitle = "Survey") {
  const stats = getSurveyStats(survey);
  const title = survey?.title || survey?.survey_name || fallbackTitle;
  const intro = `I have received the survey data for ${title}. Here is the preliminary analysis:`;

  if (isSurveyContentTooSmall(stats)) {
    return `${EMPTY_SURVEY_TABLE_MARKER}\n${intro}`;
  }

  const rows = [];
  if (stats.ratingQuestions.length > 0) {
    rows.push(`Rating insights:  ${stats.ratingQuestions.length}  rating questions with an average of  ${stats.ratingAverage ?? "No data"} / 5. Start by reviewing questions with below-average scores.`);
  }
  if (stats.textQuestions.length > 0) {
    const sampleTitle = stats.textQuestions[0]?.title || stats.textQuestions[0]?.question_title;
    const sampleQuestion = sampleTitle ? `「${sampleTitle}」` : "Open-ended question";
    rows.push(`Open-ended themes:  ${stats.textAnswers.length}  text responses collected. Start with  ${sampleQuestion}  and its recurring keywords to organize the main themes.`);
  }
  rows.push(`Response overview:  ${stats.responses.length}  respondents, ${stats.questions.length}  questions, and  ${stats.answeredValues.length}  answers available for analysis.`);
  rows.push("Recommendations: Compare question types or respondent groups, and follow up on low scores and recurring comments.");

  return `${intro}\n\n${rows.join("\n")}`;
}

function parseBuiltInSurveyText(content) {
  const isEmojiSurvey = (/📋 (?:Survey title:|問卷名稱：)/.test(content) && /🔑 (?:Survey code:|問卷代碼：)/.test(content));
  const isProfileSurvey = (/(?:Survey:|問卷：)/.test(content) && /(?:Invite code:|邀請碼：)/.test(content) && /(?:Responses:|回覆數：)/.test(content));
  if (!isEmojiSurvey && !isProfileSurvey) return null;

  const title = (isEmojiSurvey
    ? content.match(/📋 (?:Survey title:|問卷名稱：)\s*(.+)/)?.[1]
    : content.match(/(?:Survey:|問卷：)\s*(.+)/)?.[1])?.trim() || "Survey";
  const responseCount = Number((isEmojiSurvey
    ? content.match(/👥 (?:Responses:|回覆人數：)\s*(\d+)/)?.[1]
    : content.match(/(?:Responses:|回覆數：)\s*(\d+)/)?.[1]) || 0);
  const questionCount = Number((isEmojiSurvey
    ? content.match(/❓ (?:Questions:|題目數量：)\s*(\d+)/)?.[1]
    : (content.match(/^Q\d+\./gm) || []).length) || 0);
  const answerCount = (content.match(/^\s+\d+\.\s+/gm) || []).length;
  const hasRating = /(?:── Rating summary ──|── 評分題統計 ──)/.test(content) || /^\s+\d+\.\s*[0-5](?:\.0)?\s*$/m.test(content);
  const hasText = /(?:── Open-ended responses ──|── 問答題回覆 ──)/.test(content) || answerCount > 0;
  return { title, responseCount, questionCount, answerCount, hasRating, hasText };
}

function buildSurveyAnalysisReplyFromText(content) {
  const survey = parseBuiltInSurveyText(content);
  if (!survey) return null;
  const intro = `I have received the survey data for ${survey.title}. Here is the preliminary analysis:`;

  if (survey.questionCount === 0 || survey.answerCount < 2) {
    return `${EMPTY_SURVEY_TABLE_MARKER}\n${intro}`;
  }

  const rows = [];
  if (survey.hasRating) {
    rows.push("Rating insights: Compare average scores across questions to identify satisfaction levels and gaps.");
  }
  if (survey.hasText) {
    rows.push(`Open-ended themes:  ${survey.answerCount}  text responses found. Review recurring themes and positive and negative feedback.`);
  }
  rows.push(`Response overview:  ${survey.responseCount}  respondents, ${survey.questionCount}  questions available for preliminary trend analysis.`);
  rows.push("Recommendations: Add respondent group fields or collect more responses to improve confidence in the analysis.");

  return `${intro}\n\n${rows.join("\n")}`;
}

function isGreetingInput(text) {
  const normalized = text.trim().toLowerCase().replace(/[，。！？、,.!?\s]/g, "");
  return ["hi", "hello", "hey", "你好", "哈囉", "嗨", "您好"].includes(normalized);
}

function buildAssistantReply(content, surveyDetail = null, surveyTitle = "Survey") {
  if (surveyDetail) return buildSurveyAnalysisReplyFromSurvey(surveyDetail, surveyTitle);
  if (isGreetingInput(content)) return "Hello! Provide data or choose a survey, and I will help you identify the key points.";
  const surveyReply = buildSurveyAnalysisReplyFromText(content);
  if (surveyReply) return surveyReply;
  return "There is not enough data to analyze. Please choose a survey, upload a complete data file, or ask a more specific question.";
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

  const isSuggestionLabel = (value) => ["Recommendations", "Suggestions", "Suggested questions", "建議", "可進一步詢問"].includes(value.replace(/[💡]/g, "").trim());

  visibleContent.split("\n").forEach((rawLine) => {
    const line = cleanMessageText(rawLine);
    if (!line) return;

    if (/^(?:I have received|我已收到)/.test(line)) {
      introLines.push(line);
      return;
    }

    if (isSuggestionSection) return;

    const numbered = line.match(/^(\d+)\.\s*(.+)$/);
    const bullet = line.match(/^[-]\s*(.+)$/);
    const colonIndex = line.search(/[:：]/);

    if (colonIndex > 0) {
      const label = line.slice(0, colonIndex).trim();
      const value = line.slice(colonIndex + 1).trim();
      if (isSuggestionLabel(label)) {
        isSuggestionSection = true;
        currentSection = "";
        return;
      }
      const item = isSuggestionSection ? "Recommendations" : numbered ? numbered[2].split(/[:：]/)[0].trim() : label.replace(/[💡]/g, "").trim();
      const description = numbered ? numbered[2].slice(numbered[2].search(/[:：]/) + 1).trim() : value;
      rows.push({ item, description });
      return;
    }

    if (numbered || bullet) {
      const item = isSuggestionSection ? "Recommendations" : numbered ? `Item  ${numbered[1]}` : currentSection || "Key points";
      const description = numbered ? numbered[2] : bullet[1];
      rows.push({ item, description });
      return;
    }

    if (line.length <= 18) {
      isSuggestionSection = /recommendations|suggestions|建議/i.test(line);
      currentSection = isSuggestionSection ? "" : line;
      return;
    }

    if (!currentSection && !isSuggestionSection) {
      introLines.push(line);
      return;
    }

    const item = isSuggestionSection ? "Recommendations" : currentSection || "Summary";
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

function AssistantTableContent({ content, readOnly = false }) {
  const navigate = useNavigate();
  const { intro, rows } = parseAssistantTableRows(content);
  const isSurveyAnalysisReply = (/survey data|問卷資料/.test(intro) && /preliminary analysis|初步分析結果/.test(intro));
  const shouldFillEmptySurveyRow = rows.length === 0 && (content.includes(EMPTY_SURVEY_TABLE_MARKER) || isSurveyAnalysisReply);
  const displayRows = shouldFillEmptySurveyRow
    ? [{ item: "Insufficient data", description: "This survey does not yet contain enough data for analysis." }]
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
              <th>Category</th>
              <th>Analysis</th>
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
      {!readOnly && <div className="assistant-output-actions">
        <button
          className="assistant-export-btn"
          type="button"
          onClick={() => navigate("/collection", { state: { activeView: "exports" } })}
        >
          <i className="ri-download-cloud-2-line"></i>
          Exported files
        </button>
      </div>}
    </div>
  );
}

/* 【串backend】渲染真實分類結果的表格元件。
 * 5 欄對照使用者要的格式：大類別／子類別／問卷回覆內容／判斷原因與說明／受試者建議摘要。
 * 資料來源：parseClassificationMessageContent() 從訊息內容還原出來的 rows。 */
// 把用 \n 分隔的多行文字渲染成真的換行（respondent_text、fallback 時的
// aggregated_reasoning/aggregated_summary 都可能是這種多行字串）
function MultilineText({ text, highlightRespondent = false }) {
  return (text || "").split("\n").map((line, i) => {
    if (highlightRespondent) {
      const match = line.match(/^(受試者\d+：)(.*)$/);

      if (match) {
        return (
          <span key={i}>
            {i > 0 && <br />}
            <span className="respondent-label">{match[1]}</span>
            {match[2]}
          </span>
        );
      }
    }

    return (
      <span key={i}>
        {i > 0 && <br />}
        {line}
      </span>
    );
  });
}

function ClassificationTable({ rows, meta, chatId, showToast, readOnly = false }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="assistant-output-panel">
        <div className="assistant-output-intro">
          No classification results were generated for this data.
        </div>

        {meta?.diagnostic_message && (
          <div className="assistant-output-diagnostic">
            {meta.diagnostic_message}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="assistant-output-panel assistant-output-panel--wide">
      <div className="assistant-output-intro">
        Classification complete:  {rows.length}  categories.
      </div>

      <div className="assistant-output-table-wrap">
        <table className="assistant-output-table classification-table">
          <thead>
            <tr>
              <th>Main category</th>
              <th>Subcategory</th>
              <th>Survey response</th>
              <th>Reasoning and explanation</th>
              <th>Summary of respondent suggestions</th>
            </tr>
          </thead>

          <tbody>
            {rows.map((row, index) => {
              const isSameMainAsPrev =
                index > 0 &&
                rows[index - 1].main_category === row.main_category;

              let mainCategoryRowSpan = 1;

              if (!isSameMainAsPrev) {
                for (
                  let j = index + 1;
                  j < rows.length &&
                  rows[j].main_category === row.main_category;
                  j++
                ) {
                  mainCategoryRowSpan++;
                }
              }

              return (
                <tr key={index}>
                  {!isSameMainAsPrev && (
                    <td
                      rowSpan={mainCategoryRowSpan}
                      className="merged-cell-center"
                    >
                      {row.main_category}
                    </td>
                  )}

                  <td className="sub-category-cell">
                    {row.sub_category}
                  </td>

                  <td>
                    <MultilineText
                      text={row.respondent_text}
                      highlightRespondent={true}
                    />
                  </td>

                  <td>
                    <MultilineText text={row.aggregated_reasoning} />
                  </td>

                  <td>
                    <MultilineText text={row.aggregated_summary} />

                    {row.synthesis_status === "fallback" && (
                      <div className="synthesis-fallback-note">
                        (The combined summary is temporarily unavailable. Individual comments are shown below.)

                        {row.synthesis_error && (
                          <div className="synthesis-error-detail">
                            Error: {row.synthesis_error}
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {!readOnly && <ExportActions rows={rows} chatId={chatId} sourceFilename={meta?.source_filename} />}
    </div>
  );
}

// 【新增｜邀請瀏覽】export 出去給 SharedWorkspacePage.jsx 重複使用，
// 這樣唯讀頁面才能沿用同一套已經驗證過的分類結果表格渲染邏輯，
// 不用另外重寫一份（重寫容易漏掉今天調過的細節，例如大類別合併、
// 受試者片段合併顯示這些規則）。
export function MessageContent({ message, showToast, readOnly = false }) {
  // 優先判斷是不是真分類結果訊息，是的話直接渲染表格，
  // 不要讓它掉進下面 AssistantTableContent 那個舊的、給假分析用的文字解析邏輯。
  const classificationData = parseClassificationMessageContent(message.content);
  if (classificationData) {
    return (
      <ClassificationTable
        readOnly={readOnly}
        rows={classificationData.rows}
        meta={classificationData.meta}
        chatId={message.chatId}
        showToast={showToast}
      />
    );
  }
  // 【新增區塊到此為止，以下都是原本就有的邏輯，沒有改動】

  if (message.role === "assistant") {
    return <AssistantTableContent content={message.content} readOnly={readOnly} />;
  }

  return <PlainMessageContent content={message.content} />;
}

function buildAutoSessionTitle(text, file) {
  if (file?.name) {
    const baseName = file.name.replace(/\.[^/.]+$/, "");
    return `Analysis: ${baseName}`.slice(0, 28);
  }

  const cleaned = text
    .replace(/\s+/g, " ")
    .replace(/[，。！？、,.!?]/g, " ")
    .trim();

  if (!cleaned) return "New workspace";
  return cleaned.length > 18 ? `${cleaned.slice(0, 18)}...` : cleaned;
}

export default function WorkspacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isLoggedIn, user } = useAuth();
  const { recordActivity } = useActivity();
  const loadedProjectIds = useRef(new Set());


  const {
    addChatToCollection,
    addFileToCollection,
    syncChatTitle,
    deleteChatSession,
    updateSessionId,
    workspaceSessions: storedSessions = [],
    setWorkspaceSessions: setSessions,
  } = useCollection();

  const sessions = Array.isArray(storedSessions) ? storedSessions : [];

  const [activeSessionId, setActiveSessionId] = useState(null);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [attachedFile, setAttachedFile] = useState(null);
  // 【串backend】真分類流程用的 state：
  // isClassifying = 分類中鎖定輸入框（欄位名稱不用使用者輸入，後端自動判斷）
  const [isClassifying, setIsClassifying] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [showSurveyPicker, setShowSurveyPicker] = useState(false);
  const [surveyPickerSearch, setSurveyPickerSearch] = useState("");
  const [apiSurveys, setApiSurveys] = useState([]);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [isDeletingSession, setIsDeletingSession] = useState(false);
  const [shareInvite, setShareInvite] = useState(null);
  const [isSharing, setIsSharing] = useState(false);
  const [toastMsg, setToastMsg] = useState(null);
  const [isEntryLoading, setIsEntryLoading] = useState(() => sessionStorage.getItem("dataanalysis_login_loading") === "1");
  const [historyLoadingSessionId, setHistoryLoadingSessionId] = useState(() => location.state?.openSession?.sessionId || null);
  const [isSurveyPickerLoading, setIsSurveyPickerLoading] = useState(true);
  const toastTimerRef = useRef(null);

  const messagesEndRef = useRef(null);
  const scrollToBottomSessionRef = useRef(location.state?.openSession?.scrollToBottom ? location.state.openSession.sessionId : null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const surveyImportHandled = useRef(false);
  const surveyPickerRef = useRef(null);

  const showToast = (msg) => {
    setToastMsg(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToastMsg(null), 3000);
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;
  const messages = activeSession?.messages ?? [];

  // 分享目前工作區，成功後顯示可複製及預覽的邀請連結。
  // 暫存工作區（temp-/survey- 開頭）根本沒有真正的 project_id，
  // 邀請連結沒有意義，直接告知使用者先送出至少一則訊息。
  const handleInviteView = async () => {
    if (isSharing) return;
    if (!activeSession) {
      showToast?.("Please open a workspace first");
      return;
    }
    const projectId = activeSession.project_id;
    if (!projectId || String(projectId).startsWith("temp-") || String(projectId).startsWith("survey-")) {
      showToast?.("This workspace has not finished syncing. Send a message before inviting viewers.");
      return;
    }
    setIsSharing(true);
    try {
      const res = await fetch(apiUrl(`/api/workspace/${projectId}/share`), {
        method: "POST",
        headers: getAuthHeader(),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast?.(data?.error || "Failed to create invite link");
        return;
      }
      const shareLink = `${window.location.origin}/shared/${data.share_code}`;
      if (!data.share_code) throw new Error("Missing share code");
      setShareInvite({ link: shareLink, title: activeSession.title || "Analysis conversation" });
    } catch (err) {
      console.error("Failed to create invite link: ", err);
      showToast?.("Failed to create invite link. Please try again later.");
    } finally {
      setIsSharing(false);
    }
  };

  useEffect(() => {
    const headers = getAuthHeader();
    if (!isLoggedIn || !headers.Authorization) {
      setApiSurveys([]);
      return;
    }

    let cancelled = false;

    const fetchSurveyDetails = async () => {
      setIsSurveyPickerLoading(true); // 開始載入，顯示 loading 狀態
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
        console.error("Failed to load survey list", err);
      } finally {
        if (!cancelled) setIsSurveyPickerLoading(false);   // 載入完成，隱藏 loading 狀態
      }
    };

    fetchSurveyDetails();
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn, user]);

  // ── 1. 登入後載入工作區「列表外殼」 ──────────────────────────
  useEffect(() => {
    if (!isLoggedIn) {
      setIsEntryLoading(false);
      sessionStorage.removeItem("dataanalysis_login_loading");
      return;
    }

    let cancelled = false;

    const fetchWorkspaces = async () => {
      try {
        const res = await fetch(apiUrl("/api/workspace/user"), {
          headers: getAuthHeader(),
        });

        if (!res.ok) {
          console.error("Failed to load workspace API: ", res.status);
          return;
        }

        const responseData = await res.json();
        const workspaceList = Array.isArray(responseData) ? responseData : [];

        if (cancelled) return;

        setSessions((currentList) => {
          const safeList = Array.isArray(currentList) ? currentList : [];
          const backendIds = new Set(
            workspaceList.map((workspace) => String(workspace.project_id))
          );

          const localOnly = safeList.filter(
            (session) =>
              !session.project_id ||
              !backendIds.has(String(session.project_id))
          );

          const fromBackend = workspaceList.map((workspace) => {
            const existing = safeList.find(
              (session) =>
                String(session.project_id) === String(workspace.project_id)
            );

            return {
              id: existing?.id || String(workspace.project_id),
              project_id: workspace.project_id,
              title: workspace.project_name || "Untitled workspace",
              folder_name: workspace.folder_name ?? null,
              date: workspace.created_at
                ? new Date(workspace.created_at).toLocaleDateString("en-US")
                : "",
              messages: existing?.messages || [WELCOME_MSG],
            };
          });

          return [...localOnly, ...fromBackend];
        });
      } catch (err) {
        console.error("Failed to load workspace", err);
      } finally {
        if (!cancelled) {
          setIsEntryLoading(false);
          sessionStorage.removeItem("dataanalysis_login_loading");
        }
      }
    };

    fetchWorkspaces();

    return () => {
      cancelled = true;
    };
  }, [isLoggedIn, setSessions]);

  // ── 2. 當切換 activeSessionId 時，才動態去後端補拉該專案的歷史訊息 ──
    useEffect(() => {
      if (!activeSessionId || !isLoggedIn) return;

      const currentSession = sessions.find(
        (s) => String(s.id) === String(activeSessionId)
      );
      if (!currentSession?.project_id) return;

      // 已經載入過就跳過
      if (loadedProjectIds.current.has(currentSession.project_id)) {
        setHistoryLoadingSessionId((current) => current === activeSessionId ? null : current);
        return;
      }
      if (currentSession.messages && currentSession.messages.length > 1) {
        loadedProjectIds.current.add(currentSession.project_id);
        setHistoryLoadingSessionId((current) => current === activeSessionId ? null : current);
        return;
      }

      loadedProjectIds.current.add(currentSession.project_id); // 先標記，防止重複打

      setHistoryLoadingSessionId((current) => current || activeSessionId);

      const fetchHistory = async () => {
        try {
          const res = await fetch(apiUrl(`/api/chat/history/${currentSession.project_id}`), {
            headers: getAuthHeader(),
          });
          if (!res.ok) return;
          const histData = await res.json();
          const historyList = Array.isArray(histData?.chat_history)
            ? histData.chat_history.filter((item) => item.type !== "file")
            : [];
          const fetchedMessages = historyList.map((h) => ({
            id: String(h.chat_id),
            role: h.role || (h.sender_type === "user" ? "user" : "assistant"),
            content: h.content || h.message_content || "",
            // 【修正｜匯出清單抓不到 chat_id】後端明明有回傳 chat_id（上面
            // 拿去當 id 用了），但這裡漏了存進 chatId 欄位——導致頁面重新
            // 整理、或切換 session 後再回來，分類結果訊息的匯出按鈕會找不到
            // chat_id，誤判成「這則訊息還沒同步」，其實只是忘了帶進來。
            chatId: h.chat_id,
          }));

          if (fetchedMessages.length > 0) {
            setSessions((currentList) =>
              (Array.isArray(currentList) ? currentList : []).map((session) => {
                if (String(session.id) !== String(activeSessionId)) return session;

                const localMessages = Array.isArray(session.messages) ? session.messages : [];
                const messageKey = (msg) => `${msg.role || ""}::${msg.content || ""}`;
                const fetchedKeys = new Set(fetchedMessages.map(messageKey));
                const pendingLocalMessages = localMessages.filter((msg) => {
                  if (msg.id === WELCOME_MSG.id) return false;
                  return !fetchedKeys.has(messageKey(msg));
                });

                return {
                  ...session,
                  messages: [WELCOME_MSG, ...fetchedMessages, ...pendingLocalMessages],
                };
              })
            );
          }
        } catch (err) {
          console.error("Failed to load conversation history: ", err);
        } finally {
          setHistoryLoadingSessionId((current) => current === activeSessionId ? null : current);
        }
      };

      fetchHistory();
  }, [activeSessionId, isLoggedIn, sessions, setSessions]);

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
    const forceBottom = scrollToBottomSessionRef.current === activeSessionId;
    if (forceBottom && (historyLoadingSessionId || isEntryLoading)) return;
    const frame = requestAnimationFrame(() => {
      const messageArea = messagesEndRef.current?.closest(".messages-area");
      messageArea?.scrollTo({ top: messageArea.scrollHeight, behavior: forceBottom ? "instant" : "smooth" });
      if (forceBottom && messagesEndRef.current) scrollToBottomSessionRef.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, isTyping, activeSessionId, historyLoadingSessionId, isEntryLoading]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (surveyPickerRef.current && !surveyPickerRef.current.contains(e.target)) {
        setShowSurveyPicker(false);
      }
    };
    if (showSurveyPicker) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showSurveyPicker]);

  // Handle open session from collection
  useEffect(() => {
    const state = location.state;
    if (!state?.openSession) return;
    const { sessionId } = state.openSession;
    scrollToBottomSessionRef.current = state.openSession.scrollToBottom ? sessionId : null;
    setHistoryLoadingSessionId(sessionId);
    setActiveSessionId(sessionId);
    window.history.replaceState({}, "");
  }, [location.state]);

  // Handle survey import from profile page
  useEffect(() => {
    const state = location.state;
    if (!state?.surveyImport || surveyImportHandled.current) return;
    surveyImportHandled.current = true;
    const { sessionTitle, message, surveyDetail } = state.surveyImport;
    const surveyTitle = sessionTitle.replace(/^問卷分析：/, "");
    const newId = `survey-${Date.now()}`;
    const userMsg = { id: `u-${Date.now()}`, role: "user", content: message };
    const newSession = {
      id: newId,
      title: sessionTitle,
      date: new Date().toLocaleDateString("en-US"),
      messages: [WELCOME_MSG, userMsg],
    };
    setSessions((currentList) => [
      newSession,
      ...(Array.isArray(currentList) ? currentList : []),
    ]);
    setActiveSessionId(newId);

    fetch(apiUrl("/api/workspace"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ project_name: sessionTitle }),
    })
    .then((res) => res.ok ? res.json() : null)
    .then((data) => {
      if (!data?.project_id) return;

      const surveyCode =
        surveyDetail?.code ||
        surveyDetail?.access_code ||
        state.surveyImport?.survey?.code ||
        state.surveyImport?.survey?.access_code;
      if (surveyCode) {
        fetch(apiUrl(`/api/surveys/${encodeURIComponent(surveyCode)}/bind`), {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...getAuthHeader() },
          body: JSON.stringify({ project_id: data.project_id }),
        }).catch((err) => console.error("Failed to link survey", err));
      }

      const templateId = surveyDetail?.template_id || null;
      saveChatMessage(data.project_id, "user", message, templateId);

      setSessions((currentList) =>
        (Array.isArray(currentList) ? currentList : []).map((session) =>
          session.id === newId
            ? { ...session, id: String(data.project_id), project_id: data.project_id }
            : session
        )
      );
      updateSessionId(newId, String(data.project_id));
      setActiveSessionId(String(data.project_id));

      setIsTyping(true);
      // 【修正｜串接真實 Gemini 分析，取代原本純前端組字串的假回覆】
      // 對應後端 POST /api/surveys/<code>/analyze，會真的對整份問卷觸發
      // PII 遮罩 → TF-IDF 去重 → Gemini 分類 → 依類別分組彙整，
      // 沿用跟 Excel 上傳分類同一套 buildClassificationMessageContent /
      // ClassificationTable 渲染邏輯，不用另外做一套畫面。
      (async () => {
        const assistantMsgId = `a-${Date.now()}`;
        try {
          if (!surveyCode) {
            throw new Error("Survey code not found. Unable to start analysis.");
          }
          const analyzeRes = await fetch(
            apiUrl(`/api/surveys/${encodeURIComponent(surveyCode)}/analyze`),
            { method: "POST", headers: getAuthHeader() }
          );
          const analyzeData = await analyzeRes.json();
          if (!analyzeRes.ok) {
            throw new Error(analyzeData?.error || `HTTP ${analyzeRes.status}`);
          }

          const assistantContent = buildClassificationMessageContent(
            analyzeData.aggregated_groups,
            {
              classified_count: analyzeData.newly_classified_count,
              source_filename: `${surveyTitle} (survey)`,
              // 【新增｜診斷訊息】沒有結果時，把後端算出來的原因帶過去，
              // 不要只顯示「沒有結果」讓使用者猜。
              diagnostic_message: analyzeData.diagnostic?.message,
            }
          );
          setSessions((currentList) =>
            (Array.isArray(currentList) ? currentList : []).map((session) =>
              session.id === String(data.project_id)
                ? {
                    ...session,
                    messages: [
                      ...(session.messages || []),
                      { id: assistantMsgId, role: "assistant", content: assistantContent },
                    ],
                  }
                : session
            )
          );
          const savedChatId = await saveChatMessage(data.project_id, "assistant", assistantContent, templateId);
          updateMessageChatId(String(data.project_id), assistantMsgId, savedChatId);
        } catch (err) {
          const errMsg = `Analysis failed: ${err?.message || "Network error"}`;
          setSessions((currentList) =>
            (Array.isArray(currentList) ? currentList : []).map((session) =>
              session.id === String(data.project_id)
                ? {
                    ...session,
                    messages: [
                      ...(session.messages || []),
                      { id: assistantMsgId, role: "assistant", content: errMsg },
                    ],
                  }
                : session
            )
          );
          saveChatMessage(data.project_id, "assistant", errMsg, templateId);
        } finally {
          setIsTyping(false);
        }
      })();
    })
    .catch((err) => console.error("Failed to create workspace for survey import", err));

    window.history.replaceState({}, "");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const appendMessage = useCallback((sessionId, msg) => {
    setSessions((currentList) =>
      (Array.isArray(currentList) ? currentList : []).map((session) =>
        session.id === sessionId
          ? { ...session, messages: [...(session.messages || []), msg] }
          : session
      )
    );
  }, [setSessions]);

  // 【新增｜串接 Export_File】把後端回傳的 chat_id 補到已經 append 進畫面
  // 的那則訊息上（只更新 React state，不影響存進資料庫的 message_content
  // 本身）。分類結果的匯出要綁在 chat_id 上（沿用既有 Export_File 設計），
  // 這個 chat_id 只有存訊息成功之後才拿得到，所以需要事後補上去。
  const updateMessageChatId = useCallback((sessionId, messageId, chatId) => {
    if (!chatId) return;
    setSessions((currentList) =>
      (Array.isArray(currentList) ? currentList : []).map((session) =>
        session.id === sessionId
          ? {
              ...session,
              messages: (session.messages || []).map((m) =>
                m.id === messageId ? { ...m, chatId } : m
              ),
            }
          : session
      )
    );
  }, [setSessions]);

  const saveChatMessage = useCallback(async (projectId, role, content, templateId = null) => {
    if (
      !projectId ||
      String(projectId).startsWith("temp-") ||
      String(projectId).startsWith("survey-")
    ) {
      console.log("[SaveChat] Temporary workspace detected; postponing sync: ", projectId);
      return null;
    }

    const intProjectId = Number(projectId);
    if (!Number.isInteger(intProjectId)) {
      console.error("[SaveChat] Invalid projectId: ", projectId);
      return null;
    }

    try {
      const res = await fetch(apiUrl("/api/chat/history"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({
          project_id: intProjectId,
          sender_type: role === "user" ? "user" : "ai",
          message_content: content,
          template_id: templateId ?? null,
        }),
      });

      if (!res.ok) {
        console.error("Failed to sync message to database: ", res.status);
        return null;
      }
      const data = await res.json();
      return data?.chat_history?.chat_id ?? null;
    } catch (err) {
      console.error("Failed to sync message to database", err);
      return null;
    }
  }, []);

  const handleSelectSurvey = async (record) => {
    const detail = normalizeSurveyDetail(record.detail);
    if (!detail || !activeSessionId) return;
    // 【修正｜改成簡短一行】原本會把整份問卷回覆逐字列出來，跟 SurveyDetailPage.jsx
    // 的 handleImportToChat 是同一個問題，一起改成一行簡短說明。
    const content = `[Survey: ${detail.title}] Start automatic analysis`;
    const userMsg = { id: `u-${Date.now()}`, role: "user", content };

    const selectedSession = sessions.find((session) => session.id === activeSessionId);
    const projectId = selectedSession?.project_id || activeSessionId;
    saveChatMessage(projectId, "user", content, detail.id);

    setSessions((currentList) =>
      (Array.isArray(currentList) ? currentList : []).map((session) =>
        session.id === activeSessionId
          ? { ...session, messages: [...(session.messages || []), userMsg] }
          : session
      )
    );
    setShowSurveyPicker(false);
    setSurveyPickerSearch("");

    setIsTyping(true);
    const sid = activeSessionId;
    // 【修正｜串接真實 Gemini 分析，取代原本純前端組字串的假回覆】
    // 跟「專案管理→匯入」那個入口共用同一套後端 API 跟渲染邏輯，
    // 只是問卷代碼、chat_id 的取得方式不同（這裡是已經在一個既有
    // session 裡挑問卷，不用另外建新的 workspace）。
    (async () => {
      const assistantMsgId = `a-${Date.now()}`;
      try {
        if (!detail.code) {
          throw new Error("Survey code not found. Unable to start analysis.");
        }
        const analyzeRes = await fetch(
          apiUrl(`/api/surveys/${encodeURIComponent(detail.code)}/analyze`),
          { method: "POST", headers: getAuthHeader() }
        );
        const analyzeData = await analyzeRes.json();
        if (!analyzeRes.ok) {
          throw new Error(analyzeData?.error || `HTTP ${analyzeRes.status}`);
        }

        const assistantContent = buildClassificationMessageContent(
          analyzeData.aggregated_groups,
          {
            classified_count: analyzeData.newly_classified_count,
            source_filename: `${detail.title} (survey)`,
            diagnostic_message: analyzeData.diagnostic?.message,
          }
        );
        setSessions((currentList) =>
          (Array.isArray(currentList) ? currentList : []).map((session) =>
            session.id === sid
              ? {
                  ...session,
                  messages: [
                    ...(session.messages || []),
                    { id: assistantMsgId, role: "assistant", content: assistantContent },
                  ],
                }
              : session
          )
        );
        const savedChatId = await saveChatMessage(projectId, "assistant", assistantContent, detail.id);
        updateMessageChatId(sid, assistantMsgId, savedChatId);
      } catch (err) {
        const errMsg = `Analysis failed: ${err?.message || "Network error"}`;
        setSessions((currentList) =>
          (Array.isArray(currentList) ? currentList : []).map((session) =>
            session.id === sid
              ? {
                  ...session,
                  messages: [
                    ...(session.messages || []),
                    { id: assistantMsgId, role: "assistant", content: errMsg },
                  ],
                }
              : session
          )
        );
        saveChatMessage(projectId, "assistant", errMsg, detail.id);
      } finally {
        setIsTyping(false);
      }
    })();
  };

  const surveyPickerRecords = getSurveyPickerRecords(apiSurveys);
  const filteredSurveyPicker = surveyPickerRecords.filter(
    (s) =>
      String(s.title || "").toLowerCase().includes(surveyPickerSearch.toLowerCase()) ||
      String(s.code || "").toLowerCase().includes(surveyPickerSearch.toLowerCase())
  );

  /* 【串backend】
   * 真的把 Excel 送去後端做 PII 遮罩 → TF-IDF 去重 → Gemini 分類，
   * 取代原本純前端算數字套句型的假分析。
   * 打的 API：POST /api/classification/upload （multipart/form-data: file, text_column）
   * debug 時先看這支 API 的 Network 回應，data.error 會直接顯示在聊天室裡。 */
  /* 【新增｜2026-08-27｜第 4 段｜串接後端核心】
   * 真的把 Excel 送去後端做 PII 遮罩 → TF-IDF 去重 → Gemini 分類，
   * 取代原本純前端算數字套句型的假分析。
   * 打的 API：POST /api/classification/upload （multipart/form-data: file）
   * 不用使用者輸入文字欄位名稱——後端會自動判斷最可能的開放式回答欄位，
   * 回傳的 text_column / text_column_auto_detected 讓畫面上可以顯示判斷結果。
   * debug 時先看這支 API 的 Network 回應，data.error 會直接顯示在聊天室裡。 */
  const runExcelClassification = async (file, sid, projectId) => {
    const userContent = `[File: ${file.name}] Upload and classify automatically`;
    const userMsg = { id: Date.now().toString(), role: "user", content: userContent };
    appendMessage(sid, userMsg);
    setIsClassifying(true);
    setIsTyping(true);

    if (projectId && !String(projectId).startsWith("temp-") && !String(projectId).startsWith("survey-")) {
      saveChatMessage(projectId, "user", userContent);
    }

    try {
      const form = new FormData();
      form.append("file", file);
      // 不附 text_column，交給後端自動判斷（見 backend/routes/classifications/classification.py
      // 的 _auto_detect_text_column）

      // 打後端 Gemini 分類的地方
      const res = await fetch(apiUrl("/api/classification/upload"), {
        method: "POST",
        headers: getAuthHeader(),
        body: form,
      });
      const data = await res.json();

      if (!res.ok) {
        const errMsg = `Classification failed: ${data?.error || res.status}`;
        appendMessage(sid, { id: `a-${Date.now()}`, role: "assistant", content: errMsg });
        showToast(errMsg);
        return;
      }

      const assistantContent = buildClassificationMessageContent(data.aggregated_groups, {
        classified_count: data.classified_count,
        saved_answer_count: data.saved_answer_count,
        upload_batch_id: data.upload_batch_id,
        text_column: data.text_column,
        text_column_auto_detected: data.text_column_auto_detected,
        // 【新增｜匯出檔名跟原始上傳檔名對應】方便使用者從匯出清單就
        // 知道這批結果對應哪一份原始 Excel。
        source_filename: file.name,
      });
      const assistantMsgId = `a-${Date.now()}`;
      appendMessage(sid, { id: assistantMsgId, role: "assistant", content: assistantContent });

      if (projectId && !String(projectId).startsWith("temp-") && !String(projectId).startsWith("survey-")) {
        // 【新增｜串接 Export_File】拿到這則訊息真正的 chat_id，補到訊息上——
        // 分類結果的匯出（Export_File）要綁在這個 chat_id 上，之後匯出按鈕
        // 才知道要把匯出紀錄掛在哪一則對話底下。
        const savedChatId = await saveChatMessage(projectId, "assistant", assistantContent);
        updateMessageChatId(sid, assistantMsgId, savedChatId);
      }
    } catch (err) {
      const errMsg = `Classification failed: ${err?.message || "Network error"}`;
      appendMessage(sid, { id: `a-${Date.now()}`, role: "assistant", content: errMsg });
      showToast(errMsg);
    } finally {
      setIsClassifying(false);
      setIsTyping(false);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() && !attachedFile) return;
    if (!activeSessionId) return;

    /* 【串backend】
     * 附加的是 Excel → 走真的分類流程，不走假分析，不需要使用者輸入欄位名稱
     * （後端自動判斷最可能的開放式回答欄位）。
     * 其他所有情況（沒附檔、附的不是 Excel）都會直接往下掉到原本的邏輯，
     * 跟改之前完全一樣，沒有被動到。 */
    if (attachedFile && isExcelFile(attachedFile)) {
      const sid = activeSessionId;
      const session = sessions.find((s) => s.id === sid);
      const projectId = session?.project_id;
      const file = attachedFile;
      setAttachedFile(null);
      setInput("");
      await runExcelClassification(file, sid, projectId);
      return;
    }

    const draftInput = input;
    const draftFile = attachedFile;
    const sid = activeSessionId;

    setInput("");
    setAttachedFile(null);
    setIsTyping(true);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    const content = draftFile ? `[File: ${draftFile.name}] ${draftInput}` : draftInput;
    const autoTitle = buildAutoSessionTitle(draftInput, draftFile);
    const userMsg = { id: Date.now().toString(), role: "user", content };

    setSessions((currentList) =>
      (Array.isArray(currentList) ? currentList : []).map((session) => {
        if (session.id !== sid) return session;
        const shouldAutoTitle = session.title === "New workspace";
        return {
          ...session,
          title: shouldAutoTitle ? autoTitle : session.title,
          messages: [...(session.messages || []), userMsg],
        };
      })
    );

    const session = sessions.find((s) => s.id === sid);
    if (session?.title === "New workspace") syncChatTitle(sid, autoTitle);

    const projectId = session?.project_id;

    // 先存訊息拿 chat_id
    const res = await fetch(apiUrl("/api/chat/history"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({
        project_id: Number(projectId),
        sender_type: "user",
        message_content: content,
      }),
    });
    const data = await res.json();
    const chatId = data?.chat_history?.chat_id;

    // 有檔案才上傳
    if (draftFile && chatId) {
      const form = new FormData();
      form.append("file", draftFile);
      await fetch(apiUrl(`/api/chat/${chatId}/files`), {
        method: "POST",
        headers: getAuthHeader(),
        body: form,
      });
    }

    setTimeout(() => {
      const reply = buildAssistantReply(content);
      const aiMsg = { id: Date.now().toString(), role: "assistant", content: reply };
      appendMessage(sid, aiMsg);
      setIsTyping(false);
      saveChatMessage(projectId, "assistant", reply);
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

  const filteredSessions = sessions.filter((session) =>
    String(session.title || "")
      .toLowerCase()
      .includes(searchQuery.toLowerCase())
  );

  const startRename = (s) => {
    setRenamingId(s.id);
    setRenameValue(s.title);
  };

  const saveRename = async (id) => {
    const trimmed = renameValue.trim();
    if (trimmed) {
      setSessions((currentList) =>
        (Array.isArray(currentList) ? currentList : []).map((session) =>
          session.id === id ? { ...session, title: trimmed } : session
        )
      );
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
          console.error("Rename failed", err);
        }
      }
    }
    setRenamingId(null);
  };

  const requestDeleteSession = (sessionId) => {
    const session = sessions.find((s) => s.id === sessionId);
    if (!session) return;
    setDeleteTarget(session);
  };

  // ── 刪除功能 ────────────────────────────────
  const isDeletingRef = useRef(false);

  const confirmDeleteSession = async () => {
    if (!deleteTarget) return;
    if (isDeletingRef.current) return; // 防止重複點擊刪除導致的多次呼叫
    isDeletingRef.current = true;
    setIsDeletingSession(true);

    const { id: sessionId } = deleteTarget;

    try {
      await deleteChatSession(sessionId);
      setDeleteTarget(null);

      setRenamingId(null);
      setSearchQuery("");

      if (activeSessionId === sessionId) {
        const nextSession = sessions.find(
          (session) => session.id !== sessionId
        );

        setActiveSessionId(nextSession?.id || null);

        if (nextSession?.id) {
          localStorage.setItem(ACTIVE_WORKSPACE_KEY, nextSession.id);
        } else {
          localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
        }
      }

      showToast("Workspace moved to Recently deleted");
    } catch (err) {
      console.error("Failed to delete workspace", err);
      showToast("Deletion failed. Please try again later.");
    } finally {
      isDeletingRef.current = false;
      setIsDeletingSession(false);
    }
  };

  // ── 建立新工作區 ─────────────
  const createNewSession = async () => {
    const title = "New workspace";
    const tempId = `temp-${Date.now()}`;

    const tempSession = {
      id: tempId,
      title,
      date: new Date().toLocaleDateString("en-US"),
      messages: [WELCOME_MSG],
    };
    setSessions((currentList) => [
      tempSession,
      ...(Array.isArray(currentList) ? currentList : []),
    ]);
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

      if (!res.ok) {
        console.error("Failed to create workspace via API: ", res.status);
        return;
      }

      const data = await res.json();
      if (!data?.project_id) {
        console.error("Failed to create workspace: no project ID returned");
        return;
      }

      const newId = String(data.project_id);
      setSessions((currentList) =>
        (Array.isArray(currentList) ? currentList : []).map((session) =>
          session.id === tempId
            ? { ...session, id: newId, project_id: data.project_id }
            : session
        )
      );
      updateSessionId(tempId, newId);
      setActiveSessionId(newId);
    } catch (err) {
      console.error("Failed to create workspace", err);
    }
  };

  if (!isLoggedIn) {
    return (
      <>
        <Navbar />
        <div className="workspace-page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
          <LoginRequiredModal
            message="Please log in to create a workspace and start analyzing data."
            onLogin={() => navigate("/login")}
            onCancel={() => navigate("/")}
          />
        </div>
      </>
    );
  }

  if (isEntryLoading || historyLoadingSessionId) {
    return (
      <>
        <Navbar />
        <main className="workspace-entry-loading-page">
          <div className="workspace-entry-loading-card" role="status" aria-live="polite">
            <div className="workspace-entry-loading-icon">
              <i className="ri-loader-4-line"></i>
            </div>
            <h1>{isEntryLoading ? "Loading workspace…" : "Loading conversation history…"}</h1>
            <p>{isEntryLoading ? "Preparing your projects, conversation history, and analysis data. Please wait." : "Retrieving this chat's history. It will appear automatically when ready."}</p>
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <Navbar />
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
                <span className="sidebar-title">Conversation history</span>
              </div>
              <div className="sidebar-search">
                <i className="ri-search-line"></i>
                <input
                  type="text"
                  placeholder="Search conversation history…"
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
                  <p>No workspace history</p>
                  <button
                    onClick={createNewSession}
                    style={{
                      marginTop: 8, background: "#c9a0a0", color: "white",
                      border: "none", borderRadius: 8, padding: "6px 14px",
                      fontSize: 12, fontWeight: 700, cursor: "pointer",
                    }}
                  >
                    New workspace
                  </button>
                </div>
              ) : filteredSessions.length === 0 ? (
                <div className="sidebar-empty">
                  <i className="ri-search-line"></i>
                  <p>No matching records</p>
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
                      title="Rename"
                    >
                      <i className="ri-pencil-line"></i>
                    </button>
                    <button
                      className="session-delete"
                      onClick={(e) => { e.stopPropagation(); requestDeleteSession(s.id); }}
                      title="Delete workspace"
                    >
                      <i className="ri-delete-bin-line"></i>
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className="sidebar-footer">
              <button className="btn-new-session sidebar-bottom-add" onClick={createNewSession} title="New workspace">
                <i className="ri-add-line"></i>
              </button>
            </div>
          </aside>

          {/* Main Chat */}
          <main className="workspace-main">
            <div className="workspace-share-float">
              <button className="workspace-share-btn" type="button" onClick={handleInviteView} disabled={isSharing}>
                <i className="ri-eye-line"></i>
                <span>{isSharing ? "Creating link…" : "Invite viewers"}</span>
              </button>
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
                <p style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Select or create a workspace to start analyzing</p>
                <button
                  onClick={createNewSession}
                  style={{
                    background: "#c9a0a0", color: "white", border: "none",
                    borderRadius: 10, padding: "10px 24px", fontSize: 14,
                    fontWeight: 700, cursor: "pointer",
                  }}
                >
                  <i className="ri-add-line" style={{ marginRight: 6 }}></i>New workspace
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
                        <MessageContent message={msg} showToast={showToast} />
                      </div>
                    </div>
                  ))}
                  {isTyping && (
                    <div className="message-row">
                      <div className="message-avatar assistant-avatar">
                        <i className="ri-robot-line"></i>
                      </div>
                      <div className="message-bubble assistant-bubble typing-bubble">
                        <span className="typing-label">AI is thinking</span>
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
                      {isExcelFile(attachedFile) && (
                        <span className="classification-hint">(Automatically classified after sending)</span>
                      )}
                      <button onClick={() => setAttachedFile(null)} disabled={isClassifying}>
                        <i className="ri-close-line"></i>
                      </button>
                    </div>
                  )}
                  {/* 【串backend】原本這裡有一個要求使用者輸入文字欄位名稱的輸入框，
                      已移除——欄位名稱改由後端自動判斷（見 runExcelClassification 說明），
                      使用者只要附加 Excel 直接送出即可。 */}
                  <div className="input-wrapper">
                    <div className="survey-picker-wrapper" ref={surveyPickerRef}>
                      <button
                        className={`attach-btn survey-pick-btn${showSurveyPicker ? " active" : ""}`}
                        onClick={() => setShowSurveyPicker((v) => !v)}
                        title="Choose a survey to analyze"
                      >
                        <i className="ri-survey-line"></i>
                      </button>
                      {showSurveyPicker && (
                        <div className="survey-picker-panel">
                          <div className="survey-picker-header">
                            <span className="survey-picker-title">
                              <i className="ri-survey-line"></i>
                              Choose a survey to analyze
                            </span>
                            <button className="survey-picker-close" onClick={() => setShowSurveyPicker(false)}>
                              <i className="ri-close-line"></i>
                            </button>
                          </div>
                          <div className="survey-picker-search">
                            <i className="ri-search-line"></i>
                            <input
                              type="text"
                              placeholder="Search survey title or code…"
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
                            {isSurveyPickerLoading ? (
                              <div className="survey-picker-loading" role="status" aria-live="polite">
                                <i className="ri-loader-4-line ri-spin"></i>
                                <span>Loading surveys…</span>
                              </div>
                            ) : filteredSurveyPicker.length === 0 ? (
                              <div className="survey-picker-empty">
                                <i className="ri-search-line"></i>
                                <p>No matching surveys</p>
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
                                      <span><i className="ri-user-line"></i>{s.responseCount} responses</span>
                                      <span><i className="ri-calendar-line"></i>{s.createdAt}</span>
                                    </div>
                                  </div>
                                  <span className={`survey-picker-status${s.status === "active" ? " active" : ""}`}>
                                    {s.status === "active" ? "Active" : "Closed"}
                                  </span>
                                </button>
                              ))
                            )}
                          </div>
                        </div>
                      )}
                    </div>

                    <button
                      className="attach-btn"
                      onClick={() => fileInputRef.current?.click()}
                      title="Attach file"
                    >
                      <i className="ri-attachment-line"></i>
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="d-none"
                      accept=".csv,.xlsx,.txt"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setAttachedFile(f);
                        showToast(`「${f.name} attached. It will be uploaded when you send the message.`);
                        e.target.value = "";
                      }}
                    />
                    <textarea
                      ref={textareaRef}
                      rows={1}
                      placeholder="Ask a question or upload a file for analysis…"
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
                    Click the survey icon to analyze a survey · Supports CSV, Excel, and TXT · Press Enter to send
                  </p>
                </div>
              </>
            )}
          </main>
        </div>
      </div>
      {shareInvite && <ShareWorkspaceDialog invite={shareInvite} onClose={() => setShareInvite(null)} />}
      {deleteTarget && (
        <div className="workspace-modal-backdrop" onClick={() => !isDeletingSession && setDeleteTarget(null)}>
          <div className="workspace-alert-modal" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-alert-icon">
              <i className="ri-error-warning-line"></i>
            </div>
            <h3>Delete workspace</h3>
            <p>Delete {deleteTarget.title}? You can restore it from Recently deleted in Project Management.</p>
            <div className="workspace-alert-actions">
              <button className="workspace-alert-primary" onClick={confirmDeleteSession} type="button" disabled={isDeletingSession}>
                {isDeletingSession ? "Deleting…" : "OK"}
              </button>
              <button className="workspace-alert-secondary" onClick={() => setDeleteTarget(null)} type="button" disabled={isDeletingSession}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
