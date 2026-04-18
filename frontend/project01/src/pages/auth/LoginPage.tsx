// 登入頁面 - 亮色系
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: "", password: "" });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const ok = await login(form.email, form.password);
    setLoading(false);
    if (ok) navigate("/workspace");
    else setError("帳號或密碼錯誤，請重試。");
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-sky-50 via-white to-cyan-50 flex">
      {/* 左側視覺區 */}
      <div className="hidden lg:flex lg:w-1/2 relative flex-col items-center justify-center overflow-hidden bg-gradient-to-br from-sky-500 via-cyan-500 to-teal-500">
        {/* 背景裝飾 */}
        <div className="absolute top-0 right-0 w-80 h-80 bg-white/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-0 w-64 h-64 bg-teal-300/20 rounded-full blur-3xl pointer-events-none" />
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: "linear-gradient(white 1px, transparent 1px), linear-gradient(90deg, white 1px, transparent 1px)",
            backgroundSize: "48px 48px",
          }}
        />

        <div className="relative z-10 flex flex-col items-center px-12 text-center">
          {/* Logo */}
          <div className="mb-10 flex flex-col items-center gap-3">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 flex items-center justify-center bg-white/20 backdrop-blur-sm rounded-2xl border border-white/30">
                <i className="ri-bar-chart-box-line text-white text-2xl"></i>
              </div>
              <span className="text-3xl font-black text-white tracking-tight">DataAnalysis</span>
            </div>
            <div className="h-px w-40 bg-white/30 mt-1" />
          </div>
          <h2 className="text-3xl font-bold text-white mb-4 leading-snug">歡迎回來</h2>
          <p className="text-white/75 text-lg leading-relaxed max-w-xs">
            繼續您的資料分析旅程。您的作品集與工作區正在等待您。
          </p>

          {/* 功能亮點 */}
          <div className="mt-12 space-y-4 w-full max-w-xs text-left">
            {[
              { icon: "ri-upload-cloud-2-line", text: "支援 CSV、Excel、JSON 等多種格式" },
              { icon: "ri-brain-line", text: "AI 智能分析，自然語言提問" },
              { icon: "ri-folder-chart-line", text: "作品集管理，隨時回顧歷史分析" },
            ].map((item) => (
              <div key={item.text} className="flex items-center gap-3">
                <div className="w-9 h-9 flex items-center justify-center bg-white/15 rounded-xl flex-shrink-0">
                  <i className={`${item.icon} text-white text-base`}></i>
                </div>
                <span className="text-white/80 text-base">{item.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 右側表單 */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          {/* 手機版 Logo */}
          <div className="lg:hidden flex items-center gap-3 mb-10 justify-center">
            <div className="w-10 h-10 flex items-center justify-center bg-gradient-to-br from-sky-500 to-cyan-500 rounded-xl">
              <i className="ri-bar-chart-box-line text-white text-xl"></i>
            </div>
            <span className="text-2xl font-black text-slate-800 tracking-tight">DataAnalysis</span>
          </div>

          <h1 className="text-3xl font-black text-slate-800 mb-2">登入帳號</h1>
          <p className="text-slate-500 text-base mb-8">
            還沒有帳號？{" "}
            <Link to="/signup" className="text-sky-500 hover:text-sky-600 font-semibold cursor-pointer">
              免費註冊
            </Link>
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email */}
            <div>
              <label className="block text-sm font-semibold text-slate-600 mb-2">電子郵件</label>
              <div className="relative">
                <i className="ri-mail-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="your@email.com"
                  className="w-full pl-11 pr-4 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 placeholder-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100 transition-all"
                />
              </div>
            </div>

            {/* 密碼 */}
            <div>
              <label className="block text-sm font-semibold text-slate-600 mb-2">密碼</label>
              <div className="relative">
                <i className="ri-lock-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                <input
                  type={showPwd ? "text" : "password"}
                  required
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder="請輸入密碼"
                  className="w-full pl-11 pr-12 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 placeholder-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100 transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(!showPwd)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                >
                  <i className={showPwd ? "ri-eye-off-line text-base" : "ri-eye-line text-base"}></i>
                </button>
              </div>
            </div>

            <div className="flex justify-end">
              <Link to="/forgot-password" className="text-sm text-slate-400 hover:text-sky-500 cursor-pointer transition-colors">
                忘記密碼？
              </Link>
            </div>

            {error && (
              <div className="flex items-center gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl">
                <i className="ri-error-warning-line text-red-500 text-base"></i>
                <p className="text-red-600 text-sm">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-4 bg-gradient-to-r from-sky-500 to-cyan-500 text-white font-bold rounded-xl hover:from-sky-400 hover:to-cyan-400 transition-all text-base whitespace-nowrap cursor-pointer disabled:opacity-60"
            >
              {loading ? "登入中..." : "登入"}
            </button>
          </form>

          <p className="text-sm text-slate-400 text-center mt-8">
            登入即表示您同意我們的{" "}
            <a href="#" className="underline cursor-pointer hover:text-slate-600" rel="nofollow">服務條款</a>{" "}
            與{" "}
            <a href="#" className="underline cursor-pointer hover:text-slate-600" rel="nofollow">隱私政策</a>
          </p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
