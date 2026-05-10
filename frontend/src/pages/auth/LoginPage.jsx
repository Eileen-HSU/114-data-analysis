import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import "./auth.css";

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = async (e) => {
  e.preventDefault();

  try {
    const res = await fetch("https://one14-data-analysis.onrender.com", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email,
        password: password,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      alert(data.error || "登入失敗");
      return;
    }

    // 登入成功
    login({ name: data.user_name, email: data.email, user_id: data.user_id });
    navigate("/workspace");

  } catch (err) {
    alert("無法連線至伺服器，請確認後端是否啟動");
    console.error(err);
  }
};

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* Left Visual */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">歡迎回來</h2>
            <p className="auth-visual-desc">
              繼續您的資料分析旅程。您的作品集與工作區正在等待您。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-upload-cloud-2-line", text: "支援 CSV、Excel、JSON 等多種格式" },
                { icon: "ri-brain-line", text: "AI 智能分析，自然語言提問" },
                { icon: "ri-folder-chart-line", text: "作品集管理，隨時回顧歷史分析" },
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
            {/* Mobile Logo */}
            <div className="d-lg-none text-center mb-4">
              <div className="mobile-logo">
                <i className="ri-bar-chart-box-line"></i>
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

            <form onSubmit={handleSubmit} className="auth-form">
              <div className="mb-3">
                <label className="auth-label">電子郵件</label>
                <div className="position-relative">
                  <i className="ri-mail-line form-icon"></i>
                  <input
                    type="email"
                    required
                    className="form-control form-control-custom"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">密碼</label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    className="form-control form-control-custom pe-5"
                    placeholder="請輸入密碼"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
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

              <button type="submit" className="btn btn-auth-submit w-100">
                登入
              </button>
            </form>

            <p className="auth-terms text-center mt-4">
              登入即表示您同意我們的{" "}
              <a href="#" rel="nofollow">服務條款</a> 與{" "}
              <a href="#" rel="nofollow">隱私政策</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
