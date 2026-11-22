import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { translateInterfaceText, useLanguage } from "../../context/LanguageContext";
import { apiUrl } from "../../lib/api";
import GoogleSignInButton from "../../components/feature/GoogleSignInButton";
import conqightLogo from "../../assets/conqight-logo.png";
import "./auth.css";

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { language } = useLanguage();
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [googleAvailable, setGoogleAvailable] = useState(true);
  const [lockSeconds, setLockSeconds] = useState(0); // 冷卻剩餘秒數（即時倒數）
  const [alertModal, setAlertModal] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // 冷卻倒數：每秒減 1，歸零時清除錯誤訊息
  useEffect(() => {
    if (lockSeconds <= 0) return undefined;
    const timer = setTimeout(() => {
      setLockSeconds(lockSeconds - 1);
      if (lockSeconds <= 1) setLoginError("");
    }, 1000);
    return () => clearTimeout(timer);
  }, [lockSeconds]);

  useEffect(() => {
    const clearFields = () => {
      setEmail("");
      setPassword("");
    };
    clearFields();
    const timer = window.setTimeout(clearFields, 200);
    return () => window.clearTimeout(timer);
  }, []);

  const isTwoFactorRequired = (data) =>
    Boolean(
      data.two_factor_enabled ||
      data.twoFactorEnabled ||
      data.requires_2fa ||
      data.require_2fa ||
      data.requiresTwoFactor
    );

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoginError("");

    if (isSubmitting) return;

    if (!email.trim()) {
      setAlertModal({ title: "登入失敗", message: "請輸入電子郵件。" });
      return;
    }

    if (!email.includes("@")) {
      setAlertModal({ title: "登入失敗", message: `請在電子郵件地址中包含「@」。「${email}」未包含「@」。` });
      return;
    }

    if (!password) {
      setAlertModal({ title: "登入失敗", message: "請輸入密碼。" });
      return;
    }

    try {
      setIsSubmitting(true);
      sessionStorage.setItem("dataanalysis_login_loading", "1");
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const res = await fetch(apiUrl("/api/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();
      if (!res.ok) {
        setIsSubmitting(false);
        sessionStorage.removeItem("dataanalysis_login_loading");

        if (data.require_password_reset) {
          const targetEmail = data.email || email;
          window.location.assign(`/forgot-password?email=${encodeURIComponent(targetEmail)}`);
          return;
        }

        if (res.status === 429 && Number(data.retry_after) > 0) {
          setLockSeconds(Math.ceil(Number(data.retry_after)));
        }
        setLoginError(data.error || "登入失敗，請確認帳號或密碼是否正確。");
        return;
      }

      const userData = {
        name: data.user_name || data.admin_name,
        user_name: data.user_name,
        admin_name: data.admin_name,
        email: data.email,
        user_id: data.user_id,
        admin_id: data.admin_id,
        account_type: data.account_type,
        token: data.token,
        pre_auth_token: data.pre_auth_token,
        email_2fa_enabled: data.email_2fa_enabled,
      };

      if (isTwoFactorRequired(data)) {
        sessionStorage.setItem("dataanalysis_pending_2fa", JSON.stringify(userData));
        sessionStorage.removeItem("dataanalysis_login_loading");
        navigate("/login/two-factor");
        return;
      }

      login(userData);
      navigate(userData.account_type === "admin" ? "/admin/ai" : "/workspace");
    } catch (err) {
      setIsSubmitting(false);
      sessionStorage.removeItem("dataanalysis_login_loading");
      setLoginError("連線失敗，請確認後端服務是否正常。");
      console.error(err);
    }
  };

  // Google 登入：只接受已在個人資料頁綁定的 Google 帳號，不需 Email 驗證碼
  const handleGoogleCredential = async (credential) => {
    if (!credential || isSubmitting || lockSeconds > 0) return;
    setLoginError("");
    try {
      setIsSubmitting(true);
      const res = await fetch(apiUrl("/api/auth/google/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential }),
      });
      const data = await res.json().catch(() => ({}));
      setIsSubmitting(false);
      if (!res.ok) {
        if (res.status === 429 && Number(data.retry_after) > 0) setLockSeconds(Math.ceil(Number(data.retry_after)));
        setLoginError(data.error || "Google 登入失敗，請再試一次。");
        return;
      }
      login({
        name: data.user_name,
        user_name: data.user_name,
        email: data.email,
        user_id: data.user_id,
        account_type: data.account_type,
        token: data.token,
        email_2fa_enabled: data.email_2fa_enabled,
      });
      navigate("/workspace");
    } catch {
      setIsSubmitting(false);
      setLoginError("連線失敗，請確認後端服務是否正常。");
    }
  };

  return (
    <div className="auth-page auth-page-without-navbar">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-login">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src={conqightLogo}
                alt="CON QIGHT"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">歡迎回來</h2>
            <p className="auth-visual-desc">
              <span>回到您的分析工作區</span>
              <span>快速整理資料並取得洞察</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-upload-cloud-2-line", text: "支援多種資料格式" },
                { icon: "ri-brain-line", text: "AI 智能分析" },
                { icon: "ri-folder-chart-line", text: "專案管理隨時回顧" },
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
          <button className="back-home-btn" onClick={() => navigate("/")}>
            <div className="back-home-icon">
              <i className="ri-arrow-left-line"></i>
            </div>
            <span>返回首頁</span>
          </button>

          <div className="auth-form-wrapper">
            <div className="d-lg-none text-center mb-4">
              <div className="mobile-logo">
                <img src={conqightLogo} alt="CON QIGHT" />
              </div>
              <span className="mobile-logo-text">DataAnalysis</span>
            </div>

            <h1 className="auth-title">登入帳號</h1>
            <p className="auth-subtitle">
              還沒有帳號？{" "}
              <a className="auth-link" onClick={() => navigate("/signup")} style={{ cursor: "pointer" }}>
                立即註冊
              </a>
            </p>

            <form onSubmit={handleSubmit} className="auth-form" autoComplete="off" noValidate>
              <div className="mb-3">
                <label className="auth-label">電子郵件</label>
                <div className="position-relative">
                  <i className="ri-mail-line form-icon"></i>
                  <input
                    type="email"
                    name="login_email"
                    autoComplete="off"
                    required
                    className="form-control form-control-custom"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setLoginError("");
                    }}
                  />
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">密碼</label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    name="login_password"
                    autoComplete="new-password"
                    required
                    className="form-control form-control-custom pe-5"
                    placeholder="請輸入密碼"
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      setLoginError("");
                    }}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    <i className={showPassword ? "ri-eye-off-line" : "ri-eye-line"}></i>
                  </button>
                </div>
              </div>

              <div className="d-flex justify-content-end mb-3">
                <a className="forgot-link" onClick={() => navigate("/forgot-password")} style={{ cursor: "pointer" }}>
                  忘記密碼？
                </a>
              </div>

              {loginError && (
                <div className="auth-error-message" role="alert" data-localized>
                  <i className="ri-error-warning-line"></i>
                  <span>
                    {lockSeconds > 0
                      ? translateInterfaceText(`嘗試次數過多，請於 ${String(Math.floor(lockSeconds / 60)).padStart(2, "0")}:${String(lockSeconds % 60).padStart(2, "0")} 後再試`, language)
                      : translateInterfaceText(loginError, language)}
                  </span>
                </div>
              )}

              <button type="submit" className="btn btn-auth-submit w-100" disabled={isSubmitting || lockSeconds > 0}>
                {isSubmitting ? "登入中..." : "登入"}
              </button>
            </form>

            {googleAvailable && (
              <div className="mt-3">
                <div className="d-flex align-items-center gap-2 my-3" style={{ color: "#999", fontSize: 13 }}>
                  <hr className="flex-grow-1 m-0" /><span>{language === "en" ? "or" : "或"}</span><hr className="flex-grow-1 m-0" />
                </div>
                <GoogleSignInButton
                  onCredential={handleGoogleCredential}
                  disabled={isSubmitting || lockSeconds > 0}
                  onUnavailable={() => setGoogleAvailable(false)}
                />
                <p className="text-center mt-2 mb-0" style={{ fontSize: 12, color: "#888" }}>
                  {language === "en"
                    ? "For accounts created with Google, or password accounts you linked in Profile."
                    : "適用於用 Google 註冊的帳號，或已在個人資料頁綁定 Google 的帳號。"}
                </p>
              </div>
            )}

            <p className="auth-terms text-center mt-4" data-localized>
              {language === "en" ? "By logging in, you agree to our " : "登入即表示您同意我們的 "}
              <a href="#" rel="nofollow">{language === "en" ? "Terms of Service" : "服務條款"}</a>
              {language === "en" ? " and " : " 與 "}
              <a href="#" rel="nofollow">{language === "en" ? "Privacy Policy" : "隱私政策"}</a>
              {language === "en" ? "." : "。"}
            </p>
          </div>
        </div>
      </div>
      {alertModal && (
        <div className="auth-modal-backdrop" onClick={() => setAlertModal(null)}>
          <div className="auth-alert-modal error" onClick={(event) => event.stopPropagation()}>
            <div className="auth-alert-icon">
              <i className="ri-error-warning-line"></i>
            </div>
            <div className="auth-alert-content">
              <h3>{alertModal.title}</h3>
              <p>{alertModal.message}</p>
            </div>
            <button className="auth-alert-primary" onClick={() => setAlertModal(null)} type="button">
              確定
            </button>
          </div>
        </div>
      )}
      {isSubmitting && (
        <div className="auth-loading-backdrop" role="status" aria-live="polite">
          <div className="auth-loading-card">
            <div className="auth-loading-icon">
              <i className="ri-loader-4-line"></i>
            </div>
            <h2>正在登入帳號...</h2>
            <p>正在確認您的帳號資料，請稍候。</p>
          </div>
        </div>
      )}
    </div>
  );
}
