import InterfaceText from "../../components/feature/InterfaceText";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { apiUrl } from "../../lib/api";
import { useLanguage } from "../../context/LanguageContext";
import conqightLogo from "../../assets/conqight-logo.png";
import "./auth.css";

export default function ResetPasswordPage() {
  const { language } = useLanguage();
  const localize = (zh, en) => language === "en" ? en : zh;
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
      setError(localize("缺少電子郵件資訊，請重新從信箱連結進入。", "Email information is missing. Please open the link in your email again."));
      return;
    }
    if (!/^\d{6}$/.test(trimmedOtp)) {
      setError(localize("請輸入正確的 6 位數驗證碼。", "Please enter a valid 6-digit verification code."));
      return;
    }
    if (newPassword.length < 8) {
      setError(localize("新密碼至少需要 8 個字元，並包含英文字母和數字", "Your new password must contain at least 8 characters, including letters and numbers."));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(localize("兩次輸入的新密碼不一致。", "The new passwords do not match."));
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
      setError(err.response?.data?.error || localize("密碼重設失敗，請檢查驗證碼或稍後再試。", "Password reset failed. Check your verification code or try again later."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page auth-page-without-navbar">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* 左側視覺裝飾區域 */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-reset-pw">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content" data-localized>
            <div className="auth-logo mb-5">
              <img
                src={conqightLogo}
                alt="CON QIGHT"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">
              {isForgotFlow ? localize("重設您的密碼", "Reset your password") : localize("設定新密碼", "Set a new password")}
            </h2>
            <p className="auth-visual-desc">
              <span>{isForgotFlow ? localize("輸入驗證碼", "Enter your verification code") : localize("確認您的身份", "Verify your identity")}</span>
              <span>{isForgotFlow ? localize("重新設定安全密碼", "Set a new, secure password") : localize("完成後返回個人資料", "Return to your profile when finished")}</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-key-2-line", text: localize("驗證碼 10 分鐘內有效", "Code valid for 10 minutes") },
                { icon: "ri-lock-star-line", text: localize("新密碼至少 8 個字元", "New password must be at least 8 characters") },
                { icon: "ri-shield-check-line", text: isForgotFlow ? localize("完成後請重新登入", "Log in again when finished") : localize("完成後不會登出帳號", "You will remain logged in") },
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
            <span><InterfaceText>{"重新發送"}</InterfaceText></span>
          </button>

          <div className="auth-form-wrapper">
            <div className="forgot-icon-wrap">
              <i className="ri-lock-unlock-line"></i>
            </div>
            <h1 className="auth-title" data-localized>
              {isForgotFlow ? localize("重新設定密碼", "Reset your password") : localize("變更您的密碼", "Change your password")}
            </h1>
            <p className="auth-subtitle" style={{ marginBottom: 28 }} data-localized>
              {language === "en" ? (
                <>{isForgotFlow ? "Resetting the password for " : "Changing the password for "}<strong>{email || "your email address"}</strong></>
              ) : (
                <>{isForgotFlow ? "正在重設" : "正在變更"} <strong>{email || "您的電子郵件"}</strong> 的密碼</>
              )}
            </p>

            <form onSubmit={handleSubmit} noValidate autoComplete="off">
              <div className="mb-3">
                <label className="auth-label"><InterfaceText>{"驗證碼"}</InterfaceText></label>
                <div className="position-relative">
                  <i className="ri-shield-keyhole-line form-icon"></i>
                  <input
                    type="text"
                    inputMode="numeric"
                    name="reset_verification_code"
                    autoComplete="off"
                    maxLength={6}
                    className="form-control form-control-custom"
                    placeholder="請輸入 6 位數驗證碼"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  />
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label"><InterfaceText>{"設定新密碼"}</InterfaceText></label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    name="reset_new_password"
                    autoComplete="new-password"
                    className="form-control form-control-custom pe-5"
                    data-localized
                    placeholder={localize("請輸入新密碼", "Enter your new password")}
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
                <label className="auth-label"><InterfaceText>{"再次確認新密碼"}</InterfaceText></label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    name="reset_confirm_password"
                    autoComplete="new-password"
                    className="form-control form-control-custom"
                    data-localized
                    placeholder={localize("請再次輸入新密碼", "Re-enter your new password")}
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

              <button type="submit" className="btn btn-auth-submit w-100 mt-2" disabled={isSubmitting} data-localized>
                {isSubmitting
                  ? localize("設定中...", "Saving…")
                  : isForgotFlow
                    ? localize("確定重設並返回登入", "Reset password and return to login")
                    : localize("確定修改並回個人資料", "Save password and return to profile")}
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
            <h3><InterfaceText>{"密碼重設成功"}</InterfaceText></h3>
            <p><InterfaceText>{"請使用新密碼重新登入您的帳號。"}</InterfaceText></p>
            <button type="button" className="auth-success-action" data-localized onClick={() => navigate("/login", { replace: true })}>
              {language === "en" ? "Back to login" : "回到登入頁"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
