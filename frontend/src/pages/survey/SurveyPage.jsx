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
        <div className="survey-shell">
          <section className="survey-dashboard-head">
            <div>
              <div className="survey-eyebrow">
                <i className="ri-survey-line"></i>
                問卷調查
              </div>
              <h1 className="survey-page-title">建立問卷與收集回覆</h1>
              <p className="survey-page-subtitle">
                建立評分或文字題，分享邀請碼給填答者，回收後可直接進入分析。
              </p>
            </div>
            <a className="survey-primary-action" href="/survey/create">
              <i className="ri-add-line"></i>
              建立問卷
            </a>
          </section>

          <section className="survey-action-grid" aria-label="問卷功能">
            <a className="survey-action-card survey-action-create" href="/survey/create">
              <div className="survey-action-icon">
                <i className="ri-edit-box-line"></i>
              </div>
              <div className="survey-action-copy">
                <span className="survey-action-kicker">建立與分享</span>
                <h2>建立問卷</h2>
                <p>新增題目、設定截止時間，產生可分享的邀請碼。</p>
              </div>
              <span className="survey-action-arrow"><i className="ri-arrow-right-line"></i></span>
            </a>

            <a className="survey-action-card survey-action-fill" href="/survey/fill">
              <div className="survey-action-icon">
                <i className="ri-file-list-3-line"></i>
              </div>
              <div className="survey-action-copy">
                <span className="survey-action-kicker">填答入口</span>
                <h2>填寫問卷</h2>
                <p>輸入邀請碼開啟問卷，快速提交回覆內容。</p>
              </div>
              <span className="survey-action-arrow"><i className="ri-arrow-right-line"></i></span>
            </a>
          </section>

          <section className="survey-recent-panel">
            <div className="survey-section-heading">
              <div>
                <h2>最近問卷</h2>
                <p>快速回到已建立的問卷，查看邀請碼與回覆狀態。</p>
              </div>
              <a href="/profile" className="survey-secondary-link">
                我的問卷
                <i className="ri-arrow-right-line"></i>
              </a>
            </div>

            {recentSurveys.length > 0 ? (
              <div className="survey-recent-list">
                {recentSurveys.map((survey) => (
                  <a key={survey.code} className="survey-recent-item" href="/profile">
                    <div className="survey-recent-icon">
                      <i className="ri-file-chart-line"></i>
                    </div>
                    <div className="survey-recent-main">
                      <strong>{survey.title}</strong>
                      <span>邀請碼 {survey.code} · {survey.responses?.length || 0} 份回覆</span>
                    </div>
                    <span className="survey-recent-date">{survey.createdAt || "未記錄日期"}</span>
                  </a>
                ))}
              </div>
            ) : (
              <div className="survey-empty-state">
                <div className="survey-empty-icon"><i className="ri-inbox-line"></i></div>
                <div>
                  <strong>目前還沒有問卷</strong>
                  <span>建立第一份問卷後，這裡會顯示最近項目。</span>
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
    </>
  );
}
