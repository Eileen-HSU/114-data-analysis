interface Feature {
  icon: string;
  title: string;
  description: string;
  iconColor: string;
  iconBg: string;
  tag: string;
  tagColor: string;
  tagBg: string;
  borderHover: string;
  bgHover: string;
}

const features: Feature[] = [
  {
    icon: "ri-upload-cloud-2-line",
    title: "輕鬆上傳檔案",
    description: "拖放您的 CSV、Excel、JSON 或文字檔案。系統即時處理並準備好您的資料進行分析。",
    iconColor: "text-violet-500",
    iconBg: "bg-violet-50",
    tag: "核心功能",
    tagColor: "text-violet-600",
    tagBg: "bg-violet-50 border-violet-200",
    borderHover: "hover:border-violet-200",
    bgHover: "hover:bg-violet-50/30",
  },
  {
    icon: "ri-brain-line",
    title: "AI 智能分析",
    description: "用自然語言提問，獲得智能洞察。我們的 AI 理解上下文，提供有意義的分析結果。",
    iconColor: "text-sky-500",
    iconBg: "bg-sky-50",
    tag: "AI 驅動",
    tagColor: "text-sky-600",
    tagBg: "bg-sky-50 border-sky-200",
    borderHover: "hover:border-sky-200",
    bgHover: "hover:bg-sky-50/30",
  },
  {
    icon: "ri-folder-chart-line",
    title: "智能作品集",
    description: "將分析檔案整理到資料夾中。建立個人知識庫，隨時回顧您的洞察成果。",
    iconColor: "text-cyan-500",
    iconBg: "bg-cyan-50",
    tag: "組織管理",
    tagColor: "text-cyan-600",
    tagBg: "bg-cyan-50 border-cyan-200",
    borderHover: "hover:border-cyan-200",
    bgHover: "hover:bg-cyan-50/30",
  },
  {
    icon: "ri-history-line",
    title: "工作階段歷史",
    description: "每個分析工作階段都會自動儲存。從上次中斷的地方繼續，或開啟全新工作區。",
    iconColor: "text-teal-500",
    iconBg: "bg-teal-50",
    tag: "自動儲存",
    tagColor: "text-teal-600",
    tagBg: "bg-teal-50 border-teal-200",
    borderHover: "hover:border-teal-200",
    bgHover: "hover:bg-teal-50/30",
  },
  {
    icon: "ri-bar-chart-grouped-line",
    title: "視覺化報告",
    description: "將原始數字轉化為精美的圖表。以清晰的視覺格式與團隊分享洞察。",
    iconColor: "text-violet-500",
    iconBg: "bg-violet-50",
    tag: "視覺化",
    tagColor: "text-violet-600",
    tagBg: "bg-violet-50 border-violet-200",
    borderHover: "hover:border-violet-200",
    bgHover: "hover:bg-violet-50/30",
  },
  {
    icon: "ri-shield-check-line",
    title: "安全與隱私",
    description: "您的資料屬於您。企業級加密確保您的敏感資訊始終受到保護。",
    iconColor: "text-sky-500",
    iconBg: "bg-sky-50",
    tag: "資料安全",
    tagColor: "text-sky-600",
    tagBg: "bg-sky-50 border-sky-200",
    borderHover: "hover:border-sky-200",
    bgHover: "hover:bg-sky-50/30",
  },
];

const FeaturesSection: React.FC = () => {
  return (
    <section className="py-28 px-6 bg-white">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-20">
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-50 to-sky-50 border border-violet-100 rounded-full mb-5">
            <span className="bg-gradient-to-r from-violet-600 to-sky-600 bg-clip-text text-transparent text-base font-semibold">功能特色</span>
          </div>
          <h2 className="text-4xl md:text-5xl font-black text-slate-800 mb-5">
            分析資料所需的一切工具
          </h2>
          <p className="text-slate-500 max-w-xl mx-auto text-xl leading-relaxed">
            從簡單的 CSV 檔案到複雜的資料集，DataAnalysis 提供您提取有意義洞察所需的所有工具。
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((feature) => (
            <div
              key={feature.title}
              className={`p-8 rounded-2xl bg-white border border-slate-100 ${feature.borderHover} ${feature.bgHover} transition-all group`}
            >
              <div className="flex items-start justify-between mb-6">
                <div className={`w-14 h-14 flex items-center justify-center ${feature.iconBg} rounded-2xl group-hover:scale-110 transition-transform`}>
                  <i className={`${feature.icon} text-2xl ${feature.iconColor}`}></i>
                </div>
                <span className={`text-sm font-semibold px-3 py-1.5 rounded-full border ${feature.tagBg} ${feature.tagColor}`}>
                  {feature.tag}
                </span>
              </div>
              <h3 className="text-xl font-bold text-slate-800 mb-3">{feature.title}</h3>
              <p className="text-base text-slate-500 leading-relaxed">{feature.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default FeaturesSection;
