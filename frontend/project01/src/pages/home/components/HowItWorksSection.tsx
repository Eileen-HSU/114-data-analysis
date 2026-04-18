const steps = [
  {
    number: "01",
    title: "建立帳號",
    description: "幾秒鐘內免費註冊。無需信用卡，從免費方案開始使用。",
    icon: "ri-user-add-line",
    iconColor: "text-violet-500",
    iconBg: "bg-violet-50",
    numColor: "text-violet-600",
    numBg: "bg-violet-100",
    border: "border-violet-100",
    hoverBorder: "hover:border-violet-200",
  },
  {
    number: "02",
    title: "上傳您的資料",
    description: "將檔案拖放到工作區。支援 CSV、Excel、JSON 和純文字格式。",
    icon: "ri-upload-2-line",
    iconColor: "text-sky-500",
    iconBg: "bg-sky-50",
    numColor: "text-sky-600",
    numBg: "bg-sky-100",
    border: "border-sky-100",
    hoverBorder: "hover:border-sky-200",
  },
  {
    number: "03",
    title: "提出您的問題",
    description: "用自然語言輸入分析問題。AI 將處理並回應詳細的洞察結果。",
    icon: "ri-chat-3-line",
    iconColor: "text-cyan-500",
    iconBg: "bg-cyan-50",
    numColor: "text-cyan-600",
    numBg: "bg-cyan-100",
    border: "border-cyan-100",
    hoverBorder: "hover:border-cyan-200",
  },
  {
    number: "04",
    title: "儲存與整理",
    description: "將分析儲存到我的作品集。建立資料夾，按專案整理您的工作。",
    icon: "ri-save-line",
    iconColor: "text-teal-500",
    iconBg: "bg-teal-50",
    numColor: "text-teal-600",
    numBg: "bg-teal-100",
    border: "border-teal-100",
    hoverBorder: "hover:border-teal-200",
  },
];

const HowItWorksSection: React.FC = () => {
  return (
    <section className="py-28 px-6 bg-gradient-to-b from-violet-50/40 via-sky-50/30 to-white">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-20">
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-50 to-sky-50 border border-violet-100 rounded-full mb-5">
            <span className="bg-gradient-to-r from-violet-600 to-sky-600 bg-clip-text text-transparent text-base font-semibold">使用流程</span>
          </div>
          <h2 className="text-4xl md:text-5xl font-black text-slate-800 mb-5">如何使用</h2>
          <p className="text-slate-500 max-w-xl mx-auto text-xl leading-relaxed">
            只需四個簡單步驟，從原始資料到可行的洞察。
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {steps.map((step, index) => (
            <div key={step.number} className="relative">
              {index < steps.length - 1 && (
                <div className="hidden lg:flex absolute top-10 left-[calc(50%+3rem)] w-[calc(100%-6rem)] items-center z-0">
                  <div className="flex-1 h-px bg-gradient-to-r from-violet-200 via-sky-200 to-cyan-100" />
                  <i className="ri-arrow-right-s-line text-violet-300 text-lg -ml-1"></i>
                </div>
              )}

              <div className={`relative z-10 flex flex-col items-center text-center p-6 bg-white border border-slate-100 ${step.hoverBorder} rounded-2xl hover:bg-violet-50/10 transition-all`}>
                <div className={`w-8 h-8 flex items-center justify-center ${step.numBg} rounded-full mb-4`}>
                  <span className={`text-sm font-black ${step.numColor}`}>{index + 1}</span>
                </div>
                <div className={`w-16 h-16 flex items-center justify-center ${step.iconBg} border ${step.border} rounded-2xl mb-5`}>
                  <i className={`${step.icon} text-3xl ${step.iconColor}`}></i>
                </div>
                <h3 className="text-xl font-bold text-slate-800 mb-3">{step.title}</h3>
                <p className="text-base text-slate-500 leading-relaxed">{step.description}</p>
              </div>
            </div>
          ))}
        </div>

        {/* 底部展示圖 */}
        <div className="mt-20 rounded-2xl overflow-hidden border border-violet-100 relative">
          <img
            src="https://readdy.ai/api/search-image?query=clean%20bright%20white%20data%20analytics%20dashboard%20interface%20with%20violet%20purple%20sky%20blue%20cyan%20accent%20charts%2C%20bar%20graphs%2C%20line%20charts%2C%20data%20tables%2C%20modern%20minimal%20UI%20design%2C%20professional%20SaaS%20software%20screenshot%2C%20light%20background%2C%20crisp%20clean%20design&width=1200&height=500&seq=dashboard-violet-v1&orientation=landscape"
            alt="系統預覽"
            className="w-full h-72 object-cover object-top"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-white via-transparent to-transparent" />
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 text-center">
            <p className="text-slate-800 font-bold text-xl">強大的分析工作區</p>
            <p className="text-slate-500 text-base mt-2">直覺的介面，讓資料分析變得簡單</p>
          </div>
        </div>
      </div>
    </section>
  );
};

export default HowItWorksSection;
