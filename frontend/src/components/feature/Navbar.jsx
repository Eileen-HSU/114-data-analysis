import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import conqightLogo from "../../assets/conqight-logo.png";
import { useLanguage } from "../../context/LanguageContext";

const DEFAULT_AVATAR = "https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/b181cfaad2165c1909b7c8fa8339cbe7.png";

export default function Navbar({ transparent = false, readOnly = false, onRequireLogin }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { isLoggedIn, user, logout } = useAuth();
  const { t } = useLanguage();
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
      className={`navbar navbar-expand-lg fixed-top ${readOnly ? "navbar-shared" : ""} ${isTransparentMode ? "navbar-transparent" : "navbar-white"}`}
      style={navStyle}
    >
      <div className="container-fluid px-4" style={{ position: "relative" }}>
        {/* Left */}
        <div className="d-flex align-items-center gap-2 me-auto">
          <a
            className={`nav-link-btn ${location.pathname === "/collection" ? "active" : ""}`}
            href="/collection"
            onClick={(event) => { event.preventDefault(); if (readOnly && !isLoggedIn) onRequireLogin?.("Project management"); else navigate("/collection"); }}
            style={{ cursor: "pointer" }}
          >
            <i className="ri-folder-chart-line"></i>
            <span>{t("project")}</span>
          </a>
          <a
            className={`nav-link-btn ${(readOnly || location.pathname === "/workspace") ? "active" : ""}`}
            href="/workspace"
            onClick={(event) => { event.preventDefault(); if (readOnly && !isLoggedIn) onRequireLogin?.("New conversation"); else navigate("/workspace"); }}
            style={{ cursor: "pointer" }}
          >
            <i className="ri-add-circle-line"></i>
            <span>{t("assistant")}</span>
          </a>
          <a
            className={`nav-link-btn ${location.pathname.startsWith("/survey") ? "active" : ""}`}
            href="/survey"
            onClick={(event) => { event.preventDefault(); navigate("/survey"); }}
            style={{ cursor: "pointer" }}
          >
            <i className="ri-survey-line"></i>
            <span>{t("survey")}</span>
          </a>
          {user?.role === "admin" && (
            <a
              className={`nav-link-btn ${location.pathname.startsWith("/admin/ai") ? "active" : ""}`}
              href="/admin/ai"
              onClick={(event) => { event.preventDefault(); navigate("/admin/ai"); }}
              style={{ cursor: "pointer" }}
            >
              <i className="ri-shield-star-line"></i>
              <span>AI Administration</span>
            </a>
          )}
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
                    alt={t("nav.profile")}
                    style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "50%" }}
                  />
                </div>
                <span className="nav-user-name">{user?.name || "User"}</span>
                <i className="ri-arrow-down-s-line" style={{ fontSize: 14 }}></i>
              </button>
              {showUserMenu && (
                <div className="nav-user-dropdown">
                  <a className="dropdown-item" href="/profile" onMouseDown={(event) => { event.preventDefault(); event.stopPropagation(); setShowUserMenu(false); navigate("/profile"); window.setTimeout(() => { if (window.location.pathname !== "/profile") window.location.assign("/profile"); }, 0); }} onClick={(event) => { event.preventDefault(); event.stopPropagation(); setShowUserMenu(false); navigate("/profile"); }} style={{ cursor: "pointer" }}>
                    <i className="ri-user-settings-line me-2"></i>{t("nav.profile")}
                  </a>
                  <div className="dropdown-divider"></div>
                  <a className="dropdown-item text-danger" href="/" onMouseDown={(event) => { event.preventDefault(); event.stopPropagation(); logout(); setShowUserMenu(false); navigate("/"); }} onClick={(event) => { event.preventDefault(); event.stopPropagation(); logout(); setShowUserMenu(false); navigate("/"); }} style={{ cursor: "pointer" }}>
                    <i className="ri-logout-box-r-line me-2"></i>{t("nav.logout")}
                  </a>
                </div>
              )}
            </div>
          ) : (
            <>
              <a className="nav-login-btn" href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }} style={{ cursor: "pointer" }}>
                {t("login")}
              </a>
              <a className="nav-signup-btn" href="/signup" onClick={(event) => { event.preventDefault(); navigate("/signup"); }} style={{ cursor: "pointer" }}>
                {t("signup")}
              </a>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
