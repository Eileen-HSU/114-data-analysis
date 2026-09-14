import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { apiUrl } from "../../lib/api";
import conqightLogo from "../../assets/conqight-logo.png";
import "./auth.css";

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // 1. 從 URL 獲取資訊：email 與來源標記 (from)
  const email = useMemo(() => searchParams.get("email") || "", [searchParams]);
  const from = useMemo(() => searchParams.get("from") || "change", [searchParams]);
  const isForgotFlow = from === "forgot";

  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successModalOpen, setSuccessModalOpen] = useState(false);

  useEffect(() => {
    const clearFields = () => {
      setOtp("");
      setNewPassword("");
      setConfirmPassword("");
    };
    clearFields();
    const timer = window.setTimeout(clearFields, 200);
    return () => window.clearTimeout(timer);
  }, [email, from]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmedOtp = otp.trim();

    // 基礎前端驗證
    if (!email) {
      setError("Email information is missing. Please reopen the link in your email.");
      return;
    }
    if (!/^\d{6}$/.test(trimmedOtp)) {
      setError("Please enter a valid 6-digit verification code.");
      return;
    }
    if (newPassword.length < 8) {
      setError("Your new password must contain at least 8 characters, including letters and numbers.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("The new passwords do not match.");
      return;
    }

    setError("");
    setIsSubmitting(true);

    try {
      // 呼叫後端重設密碼 API
      await axios.post(apiUrl("/api/auth/reset-password"), {
        email,
        otp: trimmedOtp,
        new_password: newPassword,
        type: isForgotFlow ? "PASSWORD_RESET" : "PASSWORD_CHANGE",
      });

      // --- 分流跳轉邏輯 ---
      if (isForgotFlow) {
        // 情況 A：從「忘記密碼」進來 -> 提示成功並要求重新登入
        setSuccessModalOpen(true);
      } else {
        // 情況 B：從「修改密碼」進來 (或是預設情況) -> 回到個人資料並顯示通知
        navigate("/profile?password_changed=1", { replace: true });
      }

    } catch (err) {
      // 處理後端回傳的錯誤 (如：驗證碼錯誤、過期等)
      setError(err.response?.data?.error || "Password reset failed. Check your verification code or try again later.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* 左側視覺裝飾區域 */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-reset-pw">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src={conqightLogo}
                alt="CON QIGHT"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">
              {isForgotFlow ? "Reset your password" : "Set new password"}
            </h2>
            <p className="auth-visual-desc">
              <span>{isForgotFlow ? "Enter verification code" : "Verify your identity"}</span>
              <span>{isForgotFlow ? "Set a secure new password" : "Return to your profile when finished"}</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-key-2-line", text: "Code valid for 10 minutes" },
                { icon: "ri-lock-star-line", text: "Use at least 8 characters" },
                { icon: "ri-shield-check-line", text: isForgotFlow ? "Log in again when finished" : "You will remain signed in" },
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

        {/* 右側表單操作區域 */}
        <div className="col-lg-6 d-flex align-items-center justify-content-center auth-form-area">
          <button className="back-home-btn" onClick={() => navigate(isForgotFlow ? "/forgot-password" : "/change-password")}>
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>Resend</span>
          </button>

          <div className="auth-form-wrapper">
            <div className="forgot-icon-wrap">
              <i className="ri-lock-unlock-line"></i>
            </div>
            <h1 className="auth-title">
              {isForgotFlow ? "Reset password" : "Change your password"}
            </h1>
            <p className="auth-subtitle" style={{ marginBottom: 28 }}>
              {isForgotFlow ? "Resetting the password for " : "Changing the password for "} <strong>{email || "Your email"}</strong>
            </p>

            <form onSubmit={handleSubmit} noValidate autoComplete="off">
              <div className="mb-3">
                <label className="auth-label">Verification code</label>
                <div className="position-relative">
                  <i className="ri-shield-keyhole-line form-icon"></i>
                  <input
                    type="text"
                    inputMode="numeric"
                    name="reset_verification_code"
                    autoComplete="off"
                    maxLength={6}
                    className="form-control form-control-custom"
                    placeholder="Enter the 6-digit verification code"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  />
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">Set new password</label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    name="reset_new_password"
                    autoComplete="new-password"
                    className="form-control form-control-custom pe-5"
                    placeholder="Enter your new password"
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

              <div className="mb-4">
                <label className="auth-label">Confirm new password</label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    name="reset_confirm_password"
                    autoComplete="new-password"
                    className="form-control form-control-custom"
                    placeholder="Enter your new password again"
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
                {isSubmitting
                  ? "Saving..."
                  : isForgotFlow
                    ? "Reset password and return to login"
                    : "Change password and return to profile"}
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

      {successModalOpen && (
        <div className="auth-modal-backdrop">
          <div className="auth-success-modal" role="alertdialog" aria-modal="true">
            <div className="auth-success-icon">
              <i className="ri-checkbox-circle-line"></i>
            </div>
            <h3>Password reset successful</h3>
            <p>Please log in again with your new password.</p>
            <button type="button" className="auth-success-action" onClick={() => navigate("/login", { replace: true })}>
              Back to login
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
