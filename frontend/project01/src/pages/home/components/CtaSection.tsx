import { Link } from "react-router-dom";

const CtaSection: React.FC = () => {
  return (
    <section className="py-28 px-6 relative overflow-hidden bg-gradient-to-br from-violet-500 via-sky-500 to-cyan-500">
      {/* 背景裝飾 */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-white/10 rounded-full blur-3xl" />
        <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-violet-300/20 rounded-full blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[300px] bg-sky-300/10 rounded-full blur-3xl" />
        <div
          className="absolute inset-0 opacity-[0.06]"
          style={{
            backgroundImage: "linear-gradient(white 1px, transparent 1px), linear-gradient(90deg, white 1px, transparent 1px)",
            backgroundSize: "48px 48px",
          }}
        />
      </div>

      <div className="relative z-10 max-w-3xl mx-auto text-center">
        <div className="w-20 h-20 flex items-center justify-center bg-white/20 backdrop-blur-sm rounded-2xl mx-auto mb-8 border border-white/30">
          <i className="ri-bar-chart-box-line text-white text-4xl"></i>
        </div>
        <h2 className="text-4xl md:text-5xl font-black text-white mb-6">
          準備好釋放您資料的潛力了嗎？
        </h2>
        <p className="text-white/80 mb-10 text-xl leading-relaxed max-w-xl mx-auto">
          加入數千位分析師、研究人員和商業專業人士，讓 DataAnalysis 幫您從資料中提取有意義的洞察。
        </p>
        <div className="flex items-center justify-center gap-5 flex-wrap">
          <Link
            to="/signup"
            className="px-10 py-4 bg-white text-violet-600 font-bold rounded-2xl hover:bg-violet-50 transition-all text-lg whitespace-nowrap cursor-pointer"
          >
            <i className="ri-rocket-line mr-2"></i>
            立即免費開始
          </Link>
          <Link
            to="/login"
            className="px-10 py-4 border-2 border-white/50 text-white font-semibold rounded-2xl hover:bg-white/15 transition-all text-lg whitespace-nowrap cursor-pointer"
          >
            已有帳號？登入
          </Link>
        </div>
      </div>
    </section>
  );
};

export default CtaSection;
