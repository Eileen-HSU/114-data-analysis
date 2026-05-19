import { Link } from "react-router-dom";

const HeroSection: React.FC = () => {
  return (
    <section className="relative min-h-[calc(100vh-72px)] flex items-center justify-center overflow-hidden bg-gradient-to-br from-violet-50 via-sky-50 to-cyan-50">
      {/* 背景裝飾光暈 */}
      <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-gradient-to-bl from-violet-200/50 via-sky-100/30 to-transparent rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-gradient-to-tr from-cyan-100/60 via-sky-50/40 to-transparent rounded-full blur-3xl pointer-events-none" />
      <div className="absolute top-1/3 left-1/4 w-[400px] h-[400px] bg-violet-100/40 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/3 right-1/4 w-[300px] h-[300px] bg-sky-100/50 rounded-full blur-3xl pointer-events-none" />

      {/* 背景網格裝飾 */}
      <div
        className="absolute inset-0 opacity-[0.04] pointer-events-none"
        style={{
          backgroundImage: "linear-gradient(#7c3aed 1px, transparent 1px), linear-gradient(90deg, #0ea5e9 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />

      {/* 主要內容 */}
      <div className="relative z-10 w-full max-w-5xl mx-auto px-8 text-center">

        {/* 標籤 badge */}
        <div className="inline-flex items-center gap-2.5 px-5 py-2.5 bg-gradient-to-r from-violet-50 to-sky-50 border border-violet-200 rounded-full mb-10">
          <span className="w-2 h-2 bg-gradient-to-r from-violet-500 to-sky-500 rounded-full animate-pulse" />
          <span className="bg-gradient-to-r from-violet-600 to-sky-600 bg-clip-text text-transparent text-base font-semibold">
            AI 驅動的智能資料分析平台
          </span>
        </div>

        {/* 主標題 */}
        <h1 className="text-4xl md:text-6xl font-black text-slate-800 mb-6 leading-tight tracking-tight">
          將原始資料轉化為
          <br />
          <span className="relative inline-block mt-1">
            <span className="bg-gradient-to-r from-violet-500 via-sky-500 to-cyan-500 bg-clip-text text-transparent">
              深度洞察
            </span>
            <span className="absolute -bottom-1 left-0 right-0 h-1 bg-gradient-to-r from-violet-400 via-sky-400 to-cyan-400 rounded-full opacity-40" />
          </span>
        </h1>

        {/* 副標題 */}
        <p className="text-xl text-slate-500 mb-12 max-w-2xl mx-auto leading-relaxed">
          上傳 CSV、Excel、JSON 或文字檔案，即可獲得由先進 AI 驅動的即時深度分析。
          儲存成果、整理作品集，隨時回顧洞察。
        </p>

        {/* CTA 按鈕 */}
        <div className="flex items-center justify-center gap-4 flex-wrap mb-16">
          <Link
            to="/signup"
            className="px-10 py-4 bg-gradient-to-r from-violet-500 via-sky-500 to-cyan-500 text-white font-bold rounded-2xl hover:from-violet-400 hover:to-cyan-400 transition-all text-lg whitespace-nowrap cursor-pointer"
          >
            <i className="ri-rocket-line mr-2"></i>
            免費開始使用
          </Link>
          <Link
            to="/login"
            className="px-10 py-4 border-2 border-slate-200 text-slate-600 font-semibold rounded-2xl hover:border-violet-300 hover:text-violet-600 hover:bg-violet-50 transition-all text-lg whitespace-nowrap cursor-pointer"
          >
            <i className="ri-login-box-line mr-2"></i>
            登入帳號
          </Link>
        </div>

        {/* 特色標籤列 */}
        <div className="flex items-center justify-center gap-4 flex-wrap">
          {[
            { icon: "ri-file-excel-2-line", label: "支援 CSV / Excel / JSON", color: "text-violet-500", bg: "bg-violet-50 border-violet-100" },
            { icon: "ri-brain-line", label: "AI 智能分析", color: "text-sky-500", bg: "bg-sky-50 border-sky-100" },
            { icon: "ri-folder-chart-line", label: "作品集管理", color: "text-cyan-500", bg: "bg-cyan-50 border-cyan-100" },
            { icon: "ri-shield-check-line", label: "安全加密", color: "text-teal-500", bg: "bg-teal-50 border-teal-100" },
          ].map((item) => (
            <div key={item.label} className={`flex items-center gap-2 px-4 py-2 bg-white border rounded-full ${item.bg}`}>
              <i className={`${item.icon} ${item.color} text-base`}></i>
              <span className="text-slate-600 text-base font-medium">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 底部滾動提示 */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-slate-400">
        <span className="text-sm">向下滾動探索</span>
        <i className="ri-arrow-down-line animate-bounce text-violet-400 text-xl"></i>
      </div>
    </section>
  );
};

export default HeroSection;
