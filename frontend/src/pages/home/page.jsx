import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import { useAuth } from "../../hooks/AuthContext";
import { useLanguage } from "../../context/LanguageContext";
import "./home.css";

export default function HomePage() {
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const heroBgRef = useRef(null);
  const { t } = useLanguage();

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
            <span>{t("home.eyebrow")}</span>
          </div>
          <h1 className="hero-title">
            {t("home.title")}<br />
            <span className="highlight">{t("home.highlight")}</span>
          </h1>
          <p className="hero-subtitle">
            {t("home.description")}
          </p>
          <div className="hero-buttons">
            <button className="btn btn-hero-primary" onClick={() => navigate("/signup")}>
              <i className="ri-rocket-line me-2"></i>{t("home.start")}
            </button>
            <button className="btn btn-hero-secondary" onClick={() => navigate("/login")}>
              <i className="ri-login-box-line me-2"></i>{t("home.login")}
            </button>
          </div>
          <div className="hero-tags">
            <span className="hero-tag"><i className="ri-clipboard-line me-1"></i>Survey management</span>
            <span className="hero-tag"><i className="ri-brain-line me-1"></i>AI-assisted analysis</span>
            <span className="hero-tag"><i className="ri-folder-chart-line me-1"></i>Project management</span>
            <span className="hero-tag"><i className="ri-table-line me-1"></i>Structured results</span>
          </div>
        </div>

        <div className="scroll-hint">
          <span>{t("home.scroll")}</span>
          <i className="ri-arrow-down-line"></i>
        </div>
      </section>

      {/* ── Features Section ── */}
      <section className="features-section">
        <div className="container">
          <div className="text-center mb-5">
            <div className="section-badge mb-3"><span>{t("home.features")}</span></div>
            <h2 className="section-title">{t("home.featureTitle")}</h2>
            <p className="section-subtitle">
              From survey creation and feedback collection to AI-assisted analysis, organize written feedback into clear categories and analysis records.
            </p>
          </div>
          <div className="row g-4">
            {[
              { icon: "ri-upload-cloud-2-line", iconBg: "bg-lavender-50", iconColor: "text-lavender", tag: "Data import", tagClass: "tag-lavender", title: "Upload and import data", desc: "Upload survey data or text files and bring external feedback into the analysis workspace." },
              { icon: "ri-brain-line", iconBg: "bg-mauve-50", iconColor: "text-mauve", tag: "AI assistance", tagClass: "tag-mauve", title: "AI-assisted analysis", desc: "Combine TF-IDF and Gemini API to organize text feedback and produce categorized results." },
              { icon: "ri-folder-chart-line", iconBg: "bg-periwinkle-50", iconColor: "text-periwinkle", tag: "Save projects", tagClass: "tag-periwinkle", title: "Project management", desc: "Keep survey data, analysis results, and history for each training project together for easy follow-up." },
              { icon: "ri-history-line", iconBg: "bg-lavender-50", iconColor: "text-lavender", tag: "Track history", tagClass: "tag-lavender", title: "Save history", desc: "Review past analysis projects and activity history whenever you need to continue your work." },
              { icon: "ri-table-line", iconBg: "bg-mauve-50", iconColor: "text-mauve", tag: "Results", tagClass: "tag-mauve", title: "Structured results", desc: "Review categorized results, key feedback, and analysis history in a clear table." },
              { icon: "ri-survey-line", iconBg: "bg-periwinkle-50", iconColor: "text-periwinkle", tag: "Survey collection", tagClass: "tag-periwinkle", title: "Create surveys and collect feedback", desc: "Create surveys, collect responses, and send feedback to the AI Analysis Assistant for organization." },
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
            <div className="section-badge mb-3"><span>How it works</span></div>
            <h2 className="section-title">How it works</h2>
            <p className="section-subtitle">Four simple steps to organize and analyze training feedback.</p>
          </div>
          <div className="row g-4">
            {[
              { num: "1", numBg: "bg-lavender-100", numColor: "text-lavender", iconBg: "bg-lavender-50", icon: "ri-user-add-line", iconColor: "text-lavender", title: "Create account", desc: "Sign up and log in to create surveys or manage analysis projects." },
              { num: "2", numBg: "bg-mauve-100", numColor: "text-mauve", iconBg: "bg-mauve-50", icon: "ri-upload-2-line", iconColor: "text-mauve", title: "Create a survey or upload data", desc: "Create a survey to collect feedback, or upload existing surveys and text data." },
              { num: "3", numBg: "bg-periwinkle-100", numColor: "text-periwinkle", iconBg: "bg-periwinkle-50", icon: "ri-chat-3-line", iconColor: "text-periwinkle", title: "Use the AI Analysis Assistant", desc: "Use the AI Analysis Assistant to organize written feedback into categories and analysis records." },
              { num: "4", numBg: "bg-lavender-100", numColor: "text-lavender", iconBg: "bg-lavender-50", icon: "ri-save-line", iconColor: "text-lavender", title: "Save and review results", desc: "Save analysis results in a project for easy review, organization, and follow-up." },
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
            <h2 className="cta-title">Ready to organize your training feedback?</h2>
            <p className="cta-subtitle">
              Create an account to organize written feedback and explore insights with survey management and the AI Analysis Assistant.
            </p>
            <div className="cta-buttons">
              <button className="btn btn-cta-primary" onClick={() => navigate("/signup")}>
                <i className="ri-rocket-line me-2"></i>Get started
              </button>
              <button className="btn btn-cta-secondary" onClick={() => navigate("/login")}>
                Already have an account? Log in
              </button>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
