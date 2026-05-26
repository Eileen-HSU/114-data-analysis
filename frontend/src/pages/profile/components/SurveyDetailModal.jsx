import { useState } from "react";

function RatingStats({ question, responses }) {
  const counts = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  let total = 0;
  let answered = 0;

  if (!question) return null;
  const safeResponses = Array.isArray(responses) ? responses : [];

  safeResponses.forEach((r) => {
    if (!r || !r.answers) return;
    const qId = question.id !== undefined ? question.id : question.question_id;
    const val = r.answers[qId];
    if (val !== undefined && val !== "") {
      const num = Number(val);
      if (!isNaN(num) && num >= 0 && num <= 5) {
        counts[num] = (counts[num] || 0) + 1;
        total += num;
        answered += 1;
      }
    }
  });

  const avg = answered > 0 ? (total / answered).toFixed(1) : "—";
  const maxCount = Math.max(...Object.values(counts), 1);

  const scoreColors = [
    { bar: "#fca5a5", bg: "#fff1f2", text: "#dc2626" },
    { bar: "#fdba74", bg: "#fff7ed", text: "#ea580c" },
    { bar: "#fde047", bg: "#fefce8", text: "#ca8a04" },
    { bar: "#86efac", bg: "#f0fdf4", text: "#16a34a" },
    { bar: "#6ee7b7", bg: "#ecfdf5", text: "#059669" },
    { bar: "#5eead4", bg: "#f0fdfa", text: "#0d9488" },
  ];

  return (
    <div className="rating-stats-block">
      <div className="rating-stats-header">
        <div className="rating-avg-badge">
          <span className="rating-avg-num">{avg}</span>
          <span className="rating-avg-label">平均分</span>
        </div>
        <div className="rating-answered-info">
          <i className="ri-user-line"></i>
          <span>{answered} 人作答</span>
        </div>
      </div>
      <div className="rating-bars">
        {[0, 1, 2, 3, 4, 5].map((score) => {
          const c = counts[score] || 0;
          const pct = maxCount > 0 ? (c / maxCount) * 100 : 0;
          const col = scoreColors[score];
          return (
            <div key={score} className="rating-bar-row">
              <div
                className="rating-score-label"
                style={{ background: col.bg, color: col.text }}
              >
                {score}
              </div>
              <div className="rating-bar-track">
                <div
                  className="rating-bar-fill"
                  style={{ width: `${pct}%`, background: col.bar }}
                />
              </div>
              <div className="rating-bar-count">{c} 人</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ResponseTable({ questions, responses }) {
  const safeQuestions = Array.isArray(questions) ? questions : [];
  const safeResponses = Array.isArray(responses) ? responses : [];

  if (safeQuestions.length === 0) return null;

  return (
    <div className="response-table-wrapper">
      <div className="response-table-scroll">
        <table className="response-table">
          <thead>
            <tr>
              <th className="response-table-th response-table-th-idx">#</th>
              <th className="response-table-th response-table-th-identity">填答人</th>
              <th className="response-table-th response-table-th-time">提交時間</th>
              {safeQuestions.map((q, i) => (
                <th key={q.id || q.question_id || i} className="response-table-th response-table-th-q">
                  <div className="response-table-q-title">{q.title || q.question_title || "未命名題目"}</div>
                  <div className="response-table-q-type">
                    {{ short: "簡答", long: "詳答", single: "單選", multiple: "多選", rating: "評分" }[q.type || q.question_type] || "問答"}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {safeResponses.map((r, idx) => (
              <tr key={r.respondentId || r.respondent_id || idx} className={idx % 2 === 0 ? "response-table-row-even" : "response-table-row-odd"}>
                <td className="response-table-td response-table-td-idx">{idx + 1}</td>
                <td className="response-table-td response-table-td-identity">
                  {r.respondentIdentity || r.respondent_identity || r.username || "匿名"}
                </td>
                <td className="response-table-td response-table-td-time">{r.submittedAt || r.submitted_at || "—"}</td>
                {safeQuestions.map((q, i) => {
                  const qId = q.id !== undefined ? q.id : q.question_id;
                  const ans = r.answers ? r.answers[qId] : undefined;
                  const display = Array.isArray(ans) ? ans.join("、") : (ans !== undefined && ans !== "" ? String(ans) : "—");
                  return (
                    <td key={q.id || q.question_id || i} className="response-table-td response-table-td-ans">
                      {display}
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

export default function SurveyDetailModal({ survey, onClose }) {
  const [activeTab, setActiveTab] = useState("overview");

  // 如果物件根本還沒進來，先回傳 null 阻斷，避免網頁崩潰變空白
  if (!survey) return null;

  const questions = Array.isArray(survey.questions) ? survey.questions : [];
  const responses = Array.isArray(survey.responses) ? survey.responses : [];

  const ratingQuestions = questions.filter((q) => (q.type || q.question_type) === "rating");
  const textQuestions = questions.filter((q) => (q.type || q.question_type) !== "rating");

  return (
    <div className="survey-detail-backdrop" onClick={onClose}>
      <div className="survey-detail-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="survey-detail-header">
          <div>
            <h2 className="survey-detail-title">{survey.title || survey.survey_name || "未命名問卷"}</h2>
            <div className="survey-detail-meta">
              <span><i className="ri-key-2-line"></i> {survey.code}</span>
              <span><i className="ri-calendar-line"></i> {survey.createdAt || survey.created_at || "—"}</span>
              <span><i className="ri-user-line"></i> {responses.length} 人回覆</span>
            </div>
          </div>
          <button className="survey-detail-close" onClick={onClose}>
            <i className="ri-close-line"></i>
          </button>
        </div>

        {/* Tabs */}
        <div className="survey-detail-tabs">
          <button
            className={`survey-detail-tab ${activeTab === "overview" ? "active" : ""}`}
            onClick={() => setActiveTab("overview")}
          >
            <i className="ri-bar-chart-line"></i>
            統計總覽
          </button>
          <button
            className={`survey-detail-tab ${activeTab === "responses" ? "active" : ""}`}
            onClick={() => setActiveTab("responses")}
          >
            <i className="ri-table-line"></i>
            回覆明細
          </button>
        </div>

        {/* Content */}
        <div className="survey-detail-body">
          {activeTab === "overview" && (
            <div>
              {/* Rating Questions */}
              {ratingQuestions.length > 0 && (
                <div className="survey-detail-section">
                  <div className="survey-detail-section-title">
                    <i className="ri-star-line"></i>
                    評分題統計
                  </div>
                  <div className="rating-questions-grid">
                    {ratingQuestions.map((q) => (
                      <div key={q.id || q.question_id} className="rating-question-card">
                        <div className="rating-question-label">
                          <span className="rating-q-num">Q{questions.indexOf(q) + 1}</span>
                          {q.title || q.question_title}
                        </div>
                        <RatingStats question={q} responses={responses} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Text Questions Summary */}
              {textQuestions.length > 0 && (
                <div className="survey-detail-section">
                  <div className="survey-detail-section-title">
                    <i className="ri-file-text-line"></i>
                    問答題摘要
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    {textQuestions.map((q) => {
                      const qId = q.id !== undefined ? q.id : q.question_id;
                      const answers = responses
                        .map((r) => r.answers ? r.answers[qId] : undefined)
                        .filter((a) => a && (Array.isArray(a) ? a.length > 0 : a !== ""));
                      return (
                        <div key={q.id || q.question_id} className="text-q-summary-card">
                          <div className="text-q-summary-header">
                            <span className="text-q-num">Q{questions.indexOf(q) + 1}</span>
                            <span className="text-q-title">{q.title || q.question_title}</span>
                            <span className="text-q-count">{answers.length} 人回答</span>
                          </div>
                          <div className="text-q-answers-preview">
                            {answers.slice(0, 3).map((ans, i) => (
                              <div key={i} className="text-q-answer-item">
                                <i className="ri-chat-1-line"></i>
                                <span>{Array.isArray(ans) ? ans.join("、") : String(ans)}</span>
                              </div>
                            ))}
                            {answers.length > 3 && (
                              <div
                                className="text-q-more"
                                onClick={() => setActiveTab("responses")}
                              >
                                還有 {answers.length - 3} 筆回答，點此查看全部 →
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === "responses" && (
            <div>
              <div className="survey-detail-section">
                <div className="survey-detail-section-title">
                  <i className="ri-table-line"></i>
                  所有回覆（{responses.length} 筆）
                </div>

                {ratingQuestions.length > 0 && (
                  <div className="responses-rating-row">
                    {ratingQuestions.map((q) => {
                      let total = 0; let cnt = 0;
                      responses.forEach((r) => {
                        if (!r.answers) return;
                        const qId = q.id !== undefined ? q.id : q.question_id;
                        const v = Number(r.answers[qId]);
                        if (!isNaN(v) && r.answers[qId] !== "") { total += v; cnt++; }
                      });
                      const avg = cnt > 0 ? (total / cnt).toFixed(1) : "—";
                      return (
                        <div key={q.id || q.question_id} className="responses-rating-chip">
                          <span className="responses-rating-chip-q">Q{questions.indexOf(q) + 1}</span>
                          <span className="responses-rating-chip-title">{q.title || q.question_title}</span>
                          <span className="responses-rating-chip-avg">平均 {avg} 分</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                <ResponseTable questions={questions} responses={responses} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}