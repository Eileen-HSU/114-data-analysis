import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { apiUrl } from "../../lib/api";
import "./auth.css";

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  
  // 1. 從 URL 獲取資訊：email 與來源標記 (from)
  const email = useMemo(() => searchParams.get("email") || "", [searchParams]);
  const from = useMemo(() => searchParams.get("from") || "change", [searchParams]);

  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmedOtp = otp.trim();

    // 基礎前端驗證
    if (!email) {
      setError("缺少電子郵件資訊，請重新從信箱連結進入。");
      return;
    }
    if (!/^\d{6}$/.test(trimmedOtp)) {
      setError("請輸入正確的 6 位數驗證碼。");
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
      // 呼叫後端重設密碼 API
      await axios.post(apiUrl("/api/auth/reset-password"), {
        email,
        otp: trimmedOtp,
        new_password: newPassword,
      });

      // --- 分流跳轉邏輯 ---
      if (from === "forgot") {
        // 情況 A：從「忘記密碼」進來 -> 提示成功並要求重新登入
        alert("密碼重設成功！請使用新密碼重新登入。");
        navigate("/login", { replace: true });
      } else {
        // 情況 B：從「修改密碼」進來 (或是預設情況) -> 回到個人資料並顯示通知
        navigate("/profile?password_changed=1", { replace: true });
      }
      
    } catch (err) {
      // 處理後端回傳的錯誤 (如：驗證碼錯誤、過期等)
      setError(err.response?.data?.error || "密碼重設失敗，請檢查驗證碼或稍後再試。");
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
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">
              {from === "forgot" ? "重設您的密碼" : "設定新密碼"}
            </h2>
            <p className="auth-visual-desc">
              請輸入發送到信箱的驗證碼，設定完成後您就能繼續進行資料分析。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-key-2-line", text: "驗證碼 10 分鐘內有效" },
                { icon: "ri-lock-star-line", text: "新密碼需至少 6 個字元" },
                { icon: "ri-shield-check-line", text: from === "forgot" ? "完成後請重新登入" : "完成後回到個人資料" },
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
          <button className="back-home-btn" onClick={() => navigate(from === "forgot" ? "/forgot-password" : "/change-password")}>
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>重新發送</span>
          </button>

          <div className="auth-form-wrapper">
            <div className="forgot-icon-wrap">
              <i className="ri-lock-unlock-line"></i>
            </div>
            <h1 className="auth-title">
              {from === "forgot" ? "重新設定密碼" : "變更您的密碼"}
            </h1>
            <p className="auth-subtitle" style={{ marginBottom: 28 }}>
              正在為 <strong>{email || "您的電子郵件"}</strong> 設定新密碼
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
                <label className="auth-label">設定新密碼</label>
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

              <div className="mb-4">
                <label className="auth-label">再次確認新密碼</label>
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
                {isSubmitting ? "設定中..." : "確定修改並進入系統"}
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
