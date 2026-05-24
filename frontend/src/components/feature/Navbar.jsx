import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import conqightLogo from "../../assets/conqight-logo.svg";

const DEFAULT_AVATAR = "https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/b181cfaad2165c1909b7c8fa8339cbe7.png";

export default function Navbar({ transparent = false }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { isLoggedIn, user, logout } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  useEffect(() => {
    if (!transparent) return;
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, [transparent]);

  const navStyle =
    transparent && !scrolled
      ? { background: "transparent", borderBottom: "1px solid transparent" }
      : { background: "rgba(255,255,255,0.97)", borderBottom: "1px solid var(--slate-100)", backdropFilter: "blur(10px)" };

  const isTransparentMode = transparent && !scrolled;

  return (
    <nav
      id="mainNavbar"
      className={`navbar navbar-expand-lg fixed-top ${isTransparentMode ? "navbar-transparent" : "navbar-white"}`}
      style={navStyle}
    >
      <div className="container-fluid px-4" style={{ position: "relative" }}>
        {/* Left */}
        <div className="d-flex align-items-center gap-2 me-auto">
          <a
            className={`nav-link-btn ${location.pathname === "/collection" ? "active" : ""}`}
            onClick={() => navigate("/collection")}
            style={{ cursor: "pointer" }}
          >
            <i className="ri-folder-chart-line"></i>
            <span>我的作品集</span>
          </a>
          <a
            className={`nav-link-btn ${location.pathname === "/workspace" ? "active" : ""}`}
            onClick={() => navigate("/workspace")}
            style={{ cursor: "pointer" }}
          >
            <i className="ri-add-circle-line"></i>
            <span>分析助理</span>
          </a>
          <a
            className={`nav-link-btn ${location.pathname.startsWith("/survey") ? "active" : ""}`}
            onClick={() => navigate("/survey")}
            style={{ cursor: "pointer" }}
          >
            <i className="ri-survey-line"></i>
            <span>問卷調查</span>
          </a>
        </div>

        {/* Center Logo */}
        <a
          className="navbar-brand d-flex align-items-center"
          onClick={() => navigate(isLoggedIn ? "/workspace" : "/")}
          style={{
            cursor: "pointer",
            textDecoration: "none",
            position: "absolute",
            left: "50%",
            transform: "translateX(-50%)",
          }}
        >
          <img
            src={conqightLogo}
            alt="CON QIGHT Logo"
            className="navbar-logo-img"
          />
        </a>

        {/* Right */}
        <div className="d-flex align-items-center gap-2 ms-auto">
          {isLoggedIn ? (
            <div className="position-relative">
              <button
                className="nav-user-btn"
                onClick={() => setShowUserMenu(!showUserMenu)}
                style={{ cursor: "pointer" }}
              >
                <div className="nav-user-avatar" style={{ overflow: "hidden", background: "transparent", padding: 0 }}>
                  <img
                    src={user?.avatar || DEFAULT_AVATAR}
                    alt="頭像"
                    style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "50%" }}
                  />
                </div>
                <span className="nav-user-name">{user?.name || "使用者"}</span>
                <i className="ri-arrow-down-s-line" style={{ fontSize: 14 }}></i>
              </button>
              {showUserMenu && (
                <div className="nav-user-dropdown">
                  <a className="dropdown-item" onClick={() => { setShowUserMenu(false); navigate("/profile"); }} style={{ cursor: "pointer" }}>
                    <i className="ri-user-settings-line me-2"></i>個人資料
                  </a>
                  <div className="dropdown-divider"></div>
                  <a className="dropdown-item text-danger" onClick={() => { logout(); setShowUserMenu(false); navigate("/"); }} style={{ cursor: "pointer" }}>
                    <i className="ri-logout-box-r-line me-2"></i>登出
                  </a>
                </div>
              )}
            </div>
          ) : (
            <>
              <a className="nav-login-btn" onClick={() => navigate("/login")} style={{ cursor: "pointer" }}>
                登入
              </a>
              <a className="nav-signup-btn" onClick={() => navigate("/signup")} style={{ cursor: "pointer" }}>
                註冊
              </a>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
