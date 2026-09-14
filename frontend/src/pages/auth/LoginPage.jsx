import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";
import conqightLogo from "../../assets/conqight-logo.png";
import "./auth.css";

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [alertModal, setAlertModal] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

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
      setAlertModal({ title: "Login failed", message: "Please enter your email address." });
      return;
    }

    if (!email.includes("@")) {
      setAlertModal({ title: "Login failed", message: `Please include an @ in the email address. The address ${email} does not contain an @.` });
      return;
    }

    if (!password) {
      setAlertModal({ title: "Login failed", message: "Please enter your password." });
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

        setLoginError(data.error || "Login failed. Please check your email and password.");
        return;
      }

      const userData = {
        name: data.user_name,
        user_name: data.user_name,
        email: data.email,
        user_id: data.user_id,
        role: data.role,
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
      navigate("/workspace");
    } catch (err) {
      setIsSubmitting(false);
      sessionStorage.removeItem("dataanalysis_login_loading");
      setLoginError("Connection failed. Please check that the server is available.");
      console.error(err);
    }
  };

  return (
    <div className="auth-page">
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
            <h2 className="auth-visual-title">Welcome back</h2>
            <p className="auth-visual-desc">
              <span>Return to your analysis workspace</span>
              <span>Organize data and gain insights faster</span>
            </p>
            <div className="auth-features">
              {[
                { icon: "ri-upload-cloud-2-line", text: "Multiple data formats supported" },
                { icon: "ri-brain-line", text: "Intelligent AI analysis" },
                { icon: "ri-folder-chart-line", text: "Review projects anytime" },
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
            <span>Back to home</span>
          </button>

          <div className="auth-form-wrapper">
            <div className="d-lg-none text-center mb-4">
              <div className="mobile-logo">
                <img src={conqightLogo} alt="CON QIGHT" />
              </div>
              <span className="mobile-logo-text">DataAnalysis</span>
            </div>

            <h1 className="auth-title">Log in</h1>
            <p className="auth-subtitle">
              Don't have an account?{" "}
              <a className="auth-link" onClick={() => navigate("/signup")} style={{ cursor: "pointer" }}>
                Sign up now
              </a>
            </p>

            <form onSubmit={handleSubmit} className="auth-form" autoComplete="off" noValidate>
              <div className="mb-3">
                <label className="auth-label">Email</label>
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
                <label className="auth-label">Password</label>
                <div className="position-relative">
                  <i className="ri-lock-line form-icon"></i>
                  <input
                    type={showPassword ? "text" : "password"}
                    name="login_password"
                    autoComplete="new-password"
                    required
                    className="form-control form-control-custom pe-5"
                    placeholder="Please enter your password"
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
                  Forgot password?
                </a>
              </div>

              {loginError && (
                <div className="auth-error-message" role="alert">
                  <i className="ri-error-warning-line"></i>
                  <span>{loginError}</span>
                </div>
              )}

              <button type="submit" className="btn btn-auth-submit w-100" disabled={isSubmitting}>
                {isSubmitting ? "Logging in…" : "Log in"}
              </button>
            </form>

            <p className="auth-terms text-center mt-4">
              By logging in, you agree to our{" "}
              <a href="#" rel="nofollow">Terms of Service</a> and{" "}
              <a href="#" rel="nofollow">Privacy Policy</a>
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
              OK
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
            <h2>Signing you in…</h2>
            <p>Verifying your account, please wait.</p>
          </div>
        </div>
      )}
    </div>
  );
}
