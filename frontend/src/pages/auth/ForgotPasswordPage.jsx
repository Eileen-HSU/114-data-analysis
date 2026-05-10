import { useRef } from "react";
import { useNavigate } from "react-router-dom";
import "./auth.css";
import axios from "axios";
import { apiUrl } from "../../lib/api";

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const emailRef = useRef(null);
  const errorRef = useRef(null);
  const stepSendRef = useRef(null);
  const stepDoneRef = useRef(null);
  const sentEmailRef = useRef(null);
  const submitBtnRef = useRef(null);

  const showError = (msg) => {
    const el = errorRef.current;
    if (!el) return;
    el.textContent = msg;
    el.style.display = "flex";
    emailRef.current?.classList.add("is-invalid");
  };

  const clearError = () => {
    if (errorRef.current) errorRef.current.style.display = "none";
    emailRef.current?.classList.remove("is-invalid");
  };

  const handleSubmit = async (e) => {
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

    try {
      // 3. 呼叫後端 API
      const response = await axios.post(apiUrl("/api/auth/send-otp"), {
        email: val,
        type: "PASSWORD_RESET" // 後端會根據這個 type 決定郵件內的連結要帶 ?from=forgot
      });

      if (response.status === 200) {
        navigate(`/reset-password?email=${encodeURIComponent(val)}`);
      }
    } catch (error) {
      // 4. 錯誤處理 (例如：Email 沒註冊過)
      const errorMsg = error.response?.data?.error || "發送失敗，請稍後再試";
      showError(errorMsg);
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = "發送重設連結";
      }
    }
  };

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* Left Visual */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-forgot">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">重設您的密碼</h2>
            <p className="auth-visual-desc">
              別擔心，我們會發送一封重設連結到您的信箱，幾分鐘內即可完成。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-mail-send-line", text: "安全重設連結發送至信箱" },
                { icon: "ri-time-line", text: "連結 30 分鐘內有效" },
                { icon: "ri-shield-check-line", text: "全程加密保護帳號安全" },
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
          <button className="back-home-btn" onClick={() => navigate("/login")}>
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>返回登入</span>
          </button>

          <div className="auth-form-wrapper">
            {/* Mobile Logo */}
            <div className="d-lg-none text-center mb-4">
              <div className="mobile-logo">
                <i className="ri-bar-chart-box-line"></i>
              </div>
              <span className="mobile-logo-text">DataAnalysis</span>
            </div>

            {/* ── Step 1: Enter Email ── */}
            <div ref={stepSendRef}>
              <div className="forgot-icon-wrap">
                <i className="ri-lock-password-line"></i>
              </div>
              <h1 className="auth-title">忘記密碼？</h1>
              <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                輸入您的帳號電子郵件，我們將發送密碼重設連結。
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
                  >
                  </p>
                </div>

                <button ref={submitBtnRef} type="submit" className="btn btn-auth-submit w-100 mb-3">
                  發送重設連結
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
                  onClick={() => navigate("/login")}
                >
                  返回登入
                </button>
              </form>

              <p className="auth-terms text-center mt-4">
                還沒有帳號？{" "}
                <a className="auth-link" onClick={() => navigate("/signup")} style={{ cursor: "pointer" }}>
                  免費註冊
                </a>
              </p>
            </div>

            {/* ── Step 2: Sent Success ── */}
            <div ref={stepDoneRef} style={{ display: "none", textAlign: "center" }}>
              <div className="forgot-success-icon">
                <i className="ri-mail-check-line"></i>
              </div>
              <h1 className="auth-title" style={{ textAlign: "center" }}>郵件已發送！</h1>
              <p style={{ color: "var(--slate-500)", fontSize: 15, lineHeight: 1.7, marginBottom: 8 }}>
                我們已將密碼重設連結發送至
              </p>
              <p style={{ fontWeight: 700, color: "var(--slate-800)", fontSize: 16, marginBottom: 28 }}>
                <span ref={sentEmailRef}></span>
              </p>
              <p style={{ color: "var(--slate-400)", fontSize: 13, lineHeight: 1.7, marginBottom: 32 }}>
                請檢查您的收件匣（包含垃圾郵件資料夾）。連結將在 <strong>30 分鐘</strong>內有效。
              </p>

              <button
                className="btn btn-auth-submit w-100 mb-3"
                onClick={() => navigate("/login")}
              >
                <i className="ri-arrow-left-line" style={{ marginRight: 6 }}></i>
                返回登入頁面
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
                  if (stepSendRef.current) stepSendRef.current.style.display = "block";
                  if (stepDoneRef.current) stepDoneRef.current.style.display = "none";
                  if (submitBtnRef.current) {
                    submitBtnRef.current.disabled = false;
                    submitBtnRef.current.innerHTML = "發送重設連結";
                  }
                  if (emailRef.current) emailRef.current.value = "";
                }}
              >
                <i className="ri-refresh-line" style={{ marginRight: 6 }}></i>
                重新發送
              </button>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .forgot-icon-wrap {
          width: 64px; height: 64px;
          display: flex; align-items: center; justify-content: center;
          background: linear-gradient(135deg, var(--rose-100), var(--pink-100));
          border-radius: 18px;
          font-size: 28px;
          color: var(--rose-500);
          margin-bottom: 20px;
        }
        .forgot-success-icon {
          width: 88px; height: 88px;
          display: flex; align-items: center; justify-content: center;
          background: linear-gradient(135deg, var(--rose-100), var(--pink-100));
          border-radius: 50%;
          font-size: 40px;
          color: var(--rose-500);
          margin: 0 auto 24px;
        }
        .auth-visual-forgot {
          background-image: url('https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/c7324bc840efa1d4185cef328ecdebbc.png');
          background-size: cover;
          background-position: center center;
        }
      `}</style>
    </div>
  );
}
