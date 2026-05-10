import { useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import "./auth.css";
import axios from "axios";

export default function ChangePasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const emailFromUrl = useMemo(() => searchParams.get("email") || "", [searchParams]);
  const emailRef = useRef(null);
  const errorRef = useRef(null);
  const submitBtnRef = useRef(null);
  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [resetError, setResetError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

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

  const handleSendOtp = async (e) => {
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
      const response = await axios.post("https://one14-data-analysis.onrender.com/api/auth/send-otp", {
        email: val,
        type: "PASSWORD_CHANGE"
      });

      if (response.status === 200) {
        navigate(`/change-password?email=${encodeURIComponent(val)}`);
      }
    } catch (error) {
      const errorMsg = error.response?.data?.error || "發送失敗，請稍後再試";
      showError(errorMsg);
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = "發送驗證碼";
      }
    }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    const trimmedOtp = otp.trim();

    if (!emailFromUrl) {
      setResetError("缺少電子郵件，請重新發送驗證碼。");
      return;
    }
    if (!/^\d{6}$/.test(trimmedOtp)) {
      setResetError("請輸入 6 位數驗證碼。");
      return;
    }
    if (newPassword.length < 6) {
      setResetError("新密碼至少需要 6 個字元。");
      return;
    }
    if (newPassword !== confirmPassword) {
      setResetError("兩次輸入的新密碼不一致。");
      return;
    }

    setResetError("");
    setIsSubmitting(true);

    try {
      await axios.post("https://one14-data-analysis.onrender.com/api/auth/reset-password", {
        email: emailFromUrl,
        otp: trimmedOtp,
        new_password: newPassword,
      });

      alert("密碼已修改成功。");
      navigate("/profile");
    } catch (error) {
      setResetError(error.response?.data?.error || "密碼修改失敗，請稍後再試。");
    } finally {
      setIsSubmitting(false);
    }
  };

  const isResetStep = Boolean(emailFromUrl);

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
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
              輸入驗證碼並設定新密碼，完成後即可繼續使用帳號。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-mail-send-line", text: "驗證碼發送至您的信箱" },
                { icon: "ri-time-line", text: "驗證碼 10 分鐘內有效" },
                { icon: "ri-shield-check-line", text: "修改完成後不需要重新登入" },
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

          <div className="auth-form-wrapper">
            <div className="d-lg-none text-center mb-4">
              <div className="mobile-logo">
                <i className="ri-bar-chart-box-line"></i>
              </div>
              <span className="mobile-logo-text">DataAnalysis</span>
            </div>

            {!isResetStep && (
              <>
                <div className="forgot-icon-wrap">
                  <i className="ri-lock-password-line"></i>
                </div>
                <h1 className="auth-title">修改密碼</h1>
                <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                  輸入您的帳號電子郵件，我們將發送密碼修改驗證碼。
                </p>

                <form onSubmit={handleSendOtp} noValidate>
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

                  <button ref={submitBtnRef} type="submit" className="btn btn-auth-submit w-100 mb-3">
                    發送驗證碼
                  </button>
                </form>
              </>
            )}

            {isResetStep && (
              <>
                <div className="forgot-icon-wrap">
                  <i className="ri-lock-unlock-line"></i>
                </div>
                <h1 className="auth-title">設定新密碼</h1>
                <p className="auth-subtitle" style={{ marginBottom: 28 }}>
                  驗證碼已寄到 {emailFromUrl}。
                </p>

                <form onSubmit={handleResetPassword} noValidate>
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

                  {resetError && (
                    <p style={{ color: "#ef4444", fontSize: 13, marginTop: 6, fontWeight: 600 }}>
                      {resetError}
                    </p>
                  )}

                  <button type="submit" className="btn btn-auth-submit w-100 mt-2" disabled={isSubmitting}>
                    {isSubmitting ? "修改中..." : "確定"}
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .auth-visual-change-pw {
          background-image: url('https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/c7324bc840efa1d4185cef328ecdebbc.png');
          background-size: cover;
          background-position: center center;
        }
      `}</style>
    </div>
  );
}
