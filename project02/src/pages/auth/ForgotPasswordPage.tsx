// 忘記密碼頁面 - 亮色系 + 中文化
import { useState } from "react";
import { Link } from "react-router-dom";

const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    await new Promise((r) => setTimeout(r, 800));
    setLoading(false);
    setSent(true);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-sky-50 via-white to-cyan-50 flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-white rounded-2xl p-10 border border-slate-100">
        {/* Logo */}
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="w-10 h-10 flex items-center justify-center bg-gradient-to-br from-sky-500 to-cyan-500 rounded-xl">
            <i className="ri-bar-chart-box-line text-white text-xl"></i>
          </div>
          <span className="text-2xl font-black text-slate-800 tracking-tight">DataAnalysis</span>
        </div>

        {!sent ? (
          <>
            <div className="w-16 h-16 flex items-center justify-center bg-sky-50 border border-sky-100 rounded-2xl mx-auto mb-5">
              <i className="ri-mail-lock-line text-3xl text-sky-500"></i>
            </div>
            <h1 className="text-2xl font-black text-slate-800 text-center mb-2">忘記密碼？</h1>
            <p className="text-slate-500 text-base text-center mb-8 leading-relaxed">
              輸入您的電子郵件地址，我們將發送重設密碼的連結給您。
            </p>
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-2">電子郵件</label>
                <div className="relative">
                  <i className="ri-mail-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="your@email.com"
                    className="w-full pl-11 pr-4 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 placeholder-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100 transition-all"
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full py-4 bg-gradient-to-r from-sky-500 to-cyan-500 text-white font-bold rounded-xl hover:from-sky-400 hover:to-cyan-400 transition-all text-base whitespace-nowrap cursor-pointer disabled:opacity-60"
              >
                {loading ? "發送中..." : "發送重設連結"}
              </button>
            </form>
          </>
        ) : (
          <div className="text-center">
            <div className="w-16 h-16 flex items-center justify-center bg-emerald-50 border border-emerald-100 rounded-2xl mx-auto mb-5">
              <i className="ri-checkbox-circle-line text-3xl text-emerald-500"></i>
            </div>
            <h2 className="text-2xl font-black text-slate-800 mb-3">請查看您的信箱</h2>
            <p className="text-slate-500 text-base mb-6 leading-relaxed">
              我們已將密碼重設連結發送至 <strong className="text-slate-700">{email}</strong>，請查看您的收件匣。
            </p>
          </div>
        )}

        <div className="mt-6 text-center">
          <Link
            to="/login"
            className="text-base text-sky-500 hover:text-sky-600 font-semibold cursor-pointer flex items-center justify-center gap-1.5 transition-colors"
          >
            <i className="ri-arrow-left-line"></i> 返回登入
          </Link>
        </div>
      </div>
    </div>
  );
};

export default ForgotPasswordPage;
