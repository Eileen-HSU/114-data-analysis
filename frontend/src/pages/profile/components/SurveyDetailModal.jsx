import { useState } from "react";

function RatingStats({ question, responses }) {
  const counts = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  let total = 0;
  let answered = 0;

  responses.forEach((r) => {
    const val = r.answers[question.id];
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
  const textQuestions = questions.filter((q) => q.type !== "rating");

  if (textQuestions.length === 0) return null;

  return (
    <div className="response-table-wrapper">
      <div className="response-table-scroll">
        <table className="response-table">
          <thead>
            <tr>
              <th className="response-table-th response-table-th-idx">#</th>
              <th className="response-table-th response-table-th-identity">填答人</th>
              <th className="response-table-th response-table-th-time">提交時間</th>
              {textQuestions.map((q) => (
                <th key={q.id} className="response-table-th response-table-th-q">
                  <div className="response-table-q-title">{q.title}</div>
                  <div className="response-table-q-type">
                    {{ short: "簡答", long: "詳答", single: "單選", multiple: "多選", rating: "評分" }[q.type]}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {responses.map((r, idx) => (
              <tr key={r.respondentId || idx} className={idx % 2 === 0 ? "response-table-row-even" : "response-table-row-odd"}>
                <td className="response-table-td response-table-td-idx">{idx + 1}</td>
                <td className="response-table-td response-table-td-identity">{r.respondentIdentity || "匿名"}</td>
                <td className="response-table-td response-table-td-time">{r.submittedAt}</td>
                {textQuestions.map((q) => {
                  const ans = r.answers[q.id];
                  const display = Array.isArray(ans) ? ans.join("、") : (ans || "—");
                  return (
                    <td key={q.id} className="response-table-td response-table-td-ans">
                      {display || "—"}
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

  const ratingQuestions = survey.questions.filter((q) => q.type === "rating");
  const textQuestions = survey.questions.filter((q) => q.type !== "rating");

  return (
    <div className="survey-detail-backdrop" onClick={onClose}>
      <div className="survey-detail-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="survey-detail-header">
          <div>
            <h2 className="survey-detail-title">{survey.title}</h2>
            <div className="survey-detail-meta">
              <span><i className="ri-key-2-line"></i> {survey.code}</span>
              <span><i className="ri-calendar-line"></i> {survey.createdAt}</span>
              <span><i className="ri-user-line"></i> {survey.responses.length} 人回覆</span>
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
              {/* Rating Questions - shown first */}
              {ratingQuestions.length > 0 && (
                <div className="survey-detail-section">
                  <div className="survey-detail-section-title">
                    <i className="ri-star-line"></i>
                    評分題統計
                  </div>
                  <div className="rating-questions-grid">
                    {ratingQuestions.map((q, idx) => (
                      <div key={q.id} className="rating-question-card">
                        <div className="rating-question-label">
                          <span className="rating-q-num">Q{survey.questions.indexOf(q) + 1}</span>
                          {q.title}
                        </div>
                        <RatingStats question={q} responses={survey.responses} />
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
                      const answers = survey.responses
                        .map((r) => r.answers[q.id])
                        .filter((a) => a && (Array.isArray(a) ? a.length > 0 : a !== ""));
                      return (
                        <div key={q.id} className="text-q-summary-card">
                          <div className="text-q-summary-header">
                            <span className="text-q-num">Q{survey.questions.indexOf(q) + 1}</span>
                            <span className="text-q-title">{q.title}</span>
                            <span className="text-q-count">{answers.length} 人回答</span>
                          </div>
                          <div className="text-q-answers-preview">
                            {answers.slice(0, 3).map((ans, i) => (
                              <div key={i} className="text-q-answer-item">
                                <i className="ri-chat-1-line"></i>
                                <span>{Array.isArray(ans) ? ans.join("、") : ans}</span>
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
                  所有回覆（{survey.responses.length} 筆）
                  <span style={{ fontSize: 12, color: "var(--slate-400)", fontWeight: 400, marginLeft: 8 }}>
                    評分題顯示於上方，問答題展開於右側
                  </span>
                </div>

                {/* Rating summary row at top */}
                {ratingQuestions.length > 0 && (
                  <div className="responses-rating-row">
                    {ratingQuestions.map((q) => {
                      let total = 0; let cnt = 0;
                      survey.responses.forEach((r) => {
                        const v = Number(r.answers[q.id]);
                        if (!isNaN(v) && r.answers[q.id] !== "") { total += v; cnt++; }
                      });
                      const avg = cnt > 0 ? (total / cnt).toFixed(1) : "—";
                      return (
                        <div key={q.id} className="responses-rating-chip">
                          <span className="responses-rating-chip-q">Q{survey.questions.indexOf(q) + 1}</span>
                          <span className="responses-rating-chip-title">{q.title}</span>
                          <span className="responses-rating-chip-avg">平均 {avg} 分</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                <ResponseTable questions={survey.questions} responses={survey.responses} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
