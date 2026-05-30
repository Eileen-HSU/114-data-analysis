import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";
import conqightLogo from "../../assets/conqight-logo.png";
import "./auth.css";

export default function SignUpPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");
  const [gender, setGender] = useState("");
  const [isGenderOpen, setIsGenderOpen] = useState(false);
  const [alertModal, setAlertModal] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const genderOptions = [
    { value: "男", label: "男", emoji: "👨" },
    { value: "女", label: "女", emoji: "👩" },
    { value: "其他", label: "其他", emoji: "✨" },
    { value: "不願透露", label: "不願透露", emoji: "🤍" },
  ];
  const selectedGenderLabel =
    genderOptions.find((option) => option.value === gender)?.label || "請選擇性別";

  const isTwoFactorRequired = (data) =>
    Boolean(
      data.two_factor_enabled ||
      data.twoFactorEnabled ||
      data.requires_2fa ||
      data.require_2fa ||
      data.requiresTwoFactor
    );

  useEffect(() => {
    const clearFields = () => {
      setName("");
      setEmail("");
      setPassword("");
      setConfirmPassword("");
      setPhone("");
      setCompany("");
      setGender("");
    };
    clearFields();
    const timer = window.setTimeout(clearFields, 200);
    return () => window.clearTimeout(timer);
  }, []);

