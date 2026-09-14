import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../../components/feature/Navbar";
import DeadlineDateTimePicker from "../../../components/feature/DeadlineDateTimePicker";
import { buildExternalSurveyShortUrl, buildSurveyFillUrl } from "../../../lib/surveyLinks";
// 【修正】原本這裡有 import buildSurveyChatContent，用來組出使用者訊息的完整文字內容，現在改成簡短一行不再需要這個函式，拿掉未使用的 import。

const TYPE_LABELS = {
  rating: "Rating",
  short: "Short answer",
  long: "Long answer",
  single: "Single choice",
  multiple: "Multiple choice",
};

function displayAnswer(value) {
  if (Array.isArray(value)) return value.join("、");
  return value || "Not answered";
}

function toDateTimeLocalValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 16);
}

function getNextDeadlineMin() {
  const nextMinute = new Date(Date.now() + 60000);
  nextMinute.setSeconds(0, 0);
  return toDateTimeLocalValue(nextMinute);
}

function formatDeadline(value) {
  if (!value) return "Not set";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function RatingStats({ question, responses, qNum }) {
  const counts = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  let total = 0;
  let answered = 0;

  if (!question) return null;
  const safeResponses = Array.isArray(responses) ? responses : [];
  const qId = question.id !== undefined ? question.id : question.question_id;

  safeResponses.forEach((response) => {
    if (!response || !response.answers) return;
    const value = Number(response.answers[qId]);
    if (Number.isFinite(value) && value >= 0 && value <= 5) {
      counts[value] += 1;
      total += value;
      answered += 1;
    }
  });

  const avg = answered ? (total / answered).toFixed(1) : "-";
  const max = Math.max(...Object.values(counts), 1);

  return (
    <div className="sdp-rating-card">
      <div className="sdp-rating-card-header">
        <span className="sdp-q-badge">Q{qNum}</span>
        <span className="sdp-rating-card-title">{question.title || question.question_title || "Untitled question"}</span>
      </div>
      <div className="sdp-rating-stats">
        <div className="sdp-avg-block">
          <div className="sdp-avg-circle">
            <span className="sdp-avg-num">{avg}</span>
            <span className="sdp-avg-sub">/ 5</span>
          </div>
          <div className="sdp-avg-info">
            <div className="sdp-avg-label">Average score</div>
            <div className="sdp-avg-count">{answered}  responses</div>
          </div>
        </div>
        <div className="sdp-bars">
          {[0, 1, 2, 3, 4, 5].map((score) => (
            <div key={score} className={`sdp-bar-row ${counts[score] > 0 ? "has-responses" : ""}`}>
              <div className="sdp-bar-score">{score}</div>
              <div className="sdp-bar-track">
                <div className="sdp-bar-fill" style={{ width: `${(counts[score] / max) * 100}%` }} />
              </div>
              <div className="sdp-bar-count">{counts[score]}  respondents</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ResponseTable({ questions, responses }) {
  const safeQuestions = Array.isArray(questions) ? questions : [];
  const safeResponses = Array.isArray(responses) ? responses : [];

  return (
    <div className="sdp-table-wrapper">
      <div className="sdp-table-scroll">
        <table className="sdp-table">
          <thead>
            <tr>
              <th className="sdp-th sdp-th-idx">#</th>
              <th className="sdp-th sdp-th-identity">Respondent</th>
              <th className="sdp-th sdp-th-time">Submitted</th>
              {safeQuestions.map((question, index) => (
                <th key={question.id || question.question_id || index} className="sdp-th sdp-th-q">
                  <div className="sdp-th-q-num">Q{index + 1}</div>
                  <div className="sdp-th-q-title">{question.title || question.question_title || "Untitled question"}</div>
                  <div className="sdp-th-q-type">
                    {TYPE_LABELS[question.type || question.question_type] || question.type || question.question_type || "Open-ended"}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {safeResponses.map((response, index) => (
              <tr key={response.respondentId || response.respondent_id || index} className={index % 2 === 0 ? "sdp-tr-even" : "sdp-tr-odd"}>
                <td className="sdp-td sdp-td-idx">{index + 1}</td>
                <td className="sdp-td sdp-td-identity">
                  {response.respondentIdentity || response.respondent_identity || "Anonymous"}
                </td>
                <td className="sdp-td sdp-td-time">{response.submittedAt || response.submitted_at || "—"}</td>
                {safeQuestions.map((question, qIdx) => {
                  const qId = question.id !== undefined ? question.id : question.question_id;
                  const ans = response.answers ? response.answers[qId] : undefined;
                  return (
                    <td key={question.id || question.question_id || qIdx} className="sdp-td sdp-td-ans">
                      {displayAnswer(ans)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function buildSurveyChatContent(survey, questions, responses) {
  const lines = [
    `Survey: ${survey.title || survey.survey_name || "Untitled survey"}`,
    `Invite code: ${survey.code}`,
    `Created: ${survey.createdAt || survey.created_at || "—"}`,
    `Responses: ${responses.length}`,
    "",
    "Please analyze response trends, potential insights, and recommended next steps for this survey.",
  ];

  questions.forEach((question, index) => {
    const qId = question.id !== undefined ? question.id : question.question_id;
    lines.push(`Q${index + 1}. ${question.title || question.question_title}`);
    responses.slice(0, 8).forEach((response, responseIndex) => {
      if (!response || !response.answers) return;
      const identity = response.respondentIdentity || response.respondent_identity;
      const identityLabel = identity ? `Respondent: ${identity}，` : "";
      lines.push(`  ${responseIndex + 1}. ${identityLabel}${displayAnswer(response.answers[qId])}`);
    });
  });
  return lines.join("\n");
}

export default function SurveyDetailPage({ survey, onBack, onUpdateDeadline, onImportToChat }) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("overview");
  const [importSuccess, setImportSuccess] = useState(false);
  const [copyCodeSuccess, setCopyCodeSuccess] = useState(false);
  const [copyLinkSuccess, setCopyLinkSuccess] = useState(false);
  const [externalSurveyLink, setExternalSurveyLink] = useState("");
  const [isShorteningLink, setIsShorteningLink] = useState(false);

  // 避免 survey 為空時引發閃退白屏
  const currentSurvey = survey || {};
  const questions = Array.isArray(currentSurvey.questions) ? currentSurvey.questions : [];
  const responses = Array.isArray(currentSurvey.responses) ? currentSurvey.responses : [];

  const [deadlineValue, setDeadlineValue] = useState(toDateTimeLocalValue(currentSurvey.deadlineAt || currentSurvey.deadline_at));
  const [minDeadlineValue, setMinDeadlineValue] = useState(() => getNextDeadlineMin());
  const [deadlineStatus, setDeadlineStatus] = useState("");
  const [isSavingDeadline, setIsSavingDeadline] = useState(false);

  const ratingQuestions = questions.filter((question) => (question.type || question.question_type) === "rating");
  const textQuestions = questions.filter((question) => (question.type || question.question_type) !== "rating");
  const fallbackSurveyLink = buildSurveyFillUrl(currentSurvey);
  const surveyLink = externalSurveyLink || (!isShorteningLink ? fallbackSurveyLink : "");

  useEffect(() => {
    setDeadlineValue(toDateTimeLocalValue(currentSurvey.deadlineAt || currentSurvey.deadline_at));
    setDeadlineStatus("");
  }, [currentSurvey.deadlineAt, currentSurvey.deadline_at]);

  useEffect(() => {
    if (!currentSurvey.code && !currentSurvey.access_code && !currentSurvey.shortCode && !currentSurvey.short_code) {
      setExternalSurveyLink("");
      setIsShorteningLink(false);
      return;
    }

    let cancelled = false;
    setExternalSurveyLink("");
    setIsShorteningLink(true);
    buildExternalSurveyShortUrl(currentSurvey).then((shortUrl) => {
      if (cancelled) return;
      setExternalSurveyLink(shortUrl);
      setIsShorteningLink(false);
    }).catch(() => {
      if (cancelled) return;
      setIsShorteningLink(false);
    });

    return () => {
      cancelled = true;
    };
  }, [currentSurvey.code, currentSurvey.access_code, currentSurvey.shortCode, currentSurvey.short_code]);

  useEffect(() => {
    const updateMinDeadline = () => setMinDeadlineValue(getNextDeadlineMin());
    updateMinDeadline();
    const timer = window.setInterval(updateMinDeadline, 30000);
    return () => window.clearInterval(timer);
  }, []);

  if (!survey) return null;

  const handleCopyCode = async () => {
    try {
      await navigator.clipboard.writeText(currentSurvey.code || "");
      setCopyCodeSuccess(true);
      setTimeout(() => setCopyCodeSuccess(false), 1600);
    } catch {
      setCopyCodeSuccess(false);
      alert("Copy failed. Please copy the invite code manually.");
    }
  };

  const handleCopySurveyLink = async () => {
    if (!surveyLink) return;
    try {
      await navigator.clipboard.writeText(surveyLink);
      setCopyLinkSuccess(true);
      setTimeout(() => setCopyLinkSuccess(false), 1600);
    } catch {
      setCopyLinkSuccess(false);
      alert("Unable to copy the link. Please select and copy it manually.");
    }
  };

  const handleImportToChat = () => {
    setImportSuccess(true);
    setTimeout(() => {
      const surveyTitle = currentSurvey.title || currentSurvey.survey_name || "Untitled survey";
      onImportToChat?.({
        survey: currentSurvey,
        questions,
        responses,
        sessionTitle: `Survey analysis: ${surveyTitle}`,
        // 【改成簡短一行，不要把整份問卷回覆逐字列出來】原本
        // 這裡用 buildSharedSurveyChatContent(...) 會把每一題、每個人
        // 的回答全部列成一大段文字塞進使用者訊息，跟真正的分析邏輯
        // 完全無關（分析是後端直接讀資料庫），純粹是顯示太冗長，
        // 比照 Excel 上傳那條路改成一行簡短說明。
        message: `[Survey: ${surveyTitle}] Start automatic analysis`,
      });
    }, 450);
  };

  const handleSaveDeadline = async () => {
    if (!deadlineValue) {
      setDeadlineStatus("Please choose a deadline date and time.");
      return;
    }
    if (new Date(deadlineValue).getTime() <= Date.now()) {
      setDeadlineStatus("The deadline must be later than now.");
      return;
    }
    setIsSavingDeadline(true);
    setDeadlineStatus("");
    try {
      await onUpdateDeadline?.(currentSurvey, deadlineValue);
      setDeadlineStatus("Deadline updated.");
    } catch (error) {
      setDeadlineStatus(error.message || "Failed to update deadline.");
    } finally {
      setIsSavingDeadline(false);
    }
  };

  return (
    <>
      <Navbar />
      <div className="sdp-root">
        <div className="sdp-header-fixed">
          <div className="sdp-topbar">
            <button className="sdp-back-btn" onClick={onBack}>
              <i className="ri-arrow-left-line"></i>Back to survey
            </button>
            <div className="sdp-topbar-center">
              <h1 className="sdp-topbar-title">{currentSurvey.title || currentSurvey.survey_name || "Untitled survey"}</h1>
              <div className="sdp-topbar-meta">
                <span><i className="ri-calendar-line"></i>{currentSurvey.createdAt || currentSurvey.created_at || "—"}</span>
                <span><i className="ri-time-line"></i>Deadline {formatDeadline(currentSurvey.deadlineAt || currentSurvey.deadline_at)}</span>
                <span><i className="ri-user-line"></i>{responses.length} responses</span>
                <span><i className="ri-question-line"></i>{questions.length}  questions</span>
              </div>
            </div>
            <div className="sdp-topbar-right">
              <div className="sdp-code-card">
                <div className="sdp-code-label">
                  <i className="ri-key-2-line"></i>Survey code
                </div>
                <div className="sdp-code-row">
                  <span className="sdp-code-value">{currentSurvey.code}</span>
                  <button className="sdp-copy-code-btn" onClick={handleCopyCode} type="button">
                    <i className={copyCodeSuccess ? "ri-checkbox-circle-line" : "ri-file-copy-line"}></i>
                    {copyCodeSuccess ? "Copied" : "Copy code"}
                  </button>
                </div>
              </div>
              <div className="sdp-deadline-card sdp-deadline-card-top">
                <label className="sdp-code-label" htmlFor="survey-deadline-input">
                  <i className="ri-time-line"></i>Deadline
                </label>
                <div className="sdp-deadline-row">
                  <DeadlineDateTimePicker
                    id="survey-deadline-input"
                    className="sdp-deadline-picker"
                    value={deadlineValue}
                    min={minDeadlineValue}
                    onChange={setDeadlineValue}
                    compact
                  />
                  <button className="sdp-deadline-save-btn" onClick={handleSaveDeadline} disabled={isSavingDeadline} type="button">
                    <i className={isSavingDeadline ? "ri-loader-4-line" : "ri-save-line"}></i>
                    {isSavingDeadline ? "Saving" : "Save"}
                  </button>
                </div>
                {deadlineStatus && <div className="sdp-deadline-status">{deadlineStatus}</div>}
              </div>
              <button className={`sdp-import-btn ${importSuccess ? "sdp-import-btn-success" : ""}`} onClick={handleImportToChat} disabled={importSuccess}>
                <i className={importSuccess ? "ri-checkbox-circle-line" : "ri-chat-upload-line"}></i>
                {importSuccess ? "Importing..." : "Import into chat for analysis"}
              </button>
            </div>
          </div>
          <div className="sdp-tabbar">
            <div className="sdp-tab-group">
              <button className={`sdp-tab ${activeTab === "overview" ? "active" : ""}`} onClick={() => setActiveTab("overview")}>
                <i className="ri-bar-chart-line"></i>Overview
              </button>
              <button className={`sdp-tab ${activeTab === "responses" ? "active" : ""}`} onClick={() => setActiveTab("responses")}>
                <i className="ri-table-line"></i>Response data
              </button>
            </div>
            <div className="sdp-stat-pill sdp-stat-pill-compact">
              <i className="ri-bar-chart-2-line"></i>
              <span>{responses.length} responses</span>
            </div>
            <div className="sdp-link-card">
              <div className="sdp-code-label">
                <i className="ri-link"></i>Survey link
              </div>
              <div className="sdp-link-row">
                <span className="sdp-link-value" title={surveyLink}>{isShorteningLink ? "Creating short link..." : surveyLink}</span>
                <button className="sdp-copy-code-btn sdp-copy-link-btn" onClick={handleCopySurveyLink} disabled={isShorteningLink || !surveyLink} type="button">
                  <i className={isShorteningLink ? "ri-loader-4-line" : copyLinkSuccess ? "ri-checkbox-circle-line" : "ri-file-copy-line"}></i>
                  {isShorteningLink ? "Generating" : copyLinkSuccess ? "Copied" : "Copy link"}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="sdp-content">
          {activeTab === "overview" && (
            <div className="sdp-overview">
              <section className="sdp-section">
                <div className="sdp-section-header">
                  <div className="sdp-section-icon"><i className="ri-star-line"></i></div>
                  <div>
                    <h2 className="sdp-section-title">Rating summary</h2>
                    <p className="sdp-section-sub">{ratingQuestions.length}  rating questions</p>
                  </div>
                </div>
                <div className="sdp-rating-grid">
                  {ratingQuestions.map((question) => (
                    <RatingStats
                      key={question.id || question.question_id}
                      question={question}
                      responses={responses}
                      qNum={questions.indexOf(question) + 1}
                    />
                  ))}
                </div>
              </section>

              <section className="sdp-section">
                <div className="sdp-section-header">
                  <div className="sdp-section-icon sdp-section-icon-cyan"><i className="ri-file-text-line"></i></div>
                  <div>
                    <h2 className="sdp-section-title">Text and choice response summary</h2>
                    <p className="sdp-section-sub">{textQuestions.length}  non-rating questions</p>
                  </div>
                </div>
                <div className="sdp-text-q-list">
                  {textQuestions.map((question) => {
                    const qId = question.id !== undefined ? question.id : question.question_id;
                    const answers = responses.map((response) => response.answers ? response.answers[qId] : undefined).filter(Boolean);
                    return (
                      <div className="sdp-text-q-card" key={question.id || question.question_id}>
                        <div className="sdp-text-q-header">
                          <span className="sdp-q-badge sdp-q-badge-cyan">Q{questions.indexOf(question) + 1}</span>
                          <span className="sdp-text-q-title">{question.title || question.question_title}</span>
                          <span className="sdp-text-q-count">{answers.length} responses</span>
                        </div>
                        <div className="sdp-text-q-answers">
                          {answers.slice(0, 4).map((answer, index) => (
                            <div key={index} className="sdp-text-q-answer">
                              <div className="sdp-answer-dot"></div>
                              <span>{displayAnswer(answer)}</span>
                            </div>
                          ))}
                          {answers.length > 4 && <button className="sdp-see-more" onClick={() => setActiveTab("responses")}>View all  {answers.length} responses</button>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>
          )}

          {activeTab === "responses" && (
            <div className="sdp-responses">
              <div className="sdp-table-section">
                <div className="sdp-table-section-header">
                  <span className="sdp-table-count">Total:  {responses.length} responses</span>
                  <span className="sdp-table-hint">Scroll horizontally to view all questions</span>
                </div>
                <ResponseTable questions={questions} responses={responses} />
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}