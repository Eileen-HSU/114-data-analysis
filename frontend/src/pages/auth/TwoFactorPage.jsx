import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./auth.css";

export default function TwoFactorPage() {
  const navigate = useNavigate();
  const emailRef = useRef(null);
  const errorRef = useRef(null);
  const submitBtnRef = useRef(null);
  const [step, setStep] = useState("send");
  const [sentEmail, setSentEmail] = useState("");

  const showError = (msg) => {
    if (errorRef.current) {
      errorRef.current.textContent = msg;
      errorRef.current.style.display = "flex";
    }
    emailRef.current?.classList.add("is-invalid");
  };

  const clearError = () => {
    if (errorRef.current) errorRef.current.style.display = "none";
    emailRef.current?.classList.remove("is-invalid");
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const val = emailRef.current?.value.trim() ?? "";
    if (!val) { showError("請輸入電子郵件地址"); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) { showError("請輸入有效的電子郵件格式"); return; }
    clearError();

    const btn = submitBtnRef.current;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="ri-loader-4-line" style="animation:spin 1s linear infinite"></i> 發送中...`;
    }

    setTimeout(() => {
      setSentEmail(val);
      setStep("done");
    }, 1200);
  };

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* Left Visual */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-2fa">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">啟用兩步驟驗證</h2>
            <p className="auth-visual-desc">
              開啟雙重驗證後，每次登入都需要額外確認，大幅提升帳號安全性。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-shield-check-line", text: "防止未授權的帳號存取" },
                { icon: "ri-mail-send-line", text: "驗證碼發送至您的信箱" },
                { icon: "ri-lock-2-line", text: "即使密碼外洩也能保護帳號" },
              ].map((f, i) => (
                <div className="auth-feature-item" key={i}>
                  <div className="auth-feature-icon">
                    <i className={f.icon}></i>
                  </div>
                  <span>{f.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Form */}
        <div className="col-lg-6 d-flex align-items-center justify-content-center auth-form-area">
          <button className="back-home-btn" onClick={() => navigate("/profile")}>
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>返回個人資料</span>
          </button>

          <div className="auth-form-wrapper">
            <div className="d-lg-none text-center mb-4">
              <div className="mobile-logo">
                <i className="ri-bar-chart-box-line"></i>
              </div>
              <span className="mobile-logo-text">DataAnalysis</span>
            </div>

            {step === "send" && (
              <>
                <div className="forgot-icon-wrap" style={{ background: "linear-gradient(135deg, #edf2f7, #e8f4f8)", color: "#8fa3b8" }}>
                  <i className="ri-shield-check-line"></i>
                </div>
                <h1 className="auth-title">兩步驟驗證</h1>
                <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                  輸入您的帳號電子郵件，我們將發送啟用驗證連結。
                </p>

                <form onSubmit={handleSubmit} noValidate>
                  <div className="mb-4">
                    <label className="auth-label">電子郵件</label>
                    <div className="position-relative">
                      <i className="ri-mail-line form-icon"></i>
                      <input
                        ref={emailRef}
                        type="email"
                        className="form-control form-control-custom"
                        placeholder="your@email.com"
                        onInput={clearError}
                      />
                    </div>
                    <p
                      ref={errorRef}
                      style={{
                        display: "none",
                        color: "#ef4444",
                        fontSize: 13,
                        marginTop: 6,
                        alignItems: "center",
                        gap: 5,
                      }}
                    ></p>
                  </div>

                  {/* 說明區塊 */}
                  <div style={{
                    background: "#f0f4f8",
                    border: "1px solid #dce6f0",
                    borderRadius: 12,
                    padding: "14px 16px",
                    marginBottom: 20,
                    display: "flex",
                    gap: 10,
                    alignItems: "flex-start",
                  }}>
                    <i className="ri-information-line" style={{ color: "#8fa3b8", fontSize: 16, marginTop: 2, flexShrink: 0 }}></i>
                    <p style={{ fontSize: 13, color: "var(--slate-500)", margin: 0, lineHeight: 1.6 }}>
                      啟用後，每次登入時系統將發送一次性驗證碼至您的信箱，輸入正確後才能完成登入。
                    </p>
                  </div>

                  <button ref={submitBtnRef} type="submit" className="btn btn-auth-submit w-100 mb-3">
                    發送啟用連結
                  </button>

                  <button
                    type="button"
                    className="w-100"
                    style={{
                      padding: "14px",
                      background: "none",
                      border: "1.5px solid var(--slate-200)",
                      borderRadius: 12,
                      fontSize: 15,
                      fontWeight: 600,
                      color: "var(--slate-500)",
                      cursor: "pointer",
                      transition: "all 0.2s",
                      whiteSpace: "nowrap",
                    }}
                    onClick={() => navigate("/profile")}
                  >
                    取消
                  </button>
                </form>
              </>
            )}

            {step === "done" && (
              <div style={{ textAlign: "center" }}>
                <div className="forgot-success-icon" style={{ background: "#edf2f7", color: "#8fa3b8" }}>
                  <i className="ri-shield-check-line"></i>
                </div>
                <h1 className="auth-title" style={{ textAlign: "center" }}>驗證郵件已發送！</h1>
                <p style={{ color: "var(--slate-500)", fontSize: 15, lineHeight: 1.7, marginBottom: 8 }}>
                  我們已將兩步驟驗證啟用連結發送至
                </p>
                <p style={{ fontWeight: 700, color: "var(--slate-800)", fontSize: 16, marginBottom: 28 }}>
                  {sentEmail}
                </p>
                <p style={{ color: "var(--slate-400)", fontSize: 13, lineHeight: 1.7, marginBottom: 32 }}>
                  請點擊信件中的連結完成啟用。連結將在 <strong>30 分鐘</strong>內有效。<br />
                  啟用後下次登入即會要求輸入驗證碼。
                </p>

                <button
                  className="btn btn-auth-submit w-100 mb-3"
                  onClick={() => navigate("/profile?two_factor=enabled")}
                >
                  <i className="ri-checkbox-circle-line" style={{ marginRight: 6 }}></i>
                  模擬信件連結完成啟用
                </button>

                <button
                  className="w-100"
                  style={{
                    padding: "14px",
                    background: "none",
                    border: "1.5px solid var(--slate-200)",
                    borderRadius: 12,
                    fontSize: 14,
                    fontWeight: 600,
                    color: "var(--slate-500)",
                    cursor: "pointer",
                    transition: "all 0.2s",
                    whiteSpace: "nowrap",
                  }}
                  onClick={() => {
                    setStep("send");
                    if (submitBtnRef.current) {
                      submitBtnRef.current.disabled = false;
                      submitBtnRef.current.innerHTML = "發送啟用連結";
                    }
                    if (emailRef.current) emailRef.current.value = "";
                  }}
                >
                  <i className="ri-refresh-line" style={{ marginRight: 6 }}></i>
                  重新發送
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .auth-visual-2fa {
          background-image: url('https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/4a8acdc8a7b54754399ef652077c11e9.png');
          background-size: cover;
          background-position: center 20%;
        }
      `}</style>
    </div>
  );
}
