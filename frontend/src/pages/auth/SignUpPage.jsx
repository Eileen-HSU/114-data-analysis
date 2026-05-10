import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import axios from "axios";
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

const handleSubmit = async (e) => {
    e.preventDefault();
    
    try {
      // 將所有數據包裹在一個物件中作為 axios.post 的第二個參數
      const response = await axios.post('https://one14-data-analysis-frontend.onrender.com/api/register', {
        user_name: name,      // 對標後端 User 模型的名稱欄位
        email: email,         // 對標 Email 欄位
        password: password,   // 對標密碼欄位（後端會再加密）
        phone_number: phone,  
        gender: gender,       
        company_name: company 
      });

      console.log("註冊成功:", response.data);
      alert("註冊成功！");
      navigate("/login"); // 註冊成功後自動導向登入頁
    } catch (error) {
      console.error("註冊失敗:", error);
      alert(error.response?.data?.error || "註冊失敗，請檢查資料");
    }
  }; // <--- 你之前漏掉的這個括號，就是紅屏報錯的元兇

  return (
    <div className="auth-page">
      <div className="row g-0" style={{ minHeight: "100vh" }}>
        {/* Left Visual */}
        <div className="col-lg-6 d-none d-lg-flex auth-visual auth-visual-signup">
          <div className="auth-visual-overlay"></div>
          <div className="auth-visual-content">
            <div className="auth-logo mb-5">
              <img
                src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/005555d3f7d205685c5c858369347dc5.png"
                alt="DATA analysis"
                className="auth-logo-img"
              />
            </div>
            <h2 className="auth-visual-title">開始您的分析旅程</h2>
            <p className="auth-visual-desc">
              建立帳號，立即體驗 AI 驅動的智能資料分析。
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-rocket-line", text: "快速上手，立即開始分析" },
                { icon: "ri-brain-line", text: "AI 智能分析，自然語言提問" },
                { icon: "ri-shield-check-line", text: "企業級資料安全保護" },
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
                <i className="ri-bar-chart-box-line"></i>
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

            <form onSubmit={handleSubmit}>
              <div className="row g-3 mb-3">
                <div className="col-md-6">
                  <label className="auth-label">姓名</label>
                  <div className="position-relative">
                    <i className="ri-user-line form-icon"></i>
                    <input type="text" required className="form-control form-control-custom" placeholder="您的姓名" value={name} onChange={(e) => setName(e.target.value)} />
                  </div>
                </div>
                <div className="col-md-6">
                  <label className="auth-label">手機號碼</label>
                  <div className="position-relative">
                    <i className="ri-smartphone-line form-icon"></i>
                    <input type="tel" className="form-control form-control-custom" placeholder="+886 912 345 678" value={phone} onChange={(e) => setPhone(e.target.value)} />
                  </div>
                </div>
              </div>

              <div className="row g-3 mb-3">
                <div className="col-md-6">
                  <label className="auth-label">公司 / 機構</label>
                  <div className="position-relative">
                    <i className="ri-building-line form-icon"></i>
                    <input type="text" className="form-control form-control-custom" placeholder="您的公司名稱" value={company} onChange={(e) => setCompany(e.target.value)} />
                  </div>
                </div>
                <div className="col-md-6">
                  <label className="auth-label">性別</label>
                  <div className="position-relative">
                    <i className="ri-user-heart-line form-icon"></i>
                    <select className="form-control form-control-custom" value={gender} onChange={(e) => setGender(e.target.value)} style={{ appearance: "none" }}>
                      <option value="">請選擇性別</option>
                      <option value="男">男</option>
                      <option value="女">女</option>
                      <option value="其他">其他</option>
                      <option value="不願透露">不願透露</option>
                    </select>
                  </div>
                </div>
              </div>

              <div className="mb-3">
                <label className="auth-label">電子郵件</label>
                <div className="position-relative">
                  <i className="ri-mail-line form-icon"></i>
                  <input type="email" required className="form-control form-control-custom" placeholder="your@email.com" value={email} onChange={(e) => setEmail(e.target.value)} />
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
                    placeholder="至少 8 個字元"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button type="button" className="password-toggle" onClick={() => setShowPassword(!showPassword)}>
                    <i className={showPassword ? "ri-eye-off-line" : "ri-eye-line"}></i>
                  </button>
                </div>
              </div>

              <div className="mb-4">
                <label className="auth-label">確認密碼</label>
                <div className="position-relative">
                  <i className="ri-lock-2-line form-icon"></i>
                  <input
                    type={showConfirm ? "text" : "password"}
                    required
                    className="form-control form-control-custom pe-5"
                    placeholder="再次輸入密碼"
                  />
                  <button type="button" className="password-toggle" onClick={() => setShowConfirm(!showConfirm)}>
                    <i className={showConfirm ? "ri-eye-off-line" : "ri-eye-line"}></i>
                  </button>
                </div>
              </div>

              <button type="submit" className="btn btn-auth-submit w-100">
                建立帳號
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
    </div>
  );
}
