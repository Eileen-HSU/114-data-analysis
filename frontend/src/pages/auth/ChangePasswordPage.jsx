import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./auth.css";
import axios from "axios";
import { apiUrl } from "../../lib/api";

export default function ChangePasswordPage() {
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
      const response = await axios.post(apiUrl("/api/auth/send-otp"), {
        email: val,
        type: "PASSWORD_CHANGE" // 後端會根據這個 type 決定郵件內的連結要帶 ?from=change
      }, {
        timeout: 30000
      });

      if (response.status === 200) {
        setSentEmail(val);
        setStep("done");
      }
    } catch (error) {
      const errorMsg = error.response?.data?.error || "發送失敗，請稍後再試";
      showError(errorMsg);
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = "發送修改連結";
      }
    }
  };

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* Left Visual */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-change-pw">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">修改您的密碼</h2>
            <p className="auth-visual-desc">
              為了保護您的帳號安全，我們會發送驗證連結到您的信箱，確認身份後即可設定新密碼。完成後將直接進入工作區。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-mail-send-line", text: "驗證連結發送至您的信箱" },
                { icon: "ri-time-line", text: "連結 10 分鐘內有效" },
                { icon: "ri-shield-check-line", text: "修改完成直接導向工作區" },
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
                <div className="forgot-icon-wrap">
                  <i className="ri-lock-password-line"></i>
                </div>
                <h1 className="auth-title">修改密碼</h1>
                <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                  輸入您的帳號電子郵件，我們將發送密碼修改連結。
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
                    <p ref={errorRef} style={{ display: "none", color: "#ef4444", fontSize: 13, marginTop: 6 }}></p>
                  </div>

                  <button ref={submitBtnRef} type="submit" className="btn btn-auth-submit w-100 mb-3">
                    發送修改連結
                  </button>

                  <button
                    type="button"
                    className="w-100"
                    style={{
                      padding: "14px", background: "none", border: "1.5px solid var(--slate-200)",
                      borderRadius: 12, fontSize: 15, fontWeight: 600, color: "var(--slate-500)",
                      cursor: "pointer", transition: "all 0.2s",
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
                <div className="forgot-success-icon">
                  <i className="ri-mail-check-line"></i>
                </div>
                <h1 className="auth-title" style={{ textAlign: "center" }}>郵件已發送！</h1>
                <p style={{ color: "var(--slate-500)", fontSize: 15, marginBottom: 8 }}>
                  我們已將密碼修改連結發送至
                </p>
                <p style={{ fontWeight: 700, color: "var(--slate-800)", fontSize: 16, marginBottom: 28 }}>
                  {sentEmail}
                </p>
                <p style={{ color: "var(--slate-400)", fontSize: 13, marginBottom: 32 }}>
                  請檢查您的收件匣。點擊連結後即可設定新密碼並直接進入工作區。
                </p>

                <button className="btn btn-auth-submit w-100 mb-3" onClick={() => navigate("/profile")}>
                  返回個人資料
                </button>

                <button
                  className="w-100"
                  style={{
                    padding: "14px", background: "none", border: "1.5px solid var(--slate-200)",
                    borderRadius: 12, fontSize: 14, fontWeight: 600, color: "var(--slate-500)", cursor: "pointer",
                  }}
                  onClick={() => {
                    setStep("send");
                    if (submitBtnRef.current) {
                      submitBtnRef.current.disabled = false;
                      submitBtnRef.current.innerHTML = "發送修改連結";
                    }
                  }}
                >
                  重新發送
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
