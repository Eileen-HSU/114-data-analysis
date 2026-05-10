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
              <span>問卷中心</span>
            </div>
            <h1 className="survey-hero-title">
              建立問卷，收集回覆
              <br />
              <span>用邀請碼快速分享</span>
            </h1>
            <p className="survey-hero-subtitle">
              建立簡單的評分與文字題，產生邀請碼後即可讓填答者輸入代碼作答。
            </p>

            <div className="survey-entry-cards">
              <a className="survey-entry-card create" href="/survey/create">
                <div className="entry-card-arrow">
                  <i className="ri-arrow-right-up-line"></i>
                </div>
                <div className="entry-card-icon create-icon">
                  <i className="ri-edit-box-line"></i>
                </div>
                <h2 className="entry-card-title">建立問卷</h2>
                <p className="entry-card-desc">新增題目、設定必填，並產生一組可分享的邀請碼。</p>
                <span className="entry-card-btn create-btn">
                  <i className="ri-add-circle-line"></i>
                  開始建立
                </span>
              </a>

              <a className="survey-entry-card fill" href="/survey/fill">
                <div className="entry-card-arrow">
                  <i className="ri-arrow-right-up-line"></i>
                </div>
                <div className="entry-card-icon fill-icon">
                  <i className="ri-file-list-3-line"></i>
                </div>
                <h2 className="entry-card-title">填寫問卷</h2>
                <p className="entry-card-desc">輸入邀請碼，快速開啟問卷並送出回覆。</p>
                <span className="entry-card-btn fill-btn">
                  <i className="ri-pencil-line"></i>
                  前往填答
                </span>
              </a>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
