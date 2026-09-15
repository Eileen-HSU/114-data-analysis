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
    title: "Easy file upload",
    description: "Drag and drop CSV, Excel, JSON, or text files. The system processes them and prepares your data for analysis.",
    iconColor: "text-violet-500",
    iconBg: "bg-violet-50",
    tag: "Core",
    tagColor: "text-violet-600",
    tagBg: "bg-violet-50 border-violet-200",
    borderHover: "hover:border-violet-200",
    bgHover: "hover:bg-violet-50/30",
  },
  {
    icon: "ri-brain-line",
    title: "AI-powered analysis",
    description: "Ask questions in natural language and receive intelligent insights. Our AI understands context and delivers meaningful analysis.",
    iconColor: "text-sky-500",
    iconBg: "bg-sky-50",
    tag: "AI",
    tagColor: "text-sky-600",
    tagBg: "bg-sky-50 border-sky-200",
    borderHover: "hover:border-sky-200",
    bgHover: "hover:bg-sky-50/30",
  },
  {
    icon: "ri-folder-chart-line",
    title: "Smart portfolio",
    description: "Organize analyzed files into folders. Build a personal knowledge base and revisit insights anytime.",
    iconColor: "text-cyan-500",
    iconBg: "bg-cyan-50",
    tag: "Organization",
    tagColor: "text-cyan-600",
    tagBg: "bg-cyan-50 border-cyan-200",
    borderHover: "hover:border-cyan-200",
    bgHover: "hover:bg-cyan-50/30",
  },
  {
    icon: "ri-history-line",
    title: "Session history",
    description: "Each analysis session is saved automatically. Continue where you left off or open a new workspace.",
    iconColor: "text-teal-500",
    iconBg: "bg-teal-50",
    tag: "Auto-save",
    tagColor: "text-teal-600",
    tagBg: "bg-teal-50 border-teal-200",
    borderHover: "hover:border-teal-200",
    bgHover: "hover:bg-teal-50/30",
  },
  {
    icon: "ri-bar-chart-grouped-line",
    title: "Visual reports",
    description: "Turn raw numbers into beautiful charts. Share insights with your team in clear visual formats.",
    iconColor: "text-violet-500",
    iconBg: "bg-violet-50",
    tag: "Visualization",
    tagColor: "text-violet-600",
    tagBg: "bg-violet-50 border-violet-200",
    borderHover: "hover:border-violet-200",
    bgHover: "hover:bg-violet-50/30",
  },
  {
    icon: "ri-shield-check-line",
    title: "Security & privacy",
    description: "Your data belongs to you. Enterprise-grade encryption keeps your sensitive information protected.",
    iconColor: "text-sky-500",
    iconBg: "bg-sky-50",
    tag: "Data security",
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
            <span className="bg-gradient-to-r from-violet-600 to-sky-600 bg-clip-text text-transparent text-base font-semibold">Features</span>
          </div>
          <h2 className="text-4xl md:text-5xl font-black text-slate-800 mb-5">
            All the tools you need for data analysis
          </h2>
          <p className="text-slate-500 max-w-xl mx-auto text-xl leading-relaxed">
            From simple CSV files to complex datasets, DataAnalysis provides the tools you need to extract meaningful insights.
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
