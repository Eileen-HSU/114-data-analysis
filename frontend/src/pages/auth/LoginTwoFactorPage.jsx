import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";
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
      setError("請輸入 6 位數驗證碼");
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
        setError(data.error || "驗證碼錯誤，請重新輸入");
        setIsSubmitting(false);
      }
    } catch (err) {
      setError("連線失敗，請稍後再試");
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
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">兩步驟驗證</h2>
            <p className="auth-visual-desc">
              我們已將驗證碼寄到您的電子郵件，請完成驗證後繼續登入。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-shield-keyhole-line", text: "保護您的帳號安全" },
                { icon: "ri-mail-send-line", text: "驗證碼已寄送到信箱" },
                { icon: "ri-lock-2-line", text: "驗證碼 10 分鐘內有效" },
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
            <span>返回登入</span>
          </button>

          <div className="auth-form-wrapper">
            <div className="forgot-icon-wrap" style={{ background: "#edf2f7", color: "#8fa3b8" }}>
              <i className="ri-shield-keyhole-line"></i>
            </div>
            <h1 className="auth-title">輸入驗證碼</h1>
            <p className="auth-subtitle" style={{ marginBottom: 28 }}>
              請輸入寄送至 {pendingUser.email} 的 6 位數驗證碼
            </p>

            <form onSubmit={handleSubmit} noValidate autoComplete="off">
              <div className="mb-3">
                <label className="auth-label">驗證碼</label>
                <div className="position-relative">
                  <i className="ri-key-2-line form-icon"></i>
                  <input
                    type="text"
                    inputMode="numeric"
                    name="login_two_factor_code"
                    autoComplete="off"
                    maxLength={6}
                    className="form-control form-control-custom"
                    placeholder="請輸入 6 位數驗證碼"
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
                {isSubmitting ? "驗證中..." : "驗證"}
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
