import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../../components/feature/Navbar";

const TYPE_LABELS = {
  rating: "評分",
  short: "短答",
  long: "詳答",
  single: "單選",
  multiple: "複選",
};

function displayAnswer(value) {
  if (Array.isArray(value)) return value.join("、");
  return value || "未填";
}

function toDateTimeLocalValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 16);
}

function formatDeadline(value) {
  if (!value) return "未設定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-TW", {
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

  responses.forEach((response) => {
    const value = Number(response.answers[question.id]);
    if (Number.isFinite(value) && value >= 0 && value <= 5) {
      counts[value] += 1;
      total += value;
      answered += 1;
    }
  });

  const avg = answered ? (total / answered).toFixed(1) : "-";
  const max = Math.max(...Object.values(counts), 1);
  const colors = ["#fca5a5", "#fdba74", "#fde047", "#86efac", "#6ee7b7", "#5eead4"];

  return (
    <div className="sdp-rating-card">
      <div className="sdp-rating-card-header">
        <span className="sdp-q-badge">Q{qNum}</span>
        <span className="sdp-rating-card-title">{question.title}</span>
      </div>
      <div className="sdp-rating-stats">
        <div className="sdp-avg-block">
          <div className="sdp-avg-circle">
            <span className="sdp-avg-num">{avg}</span>
            <span className="sdp-avg-sub">/ 5</span>
          </div>
          <div className="sdp-avg-info">
            <div className="sdp-avg-label">平均分數</div>
            <div className="sdp-avg-count">{answered} 份回答</div>
          </div>
        </div>
        <div className="sdp-bars">
          {[0, 1, 2, 3, 4, 5].map((score) => (
            <div key={score} className="sdp-bar-row">
              <div className="sdp-bar-score">{score}</div>
              <div className="sdp-bar-track">
                <div className="sdp-bar-fill" style={{ width: `${(counts[score] / max) * 100}%`, background: colors[score] }} />
              </div>
              <div className="sdp-bar-count">{counts[score]}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ResponseTable({ questions, responses }) {
  return (
    <div className="sdp-table-wrapper">
      <div className="sdp-table-scroll">
        <table className="sdp-table">
          <thead>
            <tr>
              <th className="sdp-th sdp-th-idx">#</th>
              <th className="sdp-th sdp-th-identity">填答人</th>
              <th className="sdp-th sdp-th-time">提交時間</th>
              {questions.map((question, index) => (
                <th key={question.id} className="sdp-th sdp-th-q">
                  <div className="sdp-th-q-num">Q{index + 1}</div>
                  <div className="sdp-th-q-title">{question.title}</div>
                  <div className="sdp-th-q-type">{TYPE_LABELS[question.type] || question.type}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {responses.map((response, index) => (
              <tr key={response.respondentId || index} className={index % 2 === 0 ? "sdp-tr-even" : "sdp-tr-odd"}>
                <td className="sdp-td sdp-td-idx">{index + 1}</td>
                <td className="sdp-td sdp-td-identity">{response.respondentIdentity || "匿名"}</td>
                <td className="sdp-td sdp-td-time">{response.submittedAt}</td>
                {questions.map((question) => (
                  <td key={question.id} className="sdp-td sdp-td-ans">{displayAnswer(response.answers[question.id])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function buildSurveyChatContent(survey) {
  const lines = [
    `問卷：${survey.title}`,
    `邀請碼：${survey.code}`,
    `建立日期：${survey.createdAt}`,
    `回覆數：${survey.responses.length}`,
    "",
    "請協助我分析這份問卷的回答趨勢、可能洞察與後續建議。",
  ];
  survey.questions.forEach((question, index) => {
    lines.push(`Q${index + 1}. ${question.title}`);
    survey.responses.slice(0, 8).forEach((response, responseIndex) => {
      const identityLabel = response.respondentIdentity ? `填答人：${response.respondentIdentity}，` : "";
      lines.push(`  ${responseIndex + 1}. ${identityLabel}${displayAnswer(response.answers[question.id])}`);
    });
  });
  return lines.join("\n");
}

export default function SurveyDetailPage({ survey, onBack, onUpdateDeadline }) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("overview");
  const [importSuccess, setImportSuccess] = useState(false);
  const [copyCodeSuccess, setCopyCodeSuccess] = useState(false);
  const [deadlineValue, setDeadlineValue] = useState(toDateTimeLocalValue(survey.deadlineAt));
  const [deadlineStatus, setDeadlineStatus] = useState("");
  const [isSavingDeadline, setIsSavingDeadline] = useState(false);
  const ratingQuestions = survey.questions.filter((question) => question.type === "rating");
  const textQuestions = survey.questions.filter((question) => question.type !== "rating");

  useEffect(() => {
    setDeadlineValue(toDateTimeLocalValue(survey.deadlineAt));
    setDeadlineStatus("");
  }, [survey.deadlineAt]);

  const handleCopyCode = async () => {
    try {
      await navigator.clipboard.writeText(survey.code);
      setCopyCodeSuccess(true);
      setTimeout(() => setCopyCodeSuccess(false), 1600);
    } catch {
      setCopyCodeSuccess(false);
      alert("複製失敗，請手動複製邀請碼");
    }
  };

  const handleImportToChat = () => {
    setImportSuccess(true);
    setTimeout(() => {
      navigate("/workspace", {
        state: {
          surveyImport: {
            sessionTitle: `問卷分析：${survey.title}`,
            message: buildSurveyChatContent(survey),
          },
        },
      });
    }, 450);
  };

  const handleSaveDeadline = async () => {
    if (!deadlineValue) {
      setDeadlineStatus("請選擇截止日期與時間。");
      return;
    }
    setIsSavingDeadline(true);
    setDeadlineStatus("");
    try {
      await onUpdateDeadline?.(survey, deadlineValue);
      setDeadlineStatus("截止時間已更新。");
    } catch (error) {
      setDeadlineStatus(error.message || "截止時間更新失敗。");
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
              <i className="ri-arrow-left-line"></i>返回問卷
            </button>
            <div className="sdp-topbar-center">
              <h1 className="sdp-topbar-title">{survey.title}</h1>
              <div className="sdp-topbar-meta">
                <span><i className="ri-calendar-line"></i>{survey.createdAt}</span>
                <span><i className="ri-time-line"></i>截止 {formatDeadline(survey.deadlineAt)}</span>
                <span><i className="ri-user-line"></i>{survey.responses.length} 份回覆</span>
                <span><i className="ri-question-line"></i>{survey.questions.length} 題</span>
              </div>
            </div>
            <div className="sdp-topbar-right">
              <div className="sdp-deadline-card">
                <label className="sdp-code-label" htmlFor="survey-deadline-input">
                  <i className="ri-time-line"></i>截止時間
                </label>
                <div className="sdp-deadline-row">
                  <input
                    id="survey-deadline-input"
                    className="sdp-deadline-input"
                    type="datetime-local"
                    value={deadlineValue}
                    onChange={(event) => setDeadlineValue(event.target.value)}
                  />
                  <button className="sdp-deadline-save-btn" onClick={handleSaveDeadline} disabled={isSavingDeadline} type="button">
                    <i className={isSavingDeadline ? "ri-loader-4-line" : "ri-save-line"}></i>
                    {isSavingDeadline ? "儲存中" : "儲存"}
                  </button>
                </div>
                {deadlineStatus && <div className="sdp-deadline-status">{deadlineStatus}</div>}
              </div>
              <div className="sdp-code-card">
                <div className="sdp-code-label">
                  <i className="ri-key-2-line"></i>邀請碼
                </div>
                <div className="sdp-code-row">
                  <span className="sdp-code-value">{survey.code}</span>
                  <button className="sdp-copy-code-btn" onClick={handleCopyCode} type="button">
                    <i className={copyCodeSuccess ? "ri-checkbox-circle-line" : "ri-file-copy-line"}></i>
                    {copyCodeSuccess ? "已複製" : "複製 Code"}
                  </button>
                </div>
              </div>
              <div className="sdp-stat-pill">
                <i className="ri-bar-chart-2-line"></i>
                <span>{survey.responses.length} responses</span>
              </div>
              <button className={`sdp-import-btn ${importSuccess ? "sdp-import-btn-success" : ""}`} onClick={handleImportToChat} disabled={importSuccess}>
                <i className={importSuccess ? "ri-checkbox-circle-line" : "ri-chat-upload-line"}></i>
                {importSuccess ? "匯入中..." : "匯入 Chat 分析"}
              </button>
            </div>
          </div>
          <div className="sdp-tabbar">
            <button className={`sdp-tab ${activeTab === "overview" ? "active" : ""}`} onClick={() => setActiveTab("overview")}>
              <i className="ri-bar-chart-line"></i>總覽
            </button>
            <button className={`sdp-tab ${activeTab === "responses" ? "active" : ""}`} onClick={() => setActiveTab("responses")}>
              <i className="ri-table-line"></i>回覆資料
            </button>
          </div>
        </div>

        <div className="sdp-content">
          {activeTab === "overview" && (
            <div className="sdp-overview">
              <section className="sdp-section">
                <div className="sdp-section-header">
                  <div className="sdp-section-icon"><i className="ri-star-line"></i></div>
                  <div>
                    <h2 className="sdp-section-title">評分統計</h2>
                    <p className="sdp-section-sub">{ratingQuestions.length} 題評分題</p>
                  </div>
                </div>
                <div className="sdp-rating-grid">
                  {ratingQuestions.map((question) => (
                    <RatingStats key={question.id} question={question} responses={survey.responses} qNum={survey.questions.indexOf(question) + 1} />
                  ))}
                </div>
              </section>

              <section className="sdp-section">
                <div className="sdp-section-header">
                  <div className="sdp-section-icon sdp-section-icon-cyan"><i className="ri-file-text-line"></i></div>
                  <div>
                    <h2 className="sdp-section-title">文字與選擇題摘要</h2>
                    <p className="sdp-section-sub">{textQuestions.length} 題非評分題</p>
                  </div>
                </div>
                <div className="sdp-text-q-list">
                  {textQuestions.map((question) => {
                    const answers = survey.responses.map((response) => response.answers[question.id]).filter(Boolean);
                    return (
                      <div className="sdp-text-q-card" key={question.id}>
                        <div className="sdp-text-q-header">
                          <span className="sdp-q-badge sdp-q-badge-cyan">Q{survey.questions.indexOf(question) + 1}</span>
                          <span className="sdp-text-q-title">{question.title}</span>
                          <span className="sdp-text-q-count">{answers.length} 筆</span>
                        </div>
                        <div className="sdp-text-q-answers">
                          {answers.slice(0, 4).map((answer, index) => (
                            <div key={index} className="sdp-text-q-answer">
                              <div className="sdp-answer-dot"></div>
                              <span>{displayAnswer(answer)}</span>
                            </div>
                          ))}
                          {answers.length > 4 && <button className="sdp-see-more" onClick={() => setActiveTab("responses")}>查看全部 {answers.length} 筆</button>}
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
                  <span className="sdp-table-count">共 {survey.responses.length} 份回覆</span>
                  <span className="sdp-table-hint">可橫向捲動查看所有題目</span>
                </div>
                <ResponseTable questions={survey.questions} responses={survey.responses} />
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
