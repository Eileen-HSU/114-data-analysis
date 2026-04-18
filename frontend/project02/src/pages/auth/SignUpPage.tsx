// 註冊頁面 - 暖色系呼應主頁
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

interface SignUpForm {
  name: string;
  email: string;
  phone: string;
  company: string;
  gender: string;
  password: string;
  confirm: string;
}

const SignUpPage: React.FC = () => {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState<SignUpForm>({
    name: "", email: "", phone: "", company: "", gender: "", password: "", confirm: "",
  });
  const [showPwd, setShowPwd] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm) { setError("兩次輸入的密碼不一致。"); return; }
    if (form.password.length < 6) { setError("密碼至少需要 6 個字元。"); return; }
    if (!form.gender) { setError("請選擇性別。"); return; }
    setLoading(true);
    const ok = await signup(form.name, form.email, form.password);
    setLoading(false);
    if (ok) navigate("/workspace");
  };

  const set = (key: keyof SignUpForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [key]: e.target.value });

  const inputClass = "w-full pl-11 pr-4 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 placeholder-slate-400 focus:outline-none focus:border-rose-300 focus:ring-2 focus:ring-rose-100 transition-all";

  return (
    <div className="min-h-screen bg-gradient-to-br from-rose-50 via-pink-50 to-amber-50 flex">
      {/* 左側視覺區 */}
      <div
        className="hidden lg:flex lg:w-1/2 relative flex-col items-center justify-center overflow-hidden"
        style={{
          backgroundImage: "url('https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/45a567062040783c374a34c5d2435a22.png')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-gradient-to-br from-slate-900/40 via-purple-900/20 to-pink-900/30" />
        <div className="relative z-10 flex flex-col items-center px-12 text-center">
          <div className="mb-10 flex flex-col items-center gap-3">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 flex items-center justify-center bg-white/20 backdrop-blur-sm rounded-2xl border border-white/30">
                <i className="ri-bar-chart-box-line text-white text-2xl"></i>
              </div>
              <span className="text-3xl font-black text-white tracking-tight">DataAnalysis</span>
            </div>
            <div className="h-px w-40 bg-white/30 mt-1" />
          </div>
          <h2 className="text-3xl font-bold text-white mb-4">開始分析您的資料</h2>
          <p className="text-white/80 text-lg leading-relaxed max-w-xs">
            加入數千位分析師、研究人員和商業專業人士，讓 DataAnalysis 幫您從原始資料中提取洞察。
          </p>
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
                <span className="text-white/85 text-base">{item.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 右側表單 */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8 overflow-y-auto relative">
        {/* 返回首頁按鈕 */}
        <Link
          to="/"
          className="absolute top-6 left-6 flex items-center gap-2 text-slate-500 hover:text-rose-500 transition-colors text-sm font-medium cursor-pointer group"
        >
          <div className="w-8 h-8 flex items-center justify-center rounded-full bg-white border border-slate-200 group-hover:border-rose-200 group-hover:bg-rose-50 transition-all">
            <i className="ri-arrow-left-line text-base"></i>
          </div>
          <span>返回首頁</span>
        </Link>

        <div className="w-full max-w-md py-8">
          {/* 手機版 Logo */}
          <div className="lg:hidden flex items-center gap-3 mb-8 justify-center">
            <div className="w-10 h-10 flex items-center justify-center bg-gradient-to-br from-rose-400 to-pink-500 rounded-xl">
              <i className="ri-bar-chart-box-line text-white text-xl"></i>
            </div>
            <span className="text-2xl font-black text-slate-800 tracking-tight">DataAnalysis</span>
          </div>

          <h1 className="text-3xl font-black text-slate-800 mb-2">建立帳號</h1>
          <p className="text-slate-500 text-base mb-7">
            已有帳號？{" "}
            <Link to="/login" className="text-rose-500 hover:text-rose-600 font-semibold cursor-pointer">
              立即登入
            </Link>
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* 姓名 */}
            <div>
              <label className="block text-sm font-semibold text-slate-600 mb-2">姓名 *</label>
              <div className="relative">
                <i className="ri-user-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                <input type="text" required value={form.name} onChange={set("name")} placeholder="請輸入您的姓名" className={inputClass} />
              </div>
            </div>

            {/* Gmail */}
            <div>
              <label className="block text-sm font-semibold text-slate-600 mb-2">Gmail 電子郵件 *</label>
              <div className="relative">
                <i className="ri-google-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                <input type="email" required value={form.email} onChange={set("email")} placeholder="your@gmail.com" className={inputClass} />
              </div>
            </div>

            {/* 手機號碼 */}
            <div>
              <label className="block text-sm font-semibold text-slate-600 mb-2">手機號碼 *</label>
              <div className="relative">
                <i className="ri-smartphone-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                <input type="tel" required value={form.phone} onChange={set("phone")} placeholder="+886 912 345 678" className={inputClass} />
              </div>
            </div>

            {/* 公司 & 性別 並排 */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-2">公司 / 機構</label>
                <div className="relative">
                  <i className="ri-building-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                  <input type="text" value={form.company} onChange={set("company")} placeholder="公司名稱" className={inputClass} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-2">性別 *</label>
                <div className="relative">
                  <i className="ri-user-heart-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                  <select required value={form.gender} onChange={set("gender")}
                    className="w-full pl-11 pr-4 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 focus:outline-none focus:border-rose-300 focus:ring-2 focus:ring-rose-100 transition-all appearance-none cursor-pointer">
                    <option value="" disabled>請選擇</option>
                    <option value="male">男性</option>
                    <option value="female">女性</option>
                    <option value="other">其他</option>
                    <option value="prefer_not">不願透露</option>
                  </select>
                </div>
              </div>
            </div>

            {/* 密碼 */}
            <div>
              <label className="block text-sm font-semibold text-slate-600 mb-2">密碼 *</label>
              <div className="relative">
                <i className="ri-lock-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                <input type={showPwd ? "text" : "password"} required value={form.password} onChange={set("password")} placeholder="至少 6 個字元"
                  className="w-full pl-11 pr-12 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 placeholder-slate-400 focus:outline-none focus:border-rose-300 focus:ring-2 focus:ring-rose-100 transition-all" />
                <button type="button" onClick={() => setShowPwd(!showPwd)} className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer">
                  <i className={showPwd ? "ri-eye-off-line text-base" : "ri-eye-line text-base"}></i>
                </button>
              </div>
            </div>

            {/* 確認密碼 */}
            <div>
              <label className="block text-sm font-semibold text-slate-600 mb-2">確認密碼 *</label>
              <div className="relative">
                <i className="ri-lock-password-line absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-base"></i>
                <input type={showConfirm ? "text" : "password"} required value={form.confirm} onChange={set("confirm")} placeholder="再次輸入密碼"
                  className="w-full pl-11 pr-12 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 placeholder-slate-400 focus:outline-none focus:border-rose-300 focus:ring-2 focus:ring-rose-100 transition-all" />
                <button type="button" onClick={() => setShowConfirm(!showConfirm)} className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer">
                  <i className={showConfirm ? "ri-eye-off-line text-base" : "ri-eye-line text-base"}></i>
                </button>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl">
                <i className="ri-error-warning-line text-red-500 text-base"></i>
                <p className="text-red-600 text-sm">{error}</p>
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full py-4 bg-gradient-to-r from-rose-400 to-pink-500 text-white font-bold rounded-xl hover:from-rose-300 hover:to-pink-400 transition-all text-base whitespace-nowrap cursor-pointer disabled:opacity-60 mt-2">
              {loading ? "建立中..." : "建立帳號"}
            </button>
          </form>

          <p className="text-sm text-slate-400 text-center mt-6">
            註冊即表示您同意我們的{" "}
            <a href="#" className="underline cursor-pointer hover:text-slate-600" rel="nofollow">服務條款</a>{" "}
            與{" "}
            <a href="#" className="underline cursor-pointer hover:text-slate-600" rel="nofollow">隱私政策</a>
          </p>
        </div>
      </div>
    </div>
  );
};

export default SignUpPage;
