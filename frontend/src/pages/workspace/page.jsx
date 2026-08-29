import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import LoginRequiredModal from "../../components/feature/LoginRequiredModal";
import { useAuth } from "../../hooks/AuthContext";
import { useCollection } from "../../hooks/CollectionContext";
import { useActivity } from "../../hooks/ActivityContext";
import { apiUrl } from "../../lib/api";
import { buildSurveyChatContent as buildSharedSurveyChatContent } from "../../lib/surveyChatContent";
import "./workspace.css";

const WELCOME_MSG = {
  id: "welcome",
  role: "assistant",
  content:
    "您好！我是 DataAnalysis AI 助手。請上傳您的資料檔案（CSV、Excel 或 TXT），或直接輸入您的分析問題，我將為您提供深度洞察。",
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
    title: survey?.title || survey?.survey_name || "未命名問卷",
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

// 【新增｜匯出功能】把分類結果匯出成 CSV，讓使用者能真的下載檔案。
// 純前端實作，不用等後端支援：資料本來就已經在畫面上了。
// 開頭加 UTF-8 BOM，不然中文在 Excel 打開會變亂碼。
function downloadClassificationCSV(rows) {
  const headers = ["大類別", "子類別", "問卷回覆內容", "判斷原因與說明", "受試者建議摘要"];
  const escapeCell = (val) => {
    const s = String(val ?? "");
    // 內容裡有逗號、換行、雙引號的話，CSV 規範要求整格用雙引號包起來，
    // 裡面原本的雙引號要變成兩個雙引號escape
    if (/[",\n]/.test(s)) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  };
  const lines = [
    headers.map(escapeCell).join(","),
    ...rows.map((row, i, arr) => {
      // 【新增】CSV 也跟畫面一致：大類別跟前一列相同時留空，不重複寫
      const mainCategoryCell = i > 0 && arr[i - 1].main_category === row.main_category ? "" : row.main_category;
      return [mainCategoryCell, row.sub_category, row.respondent_text, row.aggregated_reasoning, row.aggregated_summary]
        .map(escapeCell)
        .join(",");
    }),
  ];
  const csvContent = "\uFEFF" + lines.join("\r\n"); // \uFEFF = UTF-8 BOM

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  a.href = url;
  a.download = `分類結果_${timestamp}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* 【串backend】渲染真實分類結果的表格元件。
 * 5 欄對照使用者要的格式：大類別／子類別／問卷回覆內容／判斷原因與說明／受試者建議摘要。
 * 資料來源：parseClassificationMessageContent() 從訊息內容還原出來的 rows。 */
// 把用 \n 分隔的多行文字渲染成真的換行（respondent_text、fallback 時的
// aggregated_reasoning/aggregated_summary 都可能是這種多行字串）
function MultilineText({ text }) {
  return (text || "").split("\n").map((line, i) => (
    <span key={i}>
      {i > 0 && <br />}
      {line}
    </span>
  ));
}

function ClassificationTable({ rows, meta }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="assistant-output-panel">
        <div className="assistant-output-intro">這批資料沒有產生任何分類結果。</div>
      </div>
    );
  }

  const totalRespondents = rows.reduce((sum, r) => sum + (r.respondent_count || 0), 0);

  return (
    <div className="assistant-output-panel assistant-output-panel--wide">
      <div className="assistant-output-intro">
        分類完成，共 {rows.length} 個類別
        {totalRespondents > 0 ? `（涵蓋 ${totalRespondents} 位受試者）` : ""}。
        {meta?.text_column && (
          <>
            {" "}系統判斷的文字欄位是「{meta.text_column}」
            {meta.text_column_auto_detected ? "（自動判斷）" : ""}
            {meta.text_column_auto_detected && "，如果判斷錯了，請確認 Excel 欄位標題是否清楚描述內容。"}
          </>
        )}
      </div>
      <div className="assistant-output-table-wrap">
        <table className="assistant-output-table classification-table">
          <thead>
            <tr>
              <th>大類別</th>
              <th>子類別</th>
              <th>問卷回覆內容</th>
              <th>判斷原因與說明</th>
              <th>受試者建議摘要</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              // 【修正】改用真正的表格 rowSpan 合併儲存格，而不是留空行模擬——
              // 這樣「置中」才會是整個合併區塊的正中央，不是卡在第一列。
              const isSameMainAsPrev = index > 0 && rows[index - 1].main_category === row.main_category;
              let mainCategoryRowSpan = 1;
              if (!isSameMainAsPrev) {
                for (let j = index + 1; j < rows.length && rows[j].main_category === row.main_category; j++) {
                  mainCategoryRowSpan++;
                }
              }
              return (
                <tr key={index}>
                  {/* rowSpan 合併儲存格：只有區塊第一列要渲染這個 <td>，
                      後面被合併的列完全不渲染，交給瀏覽器的 rowSpan 機制處理，
                      不能渲染空的 <td> 出來，不然表格欄位數量會對不齊。 */}
                  {!isSameMainAsPrev && (
                    <td rowSpan={mainCategoryRowSpan} className="merged-cell-center">
                      {row.main_category}
                    </td>
                  )}
                  <td className="sub-category-cell">{row.sub_category}</td>
                  <td>
                    {/* 受試者片段每人一行，respondent_text 裡本來就用 \n 分隔 */}
                    <MultilineText text={row.respondent_text} />
                  </td>
                  <td><MultilineText text={row.aggregated_reasoning} /></td>
                  <td>
                    <MultilineText text={row.aggregated_summary} />
                    {row.synthesis_status === "fallback" && (
                      <div className="synthesis-fallback-note">
                        （彙整摘要暫時失敗，以下為個別意見簡易拼接，非完整統整）
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {/* 【新增｜匯出功能】真的能下載 CSV，不是原本那個只會導到空頁面的假按鈕 */}
      <div className="assistant-output-actions">
        <button
          className="assistant-export-btn"
          type="button"
          onClick={() => downloadClassificationCSV(rows)}
        >
          <i className="ri-download-cloud-2-line"></i>
          匯出成 CSV
        </button>
      </div>
    </div>
  );
}

function MessageContent({ message }) {
  // 優先判斷是不是真分類結果訊息，是的話直接渲染表格，
  // 不要讓它掉進下面 AssistantTableContent 那個舊的、給假分析用的文字解析邏輯。
  const classificationData = parseClassificationMessageContent(message.content);
  if (classificationData) {
    return <ClassificationTable rows={classificationData.rows} meta={classificationData.meta} />;
  }
  // 【新增區塊到此為止，以下都是原本就有的邏輯，沒有改動】

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
  const [toastMsg, setToastMsg] = useState(null);
  const [isEntryLoading, setIsEntryLoading] = useState(() => sessionStorage.getItem("dataanalysis_login_loading") === "1");
  const [historyLoadingSessionId, setHistoryLoadingSessionId] = useState(() => location.state?.openSession?.sessionId || null);
  const [isSurveyPickerLoading, setIsSurveyPickerLoading] = useState(true);
  const toastTimerRef = useRef(null);

  const messagesEndRef = useRef(null);
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
        console.error("載入問卷清單失敗", err);
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
          console.error("載入 workspace API 失敗：", res.status);
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
              title: workspace.project_name || "未命名工作區",
              folder_name: workspace.folder_name ?? null,
              date: workspace.created_at
                ? new Date(workspace.created_at).toLocaleDateString()
                : "",
              messages: existing?.messages || [WELCOME_MSG],
            };
          });

          return [...localOnly, ...fromBackend];
        });
      } catch (err) {
        console.error("載入 workspace 失敗", err);
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
          console.error("動態載入歷史對話失敗：", err);
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
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

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
      date: new Date().toLocaleDateString(),
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
        }).catch((err) => console.error("問卷綁定失敗", err));
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
      setTimeout(() => {
        const aiReply = buildAssistantReply(message, surveyDetail || null, surveyTitle);
        setSessions((currentList) =>
          (Array.isArray(currentList) ? currentList : []).map((session) =>
            session.id === String(data.project_id)
              ? {
                  ...session,
                  messages: [
                    ...(session.messages || []),
                    { id: `a-${Date.now()}`, role: "assistant", content: aiReply },
                  ],
                }
              : session
          )
        );
        setIsTyping(false);
        saveChatMessage(data.project_id, "assistant", aiReply, templateId);
      }, 1800);
    })
    .catch((err) => console.error("問卷匯入建立 workspace 失敗", err));

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

  const saveChatMessage = useCallback(async (projectId, role, content, templateId = null) => {
    if (
      !projectId ||
      String(projectId).startsWith("temp-") ||
      String(projectId).startsWith("survey-")
    ) {
      console.log("[SaveChat] 偵測到臨時工作區，暫緩同步至後端：", projectId);
      return;
    }

    const intProjectId = Number(projectId);
    if (!Number.isInteger(intProjectId)) {
      console.error("[SaveChat] projectId 格式錯誤：", projectId);
      return;
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
        console.error("訊息同步至資料庫失敗：", res.status);
      }
    } catch (err) {
      console.error("訊息同步至資料庫失敗", err);
    }
  }, []);

  const handleSelectSurvey = async (record) => {
    const detail = normalizeSurveyDetail(record.detail);
    if (!detail || !activeSessionId) return;
    const content = buildSharedSurveyChatContent(detail);
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
    setTimeout(() => {
      const aiReply = buildAssistantReply(content, detail, record.title);
      
      setSessions((currentList) =>
        (Array.isArray(currentList) ? currentList : []).map((session) =>
          session.id === sid
            ? {
                ...session,
                messages: [
                  ...(session.messages || []),
                  { id: `a-${Date.now()}`, role: "assistant", content: aiReply },
                ],
              }
            : session
        )
      );
      setIsTyping(false);
      saveChatMessage(projectId, "assistant", aiReply, detail.id);
    }, 1800);
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
    const userContent = `[檔案：${file.name}] 上傳並自動分類`;
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
        const errMsg = `分類失敗：${data?.error || res.status}`;
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
      });
      appendMessage(sid, { id: `a-${Date.now()}`, role: "assistant", content: assistantContent });

      if (projectId && !String(projectId).startsWith("temp-") && !String(projectId).startsWith("survey-")) {
        saveChatMessage(projectId, "assistant", assistantContent);
      }
    } catch (err) {
      const errMsg = `分類失敗：${err?.message || "網路錯誤"}`;
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

    const content = draftFile ? `[檔案：${draftFile.name}] ${draftInput}` : draftInput;
    const autoTitle = buildAutoSessionTitle(draftInput, draftFile);
    const userMsg = { id: Date.now().toString(), role: "user", content };

    setSessions((currentList) =>
      (Array.isArray(currentList) ? currentList : []).map((session) => {
        if (session.id !== sid) return session;
        const shouldAutoTitle = session.title === "新工作區";
        return {
          ...session,
          title: shouldAutoTitle ? autoTitle : session.title,
          messages: [...(session.messages || []), userMsg],
        };
      })
    );

    const session = sessions.find((s) => s.id === sid);
    if (session?.title === "新工作區") syncChatTitle(sid, autoTitle);

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
          console.error("重新命名失敗", err);
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

      showToast("已刪除工作區，並移至最近刪除");
    } catch (err) {
      console.error("刪除工作區失敗", err);
      showToast("刪除失敗，請稍後再試");
    } finally {
      isDeletingRef.current = false;
      setIsDeletingSession(false);
    }
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
        console.error("新增工作區 API 失敗：", res.status);
        return;
      }

      const data = await res.json();
      if (!data?.project_id) {
        console.error("新增工作區失敗：後端未回傳 project_id");
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

  if (isEntryLoading || historyLoadingSessionId) {
    return (
      <>
        <Navbar />
        <main className="workspace-entry-loading-page">
          <div className="workspace-entry-loading-card" role="status" aria-live="polite">
            <div className="workspace-entry-loading-icon">
              <i className="ri-loader-4-line"></i>
            </div>
            <h1>{isEntryLoading ? "正在載入工作區..." : "正在載入歷史對話..."}</h1>
            <p>{isEntryLoading ? "正在整理您的專案管理、歷史對話紀錄與分析資料，請稍候。" : "正在取得這個 Chat 的歷史資料，完成後會自動顯示。"}</p>
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
                <span className="sidebar-title">歷史對話紀錄</span>
              </div>
              <div className="sidebar-search">
                <i className="ri-search-line"></i>
                <input
                  type="text"
                  placeholder="搜尋歷史對話紀錄..."
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
            <div className="workspace-share-float">
              <button className="workspace-share-btn" type="button">
                <i className="ri-eye-line"></i>
                <span>邀請檢視</span>
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
                        <span className="typing-label">AI 思考中</span>
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
                        <span className="classification-hint">（送出後將自動分類）</span>
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
                            {isSurveyPickerLoading ? (
                              <div className="survey-picker-loading" role="status" aria-live="polite">
                                <i className="ri-loader-4-line ri-spin"></i>
                                <span>問卷載入中...</span>
                              </div>
                            ) : filteredSurveyPicker.length === 0 ? (
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
                      accept=".csv,.xlsx,.txt"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setAttachedFile(f);
                        showToast(`「${f.name}」已附加，發送後將上傳`);
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
                    點擊問卷圖示可直接選擇問卷分析 · 支援 CSV、Excel、TXT · Enter 發送
                  </p>
                </div>
              </>
            )}
          </main>
        </div>
      </div>
      {deleteTarget && (
        <div className="workspace-modal-backdrop" onClick={() => !isDeletingSession && setDeleteTarget(null)}>
          <div className="workspace-alert-modal" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-alert-icon">
              <i className="ri-error-warning-line"></i>
            </div>
            <h3>刪除工作區</h3>
            <p>確定要刪除「{deleteTarget.title}」嗎？刪除後可在專案管理的最近刪除中還原。</p>
            <div className="workspace-alert-actions">
              <button className="workspace-alert-primary" onClick={confirmDeleteSession} type="button" disabled={isDeletingSession}>
                {isDeletingSession ? "刪除中..." : "確定"}
              </button>
              <button className="workspace-alert-secondary" onClick={() => setDeleteTarget(null)} type="button" disabled={isDeletingSession}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}