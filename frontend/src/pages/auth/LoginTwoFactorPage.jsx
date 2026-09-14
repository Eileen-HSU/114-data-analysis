import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";
import conqightLogo from "../../assets/conqight-logo.png";
import "./auth.css";

const PENDING_2FA_KEY = "dataanalysis_pending_2fa";

export default function LoginTwoFactorPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const pendingUser = useMemo(() => {
    const raw = sessionStorage.getItem(PENDING_2FA_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      sessionStorage.removeItem(PENDING_2FA_KEY);
      return null;
    }
  }, []);

  useEffect(() => {
    if (!pendingUser) navigate("/login", { replace: true });
    const clearFields = () => setCode("");
    clearFields();
    const timer = window.setTimeout(clearFields, 200);
    return () => window.clearTimeout(timer);
  }, [navigate, pendingUser]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmedCode = code.trim();
    if (!/^\d{6}$/.test(trimmedCode)) {
      setError("Enter the 6-digit verification code");
      return;
    }

    setError("");
    setIsSubmitting(true);

    try {
      const res = await fetch(apiUrl("/api/auth/2fa/login/two-factor"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: pendingUser.email, otp: trimmedCode, pre_auth_token: pendingUser.pre_auth_token }),
      });

      const data = await res.json();
      if (res.ok) {
        login({ ...data.user, token: data.token });
        sessionStorage.removeItem(PENDING_2FA_KEY);
        navigate("/workspace", { replace: true });
      } else {
        setError(data.error || "Incorrect code. Please try again.");
        setIsSubmitting(false);
      }
    } catch (err) {
      setError("Connection failed. Please try again later.");
      setIsSubmitting(false);
    }
  };

  if (!pendingUser) return null;

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-login-2fa">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src={conqightLogo}
                alt="CON QIGHT"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">Two-factor authentication</h2>
            <p className="auth-visual-desc">
              <span>Enter the verification code from your email</span>
              <span>Sign in securely after verification</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-shield-keyhole-line", text: "Protect your account" },
                { icon: "ri-mail-send-line", text: "Verification code sent by email" },
                { icon: "ri-lock-2-line", text: "Code valid for 10 minutes" },
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
          <button
            className="back-home-btn"
            onClick={() => {
              sessionStorage.removeItem(PENDING_2FA_KEY);
              navigate("/login");
            }}
          >
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>Back to login</span>
          </button>

          <div className="auth-form-wrapper two-factor-form-wrapper">
            <h1 className="auth-title">Enter verification code</h1>
            <p className="auth-subtitle" style={{ marginBottom: 28 }}>
              Enter the code sent to  {pendingUser.email}  (6 digits)
            </p>

            <form onSubmit={handleSubmit} noValidate autoComplete="off">
              <div className="mb-3">
                <label className="auth-label">Verification code</label>
                <div className="position-relative">
                  <i className="ri-key-2-line form-icon"></i>
                  <input
                    type="text"
                    inputMode="numeric"
                    name="login_two_factor_code"
                    autoComplete="off"
                    maxLength={6}
                    className="form-control form-control-custom"
                    placeholder="Enter the 6-digit verification code"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  />
                </div>
              </div>

              {error && (
                <p style={{ color: "#ef4444", fontSize: 13, marginTop: 6, fontWeight: 600 }}>
                  {error}
                </p>
              )}

              <button type="submit" className="btn btn-auth-submit w-100 mt-2" disabled={isSubmitting}>
                {isSubmitting ? "Verifying…" : "Verify"}
              </button>
            </form>
          </div>
        </div>
      </div>

      <style>{`
        .auth-visual-login-2fa {
          background-image: url('https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/4a8acdc8a7b54754399ef652077c11e9.png');
          background-size: cover;
          background-position: center 20%;
        }
      `}</style>
    </div>
  );
}
