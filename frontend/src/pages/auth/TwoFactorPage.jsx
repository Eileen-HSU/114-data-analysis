import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiUrl } from "../../lib/api";
import conqightLogo from "../../assets/conqight-logo.png";
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
      showError("Please enter your email");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      showError("Please enter a valid email address");
      return;
    }
    clearError();

    const btn = submitBtnRef.current;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="ri-loader-4-line" style="animation:spin 1s linear infinite"></i> Sending...`;
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
        showError(data.error || "Unable to send. Please try again.");
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = "Send verification code";
        }
      }
    } catch {
      showError("Connection failed. Please try again later.");
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = "Send verification code";
      }
    }
  };

  const verifyCode = async () => {
    const otp = otpRef.current?.value.trim() ?? "";
    if (!/^\d{6}$/.test(otp)) {
      showError("Enter the 6-digit verification code");
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
        showError(data.error || "Verification failed. Please try again.");
        setIsVerifying(false);
      }
    } catch {
      showError("Connection failed. Please try again later.");
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
                src={conqightLogo}
                alt="CON QIGHT"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">Enable two-factor authentication</h2>
            <p className="auth-visual-desc">
              <span>Add another layer of account protection</span>
              <span>Verify your identity with an email code when logging in</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-shield-check-line", text: "Reduce unauthorized access risk" },
                { icon: "ri-mail-send-line", text: "Verification codes are sent to your email" },
                { icon: "ri-lock-2-line", text: "Disable this in your profile at any time" },
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
            <span>Back to profile</span>
          </button>

          <div className="auth-form-wrapper two-factor-form-wrapper">
            {step === "send" && (
              <>
                <h1 className="auth-title">Enable two-factor authentication</h1>
                <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                  Enter your email address to receive a code to verify your identity.
                </p>

                <form onSubmit={sendCode} noValidate autoComplete="off">
                  <div className="mb-4">
                    <label className="auth-label">Email</label>
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
                      Once enabled, you will need an email verification code the next time you log in.
                      <br />
                      The email may be in your spam folder
                    </p>
                  </div>

                  <button ref={submitBtnRef} type="submit" className="btn btn-auth-submit w-100 mb-3">
                    Send verification code
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
                    Cancel
                  </button>
                </form>
              </>
            )}

            {step === "otp" && (
              <div>
                <h1 className="auth-title" style={{ textAlign: "center" }}>Enter verification code</h1>
                <p style={{ color: "var(--slate-500)", fontSize: 15, lineHeight: 1.7, marginBottom: 8, textAlign: "center" }}>
                  We have sent a verification code to
                </p>
                <p style={{ fontWeight: 700, color: "var(--slate-800)", fontSize: 16, marginBottom: 28, textAlign: "center" }}>
                  {sentEmail}
                </p>

                <div className="mb-3">
                  <label className="auth-label">Verification code</label>
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
                      placeholder="Enter the 6-digit verification code"
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
                  {isVerifying ? "Verifying…" : "Finish setup"}
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
                      submitBtnRef.current.innerHTML = "Send verification code";
                    }
                    if (emailRef.current) emailRef.current.value = "";
                  }}
                >
                  <i className="ri-refresh-line" style={{ marginRight: 6 }}></i>
                  Resend code
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
