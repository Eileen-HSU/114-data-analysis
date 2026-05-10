import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import "./auth.css";

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const email = useMemo(() => searchParams.get("email") || "", [searchParams]);
  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmedOtp = otp.trim();

    if (!email) {
      setError("缺少電子郵件，請重新發送驗證碼。");
      return;
    }
    if (!/^\d{6}$/.test(trimmedOtp)) {
      setError("請輸入 6 位數驗證碼。");
      return;
    }
    if (newPassword.length < 6) {
      setError("新密碼至少需要 6 個字元。");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("兩次輸入的新密碼不一致。");
      return;
    }

    setError("");
    setIsSubmitting(true);

    try {
      await axios.post("https://one14-data-analysis.onrender.com/api/auth/reset-password", {
        email,
        otp: trimmedOtp,
        new_password: newPassword,
      });

      alert("密碼已重新設定，請使用新密碼登入。");
      navigate("/login");
    } catch (err) {
      setError(err.response?.data?.error || "密碼重設失敗，請稍後再試。");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-reset-pw">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">設定新密碼</h2>
            <p className="auth-visual-desc">
              輸入信箱收到的驗證碼，並建立一組新的登入密碼。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-key-2-line", text: "驗證碼 10 分鐘內有效" },
                { icon: "ri-lock-password-line", text: "新密碼將立即生效" },
                { icon: "ri-shield-check-line", text: "完成後請重新登入帳號" },
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
          <button className="back-home-btn" onClick={() => navigate("/forgot-password")}>
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>重新發送</span>
          </button>

          <div className="auth-form-wrapper">
            <div className="forgot-icon-wrap">
              <i className="ri-lock-unlock-line"></i>
            </div>
            <h1 className="auth-title">重新設定密碼</h1>
            <p className="auth-subtitle" style={{ marginBottom: 28 }}>
              驗證碼已寄到 {email || "您的電子郵件"}。
            </p>

            <form onSubmit={handleSubmit} noValidate>
              <div className="mb-3">
                <label className="auth-label">驗證碼</label>
                <div className="position-relative">
                  <i className="ri-shield-keyhole-line form-icon"></i>
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    className="form-control form-control-custom"
                    placeholder="請輸入 6 位數驗證碼"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  />
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">新密碼</label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    className="form-control form-control-custom pe-5"
                    placeholder="請輸入新密碼"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    onClick={() => setShowPassword((prev) => !prev)}
                  >
                    <i className={showPassword ? "ri-eye-off-line" : "ri-eye-line"}></i>
                  </button>
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">再次輸入新密碼</label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    className="form-control form-control-custom"
                    placeholder="請再次輸入新密碼"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                  />
                </div>
              </div>

              {error && (
                <p style={{ color: "#ef4444", fontSize: 13, marginTop: 6, fontWeight: 600 }}>
                  {error}
                </p>
              )}

              <button type="submit" className="btn btn-auth-submit w-100 mt-2" disabled={isSubmitting}>
                {isSubmitting ? "設定中..." : "確定"}
              </button>
            </form>
          </div>
        </div>
      </div>

      <style>{`
        .auth-visual-reset-pw {
          background-image: url('https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/c7324bc840efa1d4185cef328ecdebbc.png');
          background-size: cover;
          background-position: center center;
        }
      `}</style>
    </div>
  );
}
