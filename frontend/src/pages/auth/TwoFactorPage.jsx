import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiUrl } from "../../lib/api";
import "./auth.css";

export default function TwoFactorPage() {
  const navigate = useNavigate();
  const emailRef = useRef(null);
  const otpRef = useRef(null);
  const errorRef = useRef(null);
  const submitBtnRef = useRef(null);
  const [step, setStep] = useState("send");
  const [sentEmail, setSentEmail] = useState("");
  const [isVerifying, setIsVerifying] = useState(false);

  useEffect(() => {
    const clearFields = () => {
      if (emailRef.current) emailRef.current.value = "";
      if (otpRef.current) otpRef.current.value = "";
    };
    clearFields();
    const timer = window.setTimeout(clearFields, 200);
    return () => window.clearTimeout(timer);
  }, [step]);

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

  const sendCode = async (e) => {
    e.preventDefault();
    const email = emailRef.current?.value.trim() ?? "";
    if (!email) {
      showError("請輸入電子郵件");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      showError("請輸入正確的電子郵件格式");
      return;
    }
    clearError();

    const btn = submitBtnRef.current;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="ri-loader-4-line" style="animation:spin 1s linear infinite"></i> 寄送中...`;
    }

    try {
      const res = await fetch(apiUrl("/api/auth/2fa/send"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (res.ok) {
        setSentEmail(email);
        setStep("otp");
      } else {
        showError(data.error || "寄送失敗，請稍後再試");
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = "寄送驗證碼";
        }
      }
    } catch {
      showError("連線失敗，請稍後再試");
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = "寄送驗證碼";
      }
    }
  };

  const verifyCode = async () => {
    const otp = otpRef.current?.value.trim() ?? "";
    if (!/^\d{6}$/.test(otp)) {
      showError("請輸入 6 位數驗證碼");
      return;
    }
    clearError();
    setIsVerifying(true);

    try {
      const res = await fetch(apiUrl("/api/auth/2fa/two-factor"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: sentEmail, otp }),
      });
      const data = await res.json();
      if (res.ok) {
        navigate("/profile?two_factor=enabled");
      } else {
        showError(data.error || "驗證失敗，請重新輸入");
        setIsVerifying(false);
      }
    } catch {
      showError("連線失敗，請稍後再試");
      setIsVerifying(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
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
              為您的帳號增加一層保護，登入時需輸入電子郵件驗證碼。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-shield-check-line", text: "降低未授權登入風險" },
                { icon: "ri-mail-send-line", text: "驗證碼會寄送至您的信箱" },
                { icon: "ri-lock-2-line", text: "可隨時在個人資料中停用" },
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

        <div className="col-lg-6 d-flex align-items-center justify-content-center auth-form-area">
          <button className="back-home-btn" onClick={() => navigate("/profile")}>
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>返回個人資料</span>
          </button>

          <div className="auth-form-wrapper two-factor-form-wrapper">
            {step === "send" && (
              <>
                <h1 className="auth-title">啟用兩步驟驗證</h1>
                <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                  輸入您的電子郵件，我們會寄送驗證碼確認身分。
                </p>

                <form onSubmit={sendCode} noValidate autoComplete="off">
                  <div className="mb-4">
                    <label className="auth-label">電子郵件</label>
                    <div className="position-relative">
                      <i className="ri-mail-line form-icon"></i>
                      <input
                        ref={emailRef}
                        type="email"
                        name="two_factor_email"
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
                    ></p>
                  </div>

                  <div style={{
                    background: "#fff1f2",
                    border: "1.5px solid #fda4af",
                    borderRadius: 12,
                    padding: "14px 16px",
                    marginBottom: 20,
                    display: "flex",
                    gap: 10,
                    alignItems: "flex-start",
                    boxShadow: "0 8px 18px rgba(244, 63, 94, 0.12)",
                  }}>
                    <i className="ri-information-line" style={{ color: "#e11d48", fontSize: 16, marginTop: 2, flexShrink: 0 }}></i>
                    <p style={{ fontSize: 13, color: "#be123c", margin: 0, lineHeight: 1.6, fontWeight: 600 }}>
                      啟用後，下次登入時需輸入信箱驗證碼才能進入帳號。
                    </p>
                  </div>

                  <button ref={submitBtnRef} type="submit" className="btn btn-auth-submit w-100 mb-3">
                    寄送驗證碼
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

            {step === "otp" && (
              <div>
                <h1 className="auth-title" style={{ textAlign: "center" }}>輸入驗證碼</h1>
                <p style={{ color: "var(--slate-500)", fontSize: 15, lineHeight: 1.7, marginBottom: 8, textAlign: "center" }}>
                  我們已將驗證碼寄送至
                </p>
                <p style={{ fontWeight: 700, color: "var(--slate-800)", fontSize: 16, marginBottom: 28, textAlign: "center" }}>
                  {sentEmail}
                </p>

                <div className="mb-3">
                  <label className="auth-label">驗證碼</label>
                  <div className="position-relative">
                    <i className="ri-key-2-line form-icon"></i>
                    <input
                      ref={otpRef}
                      type="text"
                      inputMode="numeric"
                      name="two_factor_code"
                      autoComplete="off"
                      maxLength={6}
                      className="form-control form-control-custom"
                      placeholder="請輸入 6 位數驗證碼"
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

                <button className="btn btn-auth-submit w-100 mb-3" onClick={verifyCode} disabled={isVerifying}>
                  <i className="ri-checkbox-circle-line" style={{ marginRight: 6 }}></i>
                  {isVerifying ? "驗證中..." : "完成啟用"}
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
                    setIsVerifying(false);
                    if (submitBtnRef.current) {
                      submitBtnRef.current.disabled = false;
                      submitBtnRef.current.innerHTML = "寄送驗證碼";
                    }
                    if (emailRef.current) emailRef.current.value = "";
                  }}
                >
                  <i className="ri-refresh-line" style={{ marginRight: 6 }}></i>
                  重新寄送
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
