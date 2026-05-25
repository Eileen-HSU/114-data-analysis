import { useMemo } from "react";
import Navbar from "../../components/feature/Navbar";
import "./survey.css";

function getRecentSurveys() {
  try {
    const stored = JSON.parse(localStorage.getItem("surveys") || "{}");
    return Object.values(stored || {})
      .filter((survey) => survey?.title && survey?.code)
      .sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")))
      .slice(0, 3);
  } catch {
    return [];
  }
}

export default function SurveyPage() {
  const recentSurveys = useMemo(() => getRecentSurveys(), []);

  return (
    <>
      <Navbar />
      <main className="survey-page">
        <section className="survey-workspace">
          <div className="survey-intro">
            <div className="survey-hero-badge">
              <i className="ri-survey-line"></i>
              <span>問卷調查</span>
            </div>
            <h1 className="survey-hero-title">建立問卷與收集回覆</h1>
            <p className="survey-hero-subtitle">
              建立評分或文字題，分享邀請碼給填答者，回收後可直接進入分析。
            </p>
          </div>

          <div className="survey-board">
            <a className="survey-entry-card create" href="/survey/create">
              <div className="entry-card-topline">
                <div className="entry-card-icon create-icon">
                  <i className="ri-edit-box-line"></i>
                </div>
                <span className="entry-card-kicker">主要功能</span>
              </div>
              <div className="entry-card-copy">
                <h2 className="entry-card-title">建立問卷</h2>
                <p className="entry-card-desc">
                  新增題目、設定截止時間，產生可分享的邀請碼，適合整理作品集訪談、產品回饋或課堂調查。
                </p>
              </div>
              <div className="entry-card-footer">
                <span className="entry-card-action">
                  開始建立
                  <i className="ri-arrow-right-line"></i>
                </span>
                <span className="entry-card-note">評分題 · 文字題 · 邀請碼</span>
              </div>
            </a>

            <aside className="survey-side-stack">
              <a className="survey-entry-card fill" href="/survey/fill">
                <div className="entry-card-icon fill-icon">
                  <i className="ri-file-list-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">填答入口</span>
                  <h2 className="entry-card-title">填寫問卷</h2>
                  <p className="entry-card-desc">輸入邀請碼開啟問卷，快速提交回覆內容。</p>
                </div>
                <span className="entry-card-arrow"><i className="ri-arrow-right-line"></i></span>
              </a>

              <section className="survey-activity-card">
                <div className="survey-activity-head">
                  <div>
                    <span className="entry-card-kicker">最近活動</span>
                    <h2>問卷動態</h2>
                  </div>
                  <a href="/profile" className="survey-profile-link">查看作品集</a>
                </div>

                {recentSurveys.length > 0 ? (
                  <div className="survey-activity-list">
                    {recentSurveys.map((survey) => (
                      <a className="survey-activity-item" href="/profile" key={survey.code}>
                        <span className="survey-activity-dot"></span>
                        <div>
                          <strong>{survey.title}</strong>
                          <span>{survey.responses?.length || 0} 份回覆 · {survey.code}</span>
                        </div>
                      </a>
                    ))}
                  </div>
                ) : (
                  <div className="survey-activity-empty">
                    <i className="ri-time-line"></i>
                    <span>建立問卷後，這裡會顯示最近的回覆與問卷狀態。</span>
                  </div>
                )}
              </section>
            </aside>
          </div>
        </section>
      </main>
    </>
  );
}
