import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./auth.css";
import axios from "axios";
import { apiUrl } from "../../lib/api";
import conqightLogo from "../../assets/conqight-logo.png";

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const emailRef = useRef(null);
  const errorRef = useRef(null);
  const stepSendRef = useRef(null);
  const stepDoneRef = useRef(null);
  const sentEmailRef = useRef(null);
  const submitBtnRef = useRef(null);
  const initialEmail = new URLSearchParams(location.search).get("email")?.trim() || "";

  useEffect(() => {
    const restoreEmail = () => {
      if (emailRef.current) {
        emailRef.current.value = initialEmail;
      }
    };

    restoreEmail();

    if (!initialEmail) {
      const timer = window.setTimeout(restoreEmail, 200);
      return () => window.clearTimeout(timer);
    }
  }, [initialEmail]);

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
    if (!val) { showError("Please enter your email address"); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) { showError("Please enter a valid email address"); return; }
    clearError();

    const btn = submitBtnRef.current;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="ri-loader-4-line" style="animation:spin 1s linear infinite"></i> Sending...`;
    }

    try {
      // 3. 呼叫後端 API
      const response = await axios.post(apiUrl("/api/auth/send-otp"), {
        email: val,
        type: "PASSWORD_RESET" // 後端會根據這個 type 決定郵件內的連結要帶 ?from=forgot
      }, {
        timeout: 30000
      });

      if (response.status === 200) {
        if (sentEmailRef.current) sentEmailRef.current.textContent = val;
        if (stepSendRef.current) stepSendRef.current.style.display = "none";
        if (stepDoneRef.current) stepDoneRef.current.style.display = "block";
      }
    } catch (error) {
      // 4. 錯誤處理 (例如：Email 沒註冊過)
      const errorMsg = error.response?.data?.error || "Unable to send. Please try again.";
      showError(errorMsg);
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = "Send reset link";
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
                src={conqightLogo}
                alt="CON QIGHT"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">Reset your password</h2>
            <p className="auth-visual-desc">
              <span>Enter your email</span>
              <span>We will send a secure reset link</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-mail-send-line", text: "Reset link sent by email" },
                { icon: "ri-time-line", text: "Link valid for 10 minutes" },
                { icon: "ri-shield-check-line", text: "Your account is protected throughout" },
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
            <span>Back to login</span>
          </button>

          <div className="auth-form-wrapper">
            {/* Mobile Logo */}
            <div className="d-lg-none text-center mb-4">
              <div className="mobile-logo">
                <img src={conqightLogo} alt="CON QIGHT" />
              </div>
              <span className="mobile-logo-text">DataAnalysis</span>
            </div>

            {/* ── Step 1: Enter Email ── */}
            <div ref={stepSendRef}>
              <div className="forgot-icon-wrap">
                <i className="ri-lock-password-line"></i>
              </div>
              <h1 className="auth-title">Forgot password?</h1>
              <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                Enter your account email and we will send a password-reset link.
              </p>

              <form onSubmit={handleSubmit} noValidate autoComplete="off">
                <div className="mb-4">
                  <label className="auth-label">Email</label>
                  <div className="position-relative">
                    <i className="ri-mail-line form-icon"></i>
                    <input
                      ref={emailRef}
                      type="email"
                      name="forgot_password_email"
                      autoComplete="off"
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
                  Send reset link
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
                  Back to login
                </button>
              </form>

              <p className="auth-terms text-center mt-4">
                Don't have an account?{" "}
                <a className="auth-link" onClick={() => navigate("/signup")} style={{ cursor: "pointer" }}>
                  Sign up for free
                </a>
              </p>
            </div>

            {/* ── Step 2: Sent Success ── */}
            <div ref={stepDoneRef} style={{ display: "none", textAlign: "center" }}>
              <div className="forgot-success-icon">
                <i className="ri-mail-check-line"></i>
              </div>
              <h1 className="auth-title" style={{ textAlign: "center" }}>Email sent!</h1>
              <p style={{ color: "var(--slate-500)", fontSize: 15, lineHeight: 1.7, marginBottom: 8 }}>
                We have sent a password reset link to
              </p>
              <p style={{ fontWeight: 700, color: "var(--slate-800)", fontSize: 16, marginBottom: 28 }}>
                <span ref={sentEmailRef}></span>
              </p>
              <p style={{ color: "var(--slate-400)", fontSize: 13, lineHeight: 1.7, marginBottom: 32 }}>
                Check your inbox (including spam). The link will be valid for <strong>10 minutes</strong>.
              </p>

              <button
                className="btn btn-auth-submit w-100 mb-3"
                onClick={() => navigate("/login")}
              >
                <i className="ri-arrow-left-line" style={{ marginRight: 6 }}></i>
                Back to login
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
                    submitBtnRef.current.innerHTML = "Send reset link";
                  }
                  if (emailRef.current) emailRef.current.value = "";
                }}
              >
                <i className="ri-refresh-line" style={{ marginRight: 6 }}></i>
                Resend
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
