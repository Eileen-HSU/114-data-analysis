import Navbar from "../../components/feature/Navbar";
import "./survey.css";

export default function SurveyPage() {
  return (
    <>
      <Navbar />
      <main className="survey-page">
        <section className="survey-hero">
          <div className="container">
            <div className="survey-hero-badge">
              <i className="ri-survey-line"></i>
              <span>問卷調查</span>
            </div>
            <h1 className="survey-hero-title">
              建立問卷與收集回覆
            </h1>
            <p className="survey-hero-subtitle">
              建立評分或文字題，分享邀請碼給填答者，回收後可直接進入分析。
            </p>

            <div className="survey-entry-cards">
              <a className="survey-entry-card create" href="/survey/create">
                <div className="entry-card-arrow">
                  <i className="ri-arrow-right-line"></i>
                </div>
                <div className="entry-card-icon create-icon">
                  <i className="ri-edit-box-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">建立與分享</span>
                  <h2 className="entry-card-title">建立問卷</h2>
                  <p className="entry-card-desc">新增題目、設定截止時間，產生可分享的邀請碼。</p>
                </div>
              </a>

              <a className="survey-entry-card fill" href="/survey/fill">
                <div className="entry-card-arrow">
                  <i className="ri-arrow-right-line"></i>
                </div>
                <div className="entry-card-icon fill-icon">
                  <i className="ri-file-list-3-line"></i>
                </div>
                <div className="entry-card-copy">
                  <span className="entry-card-kicker">填答入口</span>
                  <h2 className="entry-card-title">填寫問卷</h2>
                  <p className="entry-card-desc">輸入邀請碼開啟問卷，快速提交回覆內容。</p>
                </div>
              </a>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