const handleSubmit = async (e) => {
    e.preventDefault();

    if (isSubmitting) return;

    if (!gender) {
      setAlertModal({
        type: "error",
        title: "請選擇性別",
        message: "請先選擇性別後再建立帳號。",
      });
      return;
    }
    
    try {
      setIsSubmitting(true);
      // 將所有數據包裹在一個物件中作為 axios.post 的第二個參數
      const response = await axios.post(apiUrl("/api/register"), {
        user_name: name,      // 對標後端 User 模型的名稱欄位
        email: email,         // 對標 Email 欄位
        password: password,   // 對標密碼欄位（後端會再加密）
        phone_number: phone,  
        gender: gender,       
        company_name: company 
      });

      console.log("註冊成功:", response.data);
      sessionStorage.setItem("dataanalysis_login_loading", "1");
      await new Promise((resolve) => requestAnimationFrame(resolve));

      let loginData = response.data;
      if (!loginData?.token) {
        const loginResponse = await axios.post(apiUrl("/api/login"), {
          email,
          password,
        });
        loginData = loginResponse.data;
      }
      const userData = {
        name: loginData.user_name,
        user_name: loginData.user_name,
        email: loginData.email || email,
        user_id: loginData.user_id,
        token: loginData.token,
        pre_auth_token: loginData.pre_auth_token,
      };

      if (isTwoFactorRequired(loginData)) {
        sessionStorage.setItem("dataanalysis_pending_2fa", JSON.stringify(userData));
        sessionStorage.removeItem("dataanalysis_login_loading");
        navigate("/login/two-factor");
        return;
      }

      login(userData);
      navigate("/workspace", { replace: true });
    } catch (error) {
      setIsSubmitting(false);
      sessionStorage.removeItem("dataanalysis_login_loading");
      console.error("註冊失敗:", error);
      setAlertModal({
        type: "error",
        title: "註冊失敗",
        message: error.response?.data?.error || "註冊失敗，請檢查資料",
      });
    }
  }; // <--- 你之前漏掉的這個括號，就是紅屏報錯的元兇

  const closeAlertModal = () => {
    const onConfirm = alertModal?.onConfirm;
    setAlertModal(null);
    if (onConfirm) onConfirm();
  };

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* Left Visual */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-signup">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src={conqightLogo}
                alt="CON QIGHT"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">開始您的分析旅程</h2>
            <p className="auth-visual-desc">
              <span>建立帳號</span>
              <span>立即體驗 AI 驅動的資料分析</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-rocket-line", text: "快速上手" },
                { icon: "ri-brain-line", text: "自然語言提問" },
                { icon: "ri-shield-check-line", text: "安全保護您的資料" },
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

        {/* Right Form */}
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

            <h1 className="auth-title">建立帳號</h1>
            <p className="auth-subtitle">
              已有帳號？{" "}
              <a className="auth-link" onClick={() => navigate("/login")} style={{ cursor: "pointer" }}>
                立即登入
              </a>
            </p>

            <form onSubmit={handleSubmit} autoComplete="off">
              <div className="row g-3 mb-3">
                <div className="col-md-6">
                  <label className="auth-label">姓名<span className="required-mark">*</span></label>
                  <div className="position-relative">
                    <i className="ri-user-line form-icon"></i>
                    <input type="text" name="signup_name" autoComplete="off" required className="form-control form-control-custom" placeholder="您的姓名" value={name} onChange={(e) => setName(e.target.value)} />
                  </div>
                </div>
                <div className="col-md-6">
                  <label className="auth-label">手機號碼<span className="required-mark">*</span></label>
                  <div className="position-relative">
                    <i className="ri-smartphone-line form-icon"></i>
                    <input type="tel" name="signup_phone" autoComplete="off" required className="form-control form-control-custom" placeholder="+886 912 345 678" value={phone} onChange={(e) => setPhone(e.target.value)} />
                  </div>
                </div>
              </div>

              <div className="row g-3 mb-3">
                <div className="col-md-6">
                  <label className="auth-label">公司 / 機構<span className="required-mark">*</span></label>
                  <div className="position-relative">
                    <i className="ri-building-line form-icon"></i>
                    <input type="text" name="signup_company" autoComplete="off" required className="form-control form-control-custom" placeholder="您的公司名稱" value={company} onChange={(e) => setCompany(e.target.value)} />
                  </div>
                </div>
                <div className="col-md-6">
                  <label className="auth-label">性別<span className="required-mark">*</span></label>
                  <div className="position-relative">
                    <i className="ri-user-heart-line form-icon"></i>
                    <div className={`auth-select ${isGenderOpen ? "open" : ""}`}>
                      <button
                        type="button"
                        className={`form-control form-control-custom auth-select-trigger ${gender ? "" : "is-placeholder"}`}
                        aria-haspopup="listbox"
                        aria-expanded={isGenderOpen}
                        onClick={() => setIsGenderOpen((open) => !open)}
                        onBlur={(event) => {
                          if (!event.currentTarget.parentElement?.contains(event.relatedTarget)) {
                            setIsGenderOpen(false);
                          }
                        }}
                      >
                        <span>{selectedGenderLabel}</span>
                        <i className="ri-arrow-down-s-line auth-select-chevron"></i>
                      </button>
                      {isGenderOpen && (
                        <div className="auth-select-menu" role="listbox">
                          {genderOptions.map((option) => (
                            <button
                              type="button"
                              key={option.value}
                              role="option"
                              aria-selected={gender === option.value}
                              className={`auth-select-option ${gender === option.value ? "selected" : ""}`}
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={() => {
                                setGender(option.value);
                                setIsGenderOpen(false);
                              }}
                            >
                              <span>{option.label}</span>
                              <span className="auth-select-emoji" aria-hidden="true">{option.emoji}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">電子郵件<span className="required-mark">*</span></label>
                <div className="position-relative">
                  <i className="ri-mail-line form-icon"></i>
                  <input type="email" name="signup_email" autoComplete="off" required className="form-control form-control-custom" placeholder="your@email.com" value={email} onChange={(e) => setEmail(e.target.value)} />
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">密碼<span className="required-mark">*</span></label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    name="signup_password"
                    autoComplete="new-password"
                    required
                    className="form-control form-control-custom pe-5"
                    placeholder="至少 8 個字元"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button type="button" className="password-toggle" onClick={() => setShowPassword(!showPassword)}>
                    <i className={showPassword ? "ri-eye-off-line" : "ri-eye-line"}></i>
                  </button>
                </div>
                <p className="password-requirement-note">!密碼需有一個字元為大寫，要英文及數字總共8位元!</p>
              </div>

              <div className="mb-4">
                <label className="auth-label">確認密碼<span className="required-mark">*</span></label>
                <div className="position-relative">
                  <i className="ri-lock-2-line form-icon"></i>
                  <input
                    type={showConfirm ? "text" : "password"}
                    name="signup_confirm_password"
                    autoComplete="new-password"
                    required
                    className="form-control form-control-custom pe-5"
                    placeholder="再次輸入密碼"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                  />
                  <button type="button" className="password-toggle" onClick={() => setShowConfirm(!showConfirm)}>
                    <i className={showConfirm ? "ri-eye-off-line" : "ri-eye-line"}></i>
                  </button>
                </div>
              </div>

              <button type="submit" className="btn btn-auth-submit w-100" disabled={isSubmitting}>
                {isSubmitting ? "建立並登入中..." : "建立帳號"}
              </button>
            </form>

            <p className="auth-terms text-center mt-4">
              註冊即表示您同意我們的{" "}
              <a href="#" rel="nofollow">服務條款</a> 與{" "}
              <a href="#" rel="nofollow">隱私政策</a>
            </p>
          </div>
        </div>
      </div>

      {alertModal && (
        <div className="auth-modal-backdrop" onClick={closeAlertModal}>
          <div className={`auth-alert-modal ${alertModal.type}`} role="alertdialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className="auth-alert-icon">
              <i className={alertModal.type === "success" ? "ri-check-line" : "ri-error-warning-line"}></i>
            </div>
            <div className="auth-alert-content">
              <h3>{alertModal.title}</h3>
              <p>{alertModal.message}</p>
            </div>
            <button className="auth-alert-primary" type="button" onClick={closeAlertModal}>
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
            <h2>正在建立帳號...</h2>
            <p>註冊完成後會直接登入並進入系統，請稍候。</p>
          </div>
        </div>
      )}
    </div>
  );
}
