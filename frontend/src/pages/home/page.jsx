import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import { useAuth } from "../../hooks/AuthContext";
import "./home.css";

export default function HomePage() {
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const heroBgRef = useRef(null);

  useEffect(() => {
    if (isLoggedIn) {
      navigate("/workspace", { replace: true });
    }
  }, [isLoggedIn, navigate]);

  useEffect(() => {
    const onScroll = () => {
      if (heroBgRef.current) {
        heroBgRef.current.style.transform = `translateY(${window.scrollY * 0.42}px)`;
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      <Navbar transparent />

      {/* ── Hero Section ── */}
      <section className="hero-section">
        <div className="hero-bg" ref={heroBgRef}></div>
        <div className="hero-overlay"></div>

        <div className="hero-content">
          <div className="badge-pill mb-4">
            <span className="pulse-dot"></span>
            <span>AI 輔助的培訓回饋分析平台</span>
          </div>
          <h1 className="hero-title">
            將培訓回饋整理為<br />
            <span className="highlight">標準化分析結果</span>
          </h1>
          <p className="hero-subtitle">
            整合問卷蒐集、專案管理與 AI 分析助理，協助顧問快速整理文字回饋、查看分類結果，提升課後回饋分析效率。
          </p>
          <div className="hero-buttons">
            <button className="btn btn-hero-primary" onClick={() => navigate("/signup")}>
              <i className="ri-rocket-line me-2"></i>立即開始使用
            </button>
            <button className="btn btn-hero-secondary" onClick={() => navigate("/login")}>
              <i className="ri-login-box-line me-2"></i>登入帳號
            </button>
          </div>
          <div className="hero-tags">
            <span className="hero-tag"><i className="ri-clipboard-line me-1"></i>問卷管理</span>
            <span className="hero-tag"><i className="ri-brain-line me-1"></i>AI 輔助分析</span>
            <span className="hero-tag"><i className="ri-folder-chart-line me-1"></i>專案管理</span>
            <span className="hero-tag"><i className="ri-table-line me-1"></i>表格式結果呈現</span>
          </div>
        </div>

        <div className="scroll-hint">
          <span>向下滾動探索</span>
          <i className="ri-arrow-down-line"></i>
        </div>
      </section>

      {/* ── Features Section ── */}
      <section className="features-section">
        <div className="container">
          <div className="text-center mb-5">
            <div className="section-badge mb-3"><span>功能特色</span></div>
            <h2 className="section-title">培訓回饋整理所需的核心功能</h2>
            <p className="section-subtitle">
              從問卷建立、回饋蒐集到 AI 輔助分析，系統協助顧問快速整理文字回饋，產生清楚的分類結果與分析紀錄。
            </p>
          </div>
          <div className="row g-4">
            {[
              { icon: "ri-upload-cloud-2-line", iconBg: "bg-lavender-50", iconColor: "text-lavender", tag: "資料匯入", tagClass: "tag-lavender", title: "資料上傳與匯入", desc: "支援上傳問卷資料或文字檔案，讓使用者可將外部回饋資料匯入系統進行分析。" },
              { icon: "ri-brain-line", iconBg: "bg-mauve-50", iconColor: "text-mauve", tag: "AI 輔助", tagClass: "tag-mauve", title: "AI 輔助分析", desc: "結合 TF-IDF 與 Gemini API，協助整理文字回饋內容，產生分類結果與分析紀錄。" },
              { icon: "ri-folder-chart-line", iconBg: "bg-periwinkle-50", iconColor: "text-periwinkle", tag: "專案保存", tagClass: "tag-periwinkle", title: "專案管理", desc: "將不同培訓專案的問卷資料、分析結果與歷史紀錄集中保存，方便後續查詢與追蹤。" },
              { icon: "ri-history-line", iconBg: "bg-lavender-50", iconColor: "text-lavender", tag: "歷程追蹤", tagClass: "tag-lavender", title: "歷史紀錄保存", desc: "系統可保存過去的分析專案與操作紀錄，方便使用者回顧、查詢與延續分析流程。" },
              { icon: "ri-table-line", iconBg: "bg-mauve-50", iconColor: "text-mauve", tag: "結果呈現", tagClass: "tag-mauve", title: "表格式結果呈現", desc: "分析結果以表格式呈現，方便使用者查看分類結果、回饋重點與分析紀錄。" },
              { icon: "ri-survey-line", iconBg: "bg-periwinkle-50", iconColor: "text-periwinkle", tag: "問卷蒐集", tagClass: "tag-periwinkle", title: "問卷建立與回饋蒐集", desc: "支援建立問卷、蒐集填答內容，並可將回饋資料提供給 AI 分析助理進行整理。" },
            ].map((f, i) => (
              <div className="col-md-6 col-lg-4" key={i}>
                <div className="feature-card">
                  <div className="d-flex justify-content-between align-items-start mb-4">
                    <div className={`feature-icon ${f.iconBg}`}>
                      <i className={`${f.icon} ${f.iconColor}`}></i>
                    </div>
                    <span className={`feature-tag ${f.tagClass}`}>{f.tag}</span>
                  </div>
                  <h3 className="feature-title">{f.title}</h3>
                  <p className="feature-desc">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How It Works Section ── */}
      <section className="how-section">
        <div className="container">
          <div className="text-center mb-5">
            <div className="section-badge mb-3"><span>使用流程</span></div>
            <h2 className="section-title">如何使用</h2>
            <p className="section-subtitle">只需四個簡單步驟，從原始資料到可行的洞察。</p>
          </div>
          <div className="row g-4">
            {[
              { num: "1", numBg: "bg-lavender-100", numColor: "text-lavender", iconBg: "bg-lavender-50", icon: "ri-user-add-line", iconColor: "text-lavender", title: "建立帳號", desc: "幾秒鐘內完成註冊，馬上開始使用。" },
              { num: "2", numBg: "bg-mauve-100", numColor: "text-mauve", iconBg: "bg-mauve-50", icon: "ri-upload-2-line", iconColor: "text-mauve", title: "上傳您的資料", desc: "將檔案拖放到工作區。支援 CSV、Excel、JSON 和純文字格式。" },
              { num: "3", numBg: "bg-periwinkle-100", numColor: "text-periwinkle", iconBg: "bg-periwinkle-50", icon: "ri-chat-3-line", iconColor: "text-periwinkle", title: "提出您的問題", desc: "用自然語言輸入分析問題。AI 將處理並回應詳細的洞察結果。" },
              { num: "4", numBg: "bg-lavender-100", numColor: "text-lavender", iconBg: "bg-lavender-50", icon: "ri-save-line", iconColor: "text-lavender", title: "儲存與整理", desc: "將分析儲存到專案管理。建立資料夾，按專案整理您的工作。" },
            ].map((s, i) => (
              <div className="col-md-6 col-lg-3" key={i}>
                <div className="step-card">
                  <div className={`step-number ${s.numBg} ${s.numColor}`}>{s.num}</div>
                  <div className={`step-icon ${s.iconBg}`}>
                    <i className={`${s.icon} ${s.iconColor}`}></i>
                  </div>
                  <h3 className="step-title">{s.title}</h3>
                  <p className="step-desc">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>


      {/* ── CTA Section ── */}
      <section className="cta-section">
        <div className="cta-glow cta-glow-1"></div>
        <div className="cta-glow cta-glow-2"></div>
        <div className="cta-glow cta-glow-3"></div>
        <div className="container position-relative">
          <div className="text-center">
            <div className="cta-icon">
              <i className="ri-bar-chart-box-line"></i>
            </div>
            <h2 className="cta-title">準備好開始了嗎？</h2>
            <p className="cta-subtitle">
              立即建立帳號，體驗 AI 驅動的智能資料分析與問卷管理，讓每一筆資料都發揮最大價值。
            </p>
            <div className="cta-buttons">
              <button className="btn btn-cta-primary" onClick={() => navigate("/signup")}>
                <i className="ri-rocket-line me-2"></i>立即開始使用
              </button>
              <button className="btn btn-cta-secondary" onClick={() => navigate("/login")}>
                已有帳號？登入
              </button>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
