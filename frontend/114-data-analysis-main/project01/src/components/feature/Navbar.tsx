import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useState } from "react";

const DEFAULT_AVATAR = "https://static.readdy.ai/image/9080131fd243e879b7aeaa20dae1f896/4c3cdad381172f4be4b30c4ec4f8f3c8.png";

interface NavbarProps {
  onLoginRequired?: () => void;
}

const Navbar: React.FC<NavbarProps> = ({ onLoginRequired }) => {
  const { isLoggedIn, user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const handleProtectedClick = (e: React.MouseEvent, path: string) => {
    if (!isLoggedIn) {
      e.preventDefault();
      onLoginRequired?.();
    } else {
      navigate(path);
    }
  };

  const isActive = (path: string) => location.pathname === path;

  const navLinkClass = (path: string) =>
    `flex items-center gap-2.5 px-6 py-3 rounded-xl text-base font-semibold transition-all whitespace-nowrap cursor-pointer ${
      isActive(path)
        ? "bg-violet-50 text-violet-600 border border-violet-200"
        : "text-slate-600 hover:text-violet-600 hover:bg-violet-50"
    }`;

  const avatarSrc = user?.avatar || DEFAULT_AVATAR;

  return (
    <nav className="fixed top-0 left-0 right-0 w-full bg-white border-b border-slate-100 px-8 py-0 flex items-center justify-between z-50 h-[72px]">
      {/* 左側導覽 */}
      <div className="flex items-center gap-2 flex-1">
        <button
          onClick={(e) => handleProtectedClick(e, "/collection")}
          className={navLinkClass("/collection")}
        >
          <i className="ri-folder-chart-line text-lg"></i>
          我的作品集
        </button>
        <button
          onClick={(e) => handleProtectedClick(e, "/workspace")}
          className={navLinkClass("/workspace")}
        >
          <i className="ri-add-circle-line text-lg"></i>
          新增工作區
        </button>
      </div>

      {/* 中央 Logo（絕對置中） */}
      <Link
        to="/"
        className="absolute left-1/2 -translate-x-1/2 flex items-center gap-3 group"
      >
        <div className="w-10 h-10 flex items-center justify-center bg-gradient-to-br from-violet-500 via-sky-500 to-cyan-500 rounded-xl group-hover:from-violet-400 group-hover:to-cyan-400 transition-all">
          <i className="ri-bar-chart-box-line text-white text-xl"></i>
        </div>
        <div className="flex flex-col leading-none">
          <span className="text-xl font-black text-slate-800 tracking-tight">DataAnalysis</span>
          <span className="text-[11px] bg-gradient-to-r from-violet-500 to-sky-500 bg-clip-text text-transparent tracking-widest uppercase font-semibold">智能資料分析平台</span>
        </div>
      </Link>

      {/* 右側使用者區域 */}
      <div className="flex items-center gap-3 flex-1 justify-end">
        {isLoggedIn && user ? (
          <div className="relative">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-3 px-4 py-2.5 rounded-xl hover:bg-violet-50 transition-colors cursor-pointer border border-transparent hover:border-violet-100"
            >
              <div className="w-10 h-10 flex items-center justify-center rounded-full overflow-hidden border-2 border-violet-200 bg-violet-50 flex-shrink-0">
                <img src={avatarSrc} alt={user.name} className="w-full h-full object-cover" />
              </div>
              <div className="hidden md:block text-left">
                <p className="text-base font-semibold text-slate-800 leading-none">{user.name}</p>
                <p className="text-sm text-slate-400 mt-0.5 truncate max-w-[120px]">{user.email}</p>
              </div>
              <i className={`ri-arrow-down-s-line text-slate-400 text-base transition-transform ${dropdownOpen ? "rotate-180" : ""}`}></i>
            </button>

            {dropdownOpen && (
              <div className="absolute right-0 top-16 w-56 bg-white border border-slate-100 rounded-2xl py-2 z-50 shadow-sm">
                <div className="px-5 py-3 border-b border-slate-100">
                  <p className="text-base font-semibold text-slate-800 truncate">{user.name}</p>
                  <p className="text-sm text-slate-400 truncate mt-0.5">{user.email}</p>
                </div>
                <Link
                  to="/profile"
                  onClick={() => setDropdownOpen(false)}
                  className="flex items-center gap-3 px-5 py-3 text-base text-slate-600 hover:bg-violet-50 hover:text-violet-600 cursor-pointer transition-colors"
                >
                  <i className="ri-user-line text-lg text-violet-500"></i>
                  個人資料
                </Link>
                <Link
                  to="/collection"
                  onClick={() => setDropdownOpen(false)}
                  className="flex items-center gap-3 px-5 py-3 text-base text-slate-600 hover:bg-sky-50 hover:text-sky-600 cursor-pointer transition-colors"
                >
                  <i className="ri-folder-line text-lg text-sky-500"></i>
                  我的作品集
                </Link>
                <div className="border-t border-slate-100 mt-1 pt-1">
                  <button
                    onClick={() => { logout(); setDropdownOpen(false); navigate("/"); }}
                    className="w-full flex items-center gap-3 px-5 py-3 text-base text-red-500 hover:bg-red-50 cursor-pointer transition-colors"
                  >
                    <i className="ri-logout-box-line text-lg"></i>
                    登出
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="px-5 py-2.5 text-base font-semibold text-slate-600 hover:text-violet-600 transition-colors whitespace-nowrap cursor-pointer"
            >
              登入
            </Link>
            <Link
              to="/signup"
              className="px-5 py-2.5 text-base font-bold bg-gradient-to-r from-violet-500 via-sky-500 to-cyan-500 text-white rounded-xl hover:from-violet-400 hover:to-cyan-400 transition-all whitespace-nowrap cursor-pointer"
            >
              免費註冊
            </Link>
          </div>
        )}
      </div>

      {dropdownOpen && (
        <div className="fixed inset-0 z-40" onClick={() => setDropdownOpen(false)} />
      )}
    </nav>
  );
};

export default Navbar;
