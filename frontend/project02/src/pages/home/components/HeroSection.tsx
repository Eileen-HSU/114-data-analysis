import { Link } from "react-router-dom";

const HeroSection: React.FC = () => {
  return (
    <section className="relative min-h-screen flex items-center justify-center overflow-hidden">

      {/* 主要內容 */}
      <div className="relative z-10 w-full max-w-5xl mx-auto px-8 text-center">

        {/* 標籤 badge */}
        <div className="inline-flex items-center gap-2.5 px-5 py-2.5 bg-white/20 backdrop-blur-sm border border-white/40 rounded-full mb-10">
          <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
          <span className="text-white text-base font-semibold">
            AI 驅動的智能資料分析平台
          </span>
        </div>

        {/* 主標題 */}
        <h1 className="text-4xl md:text-6xl font-black text-white mb-6 leading-tight tracking-tight">
          將原始資料轉化為
          <br />
          <span className="relative inline-block mt-1">
            <span className="text-rose-100">
              深度洞察
            </span>
            <span className="absolute -bottom-1 left-0 right-0 h-1 bg-white/50 rounded-full" />
          </span>
        </h1>

        {/* 副標題 */}
        <p className="text-xl text-white/80 mb-12 max-w-2xl mx-auto leading-relaxed">
          上傳 CSV、Excel、JSON 或文字檔案，即可獲得由先進 AI 驅動的即時深度分析。
          儲存成果、整理作品集，隨時回顧洞察。
        </p>

        {/* CTA 按鈕 */}
        <div className="flex items-center justify-center gap-4 flex-wrap mb-16">
          <Link
            to="/signup"
            className="px-10 py-4 bg-white text-rose-400 font-bold rounded-2xl hover:bg-rose-50 transition-all text-lg whitespace-nowrap cursor-pointer"
          >
            <i className="ri-rocket-line mr-2"></i>
            免費開始使用
          </Link>
          <Link
            to="/login"
            className="px-10 py-4 border-2 border-white/60 text-white font-semibold rounded-2xl hover:bg-white/20 transition-all text-lg whitespace-nowrap cursor-pointer"
          >
            <i className="ri-login-box-line mr-2"></i>
            登入帳號
          </Link>
        </div>

        {/* 特色標籤列 */}
        <div className="flex items-center justify-center gap-4 flex-wrap">
          {[
            { icon: "ri-file-excel-2-line", label: "支援 CSV / Excel / JSON" },
            { icon: "ri-brain-line", label: "AI 智能分析" },
            { icon: "ri-folder-chart-line", label: "作品集管理" },
            { icon: "ri-shield-check-line", label: "安全加密" },
          ].map((item) => (
            <div key={item.label} className="flex items-center gap-2 px-4 py-2 bg-white/20 backdrop-blur-sm border border-white/30 rounded-full">
              <i className={`${item.icon} text-white text-base`}></i>
              <span className="text-white text-base font-medium">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 底部滾動提示 */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-white/60">
        <span className="text-sm">向下滾動探索</span>
        <i className="ri-arrow-down-line animate-bounce text-white/80 text-xl"></i>
      </div>
    </section>
  );
};

export default HeroSection;
