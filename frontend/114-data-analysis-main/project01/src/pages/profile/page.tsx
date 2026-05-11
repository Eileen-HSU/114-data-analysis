import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import Navbar from "@/components/feature/Navbar";
import LoginRequiredModal from "@/components/base/LoginRequiredModal";

const DEFAULT_AVATAR = "https://static.readdy.ai/image/9080131fd243e879b7aeaa20dae1f896/4c3cdad381172f4be4b30c4ec4f8f3c8.png";
const DEFAULT_COVER = "https://static.readdy.ai/image/9080131fd243e879b7aeaa20dae1f896/be1332bb6323931804c694d465e24796.png";

const ProfilePage: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(false);
  const [activeTab, setActiveTab] = useState<"info" | "security" | "activity">("info");
  const [avatarUrl, setAvatarUrl] = useState<string>(DEFAULT_AVATAR);
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const editSectionRef = useRef<HTMLDivElement>(null);

  const [form, setForm] = useState({
    name: user?.name || "使用者",
    bio: "熱愛資料分析，專注於商業智慧與機器學習應用。",
    phone: "+886 912 345 678",
    company: "DataTech 科技有限公司",
    gender: "不願透露",
    location: "台北市，台灣",
  });
  const [saved, setSaved] = useState(false);

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      if (ev.target?.result) setAvatarUrl(ev.target.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleSave = () => {
    setEditing(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const handleEditClick = () => {
    if (editing) {
      setEditing(false);
      return;
    }

    setActiveTab("info");
    setEditing(true);
    setTimeout(() => {
      editSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
  };

  const activities = [
    { icon: "ri-file-chart-line", text: "分析了「Q4 銷售報告.csv」", time: "2 小時前", color: "text-violet-500", bg: "bg-violet-50" },
    { icon: "ri-folder-add-line", text: "建立資料夾「2025 年度報告」", time: "昨天 14:32", color: "text-sky-500", bg: "bg-sky-50" },
    { icon: "ri-upload-cloud-2-line", text: "上傳了「用戶行為分析.xlsx」", time: "昨天 10:15", color: "text-cyan-500", bg: "bg-cyan-50" },
    { icon: "ri-save-line", text: "儲存工作區「市場趨勢分析」", time: "3 天前", color: "text-teal-500", bg: "bg-teal-50" },
    { icon: "ri-file-chart-line", text: "分析了「競品比較資料.json」", time: "5 天前", color: "text-violet-500", bg: "bg-violet-50" },
    { icon: "ri-folder-add-line", text: "建立資料夾「競品研究」", time: "1 週前", color: "text-sky-500", bg: "bg-sky-50" },
  ];

  // 統計卡片 - 純色淡色背景，不用漸層
  const stats = [
    { label: "分析次數", value: "47", icon: "ri-bar-chart-line", iconColor: "text-violet-400", iconBg: "bg-violet-50", topBar: "bg-violet-300" },
    { label: "作品集數", value: "12", icon: "ri-folder-line", iconColor: "text-sky-400", iconBg: "bg-sky-50", topBar: "bg-sky-300" },
    { label: "上傳檔案", value: "83", icon: "ri-file-line", iconColor: "text-cyan-400", iconBg: "bg-cyan-50", topBar: "bg-cyan-300" },
    { label: "使用天數", value: "128", icon: "ri-calendar-line", iconColor: "text-teal-400", iconBg: "bg-teal-50", topBar: "bg-teal-300" },
  ];

  // 基本資料欄位 icon 純色淡色
  const fields = [
    { label: "姓名", key: "name", icon: "ri-user-line", iconColor: "text-violet-400", iconBg: "bg-violet-50", type: "text" },
    { label: "手機號碼", key: "phone", icon: "ri-smartphone-line", iconColor: "text-sky-400", iconBg: "bg-sky-50", type: "tel" },
    { label: "公司 / 機構", key: "company", icon: "ri-building-line", iconColor: "text-cyan-400", iconBg: "bg-cyan-50", type: "text" },
    { label: "性別", key: "gender", icon: "ri-user-heart-line", iconColor: "text-teal-400", iconBg: "bg-teal-50", type: "text" },
    { label: "所在地", key: "location", icon: "ri-map-pin-line", iconColor: "text-violet-400", iconBg: "bg-violet-50", type: "text" },
  ];

  const inputClass = "w-full pl-11 pr-4 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 focus:outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-50 transition-all";
  const readonlyClass = "flex items-center gap-3 px-4 py-3.5 bg-slate-50 border border-slate-100 rounded-xl";

  return (
    <div className="min-h-screen bg-gradient-to-br from-violet-50 via-sky-50 to-cyan-50 flex flex-col">
      <Navbar onLoginRequired={() => setShowModal(true)} />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-10">

          {/* 頂部個人資訊卡 */}
          <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden mb-6 shadow-sm">

            {/* 封面 - 固定圖片，不可編輯，高度加大讓山露出更多 */}
            <div className="h-56 relative overflow-hidden">
              <img
                src={DEFAULT_COVER}
                alt="封面"
                className="w-full h-full object-cover object-center"
              />
              {/* 登出按鈕 */}
              <button
                onClick={() => { logout(); navigate("/"); }}
                className="absolute top-4 right-4 flex items-center gap-2 px-4 py-2 bg-white/25 backdrop-blur-sm text-white text-sm font-semibold rounded-xl hover:bg-white/40 cursor-pointer whitespace-nowrap border border-white/30 transition-colors"
              >
                <i className="ri-logout-box-line"></i> 登出
              </button>
            </div>

            {/* 頭像 + 基本資訊 */}
            <div className="px-8 pt-0 pb-7">
              <div className="flex items-start gap-5 mb-5" style={{ marginTop: "-48px" }}>
                {/* 頭像 */}
                <div className="relative flex-shrink-0">
                  <div
                    className="w-24 h-24 rounded-full border-4 border-white overflow-hidden bg-violet-50 flex items-center justify-center cursor-pointer group shadow-md"
                    onClick={() => avatarInputRef.current?.click()}
                  >
                    <img src={avatarUrl} alt="頭像" className="w-full h-full object-cover" />
                    <div className="absolute inset-0 bg-black/30 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                      <i className="ri-camera-line text-white text-2xl"></i>
                    </div>
                  </div>
                  <button
                    onClick={() => avatarInputRef.current?.click()}
                    className="absolute bottom-0 right-0 w-8 h-8 flex items-center justify-center bg-violet-400 rounded-full border-2 border-white cursor-pointer hover:bg-violet-500 transition-all shadow-sm"
                  >
                    <i className="ri-camera-line text-white text-sm"></i>
                  </button>
                  <input ref={avatarInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
                </div>

                {/* 名字區塊 */}
                <div className="pt-14 flex-1 flex items-end justify-between">
                  <div>
                    <div className="flex items-center gap-3 flex-wrap">
                      <h1 className="text-2xl font-bold text-slate-800">{user?.name || form.name}</h1>
                      <span className="px-3 py-1 bg-violet-50 text-violet-500 text-sm font-semibold rounded-full border border-violet-100">
                        專業版
                      </span>
                    </div>
                    <p className="text-base text-slate-400 mt-1">{user?.email || "user@example.com"}</p>
                  </div>
                  <button
                    onClick={handleEditClick}
                    className="flex items-center gap-2 px-5 py-2.5 bg-violet-500 text-white text-base font-bold rounded-xl hover:bg-violet-400 cursor-pointer whitespace-nowrap transition-all shadow-sm"
                  >
                    <i className={editing ? "ri-close-line" : "ri-edit-line"}></i>
                    {editing ? "取消" : "編輯資料"}
                  </button>
                </div>
              </div>

              {/* 統計數字 - 純色淡色 icon */}
              <div className="grid grid-cols-4 gap-4 mb-5">
                {stats.map((s) => (
                  <div key={s.label} className="relative overflow-hidden rounded-2xl p-4 text-center bg-white border border-slate-100 hover:border-violet-100 transition-colors">
                    <div className={`absolute top-0 left-0 right-0 h-1 ${s.topBar} opacity-60`} />
                    <div className={`w-10 h-10 flex items-center justify-center mx-auto mb-2 rounded-xl ${s.iconBg}`}>
                      <i className={`${s.icon} ${s.iconColor} text-xl`}></i>
                    </div>
                    <div className="text-2xl font-black text-slate-800">{s.value}</div>
                    <div className="text-sm text-slate-500 mt-0.5">{s.label}</div>
                  </div>
                ))}
              </div>

              <p className="text-base text-slate-500 leading-relaxed">{form.bio}</p>
            </div>
          </div>

          {/* Tab 切換 */}
          <div className="flex gap-1 mb-6 bg-white border border-slate-100 rounded-xl p-1 w-fit shadow-sm">
            {(["info", "security", "activity"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-6 py-2.5 rounded-lg text-base font-semibold transition-all cursor-pointer whitespace-nowrap ${
                  activeTab === tab
                    ? "bg-violet-500 text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-800 hover:bg-slate-50"
                }`}
              >
                {tab === "info" ? "基本資料" : tab === "security" ? "帳號安全" : "活動紀錄"}
              </button>
            ))}
          </div>

          {/* 基本資料 Tab */}
          {activeTab === "info" && (
            <div ref={editSectionRef} className="bg-white border border-slate-100 rounded-2xl p-8 shadow-sm scroll-mt-24">
              <h2 className="text-xl font-bold text-slate-800 mb-7">基本資料</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {fields.map((field) => (
                  <div key={field.key}>
                    <label className="block text-sm font-semibold text-slate-600 mb-2">{field.label}</label>
                    {editing ? (
                      <div className="relative">
                        {/* 編輯模式：純色淡色 icon 背景 */}
                        <div className={`absolute left-3 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-md ${field.iconBg}`}>
                          <i className={`${field.icon} ${field.iconColor} text-sm`}></i>
                        </div>
                        <input
                          type={field.type}
                          value={form[field.key as keyof typeof form]}
                          onChange={(e) => setForm({ ...form, [field.key]: e.target.value })}
                          className={inputClass}
                        />
                      </div>
                    ) : (
                      <div className={readonlyClass}>
                        {/* 唯讀模式：純色淡色 icon 背景 */}
                        <div className={`w-7 h-7 flex items-center justify-center rounded-lg ${field.iconBg} flex-shrink-0`}>
                          <i className={`${field.icon} ${field.iconColor} text-sm`}></i>
                        </div>
                        <span className="text-base text-slate-700">{form[field.key as keyof typeof form]}</span>
                      </div>
                    )}
                  </div>
                ))}

                {/* 電子郵件 */}
                <div>
                  <label className="block text-sm font-semibold text-slate-600 mb-2">電子郵件</label>
                  <div className={readonlyClass}>
                    <div className="w-7 h-7 flex items-center justify-center rounded-lg bg-sky-50 flex-shrink-0">
                      <i className="ri-mail-line text-sky-400 text-sm"></i>
                    </div>
                    <span className="text-base text-slate-700">{user?.email || "user@example.com"}</span>
                    <span className="ml-auto px-2.5 py-1 bg-emerald-50 text-emerald-500 text-sm font-semibold rounded-full border border-emerald-100">已驗證</span>
                  </div>
                </div>

                {/* 加入日期 */}
                <div>
                  <label className="block text-sm font-semibold text-slate-600 mb-2">加入日期</label>
                  <div className={readonlyClass}>
                    <div className="w-7 h-7 flex items-center justify-center rounded-lg bg-teal-50 flex-shrink-0">
                      <i className="ri-calendar-line text-teal-400 text-sm"></i>
                    </div>
                    <span className="text-base text-slate-700">{user?.joinDate || "2025-01-15"}</span>
                  </div>
                </div>
              </div>

              {/* 自我介紹 */}
              <div className="mt-6">
                <label className="block text-sm font-semibold text-slate-600 mb-2">自我介紹</label>
                {editing ? (
                  <textarea
                    value={form.bio}
                    onChange={(e) => setForm({ ...form, bio: e.target.value })}
                    rows={3}
                    maxLength={500}
                    className="w-full px-4 py-3.5 bg-white border border-slate-200 rounded-xl text-base text-slate-800 focus:outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-50 transition-all resize-none"
                  />
                ) : (
                  <div className={readonlyClass}>
                    <p className="text-base text-slate-700 leading-relaxed">{form.bio}</p>
                  </div>
                )}
              </div>

              {editing && (
                <div className="flex gap-3 mt-7">
                  <button onClick={handleSave}
                    className="px-7 py-3 bg-violet-500 text-white text-base font-bold rounded-xl hover:bg-violet-400 cursor-pointer whitespace-nowrap transition-all">
                    儲存變更
                  </button>
                  <button onClick={() => setEditing(false)}
                    className="px-7 py-3 border border-slate-200 text-slate-500 text-base font-semibold rounded-xl hover:bg-slate-50 cursor-pointer whitespace-nowrap transition-colors">
                    取消
                  </button>
                  {saved && <span className="flex items-center gap-2 text-emerald-500 text-base"><i className="ri-checkbox-circle-line"></i> 已儲存！</span>}
                </div>
              )}
              {saved && !editing && (
                <div className="mt-5 flex items-center gap-2 text-emerald-500 text-base">
                  <i className="ri-checkbox-circle-line"></i> 資料已成功儲存！
                </div>
              )}
            </div>
          )}

          {/* 帳號安全 Tab */}
          {activeTab === "security" && (
            <div className="bg-white border border-slate-100 rounded-2xl p-8 space-y-4 shadow-sm">
              <h2 className="text-xl font-bold text-slate-800 mb-7">帳號安全</h2>
              {[
                { label: "修改密碼", desc: "定期更換密碼以保護帳號安全", icon: "ri-lock-password-line", btn: "修改", iconColor: "text-violet-400", iconBg: "bg-violet-50" },
                { label: "兩步驟驗證", desc: "啟用後登入時需要額外驗證碼", icon: "ri-shield-check-line", btn: "啟用", iconColor: "text-sky-400", iconBg: "bg-sky-50" },
                { label: "登入裝置管理", desc: "查看並管理所有已登入的裝置", icon: "ri-device-line", btn: "查看", iconColor: "text-teal-400", iconBg: "bg-teal-50" },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between p-5 bg-slate-50 border border-slate-100 rounded-xl hover:bg-violet-50/20 transition-colors">
                  <div className="flex items-center gap-4">
                    <div className={`w-12 h-12 flex items-center justify-center ${item.iconBg} rounded-xl`}>
                      <i className={`${item.icon} ${item.iconColor} text-xl`}></i>
                    </div>
                    <div>
                      <p className="text-base font-semibold text-slate-800">{item.label}</p>
                      <p className="text-sm text-slate-400 mt-0.5">{item.desc}</p>
                    </div>
                  </div>
                  <button className="px-5 py-2.5 border border-slate-200 text-slate-600 text-sm font-semibold rounded-xl hover:bg-white cursor-pointer whitespace-nowrap transition-colors">
                    {item.btn}
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 活動紀錄 Tab */}
          {activeTab === "activity" && (
            <div className="bg-white border border-slate-100 rounded-2xl p-8 shadow-sm">
              <h2 className="text-xl font-bold text-slate-800 mb-7">最近活動</h2>
              <div className="space-y-1">
                {activities.map((act, i) => (
                  <div key={i} className="flex items-center gap-4 p-4 rounded-xl hover:bg-violet-50/20 transition-colors">
                    <div className={`w-10 h-10 flex items-center justify-center ${act.bg} rounded-xl flex-shrink-0`}>
                      <i className={`${act.icon} ${act.color} text-lg`}></i>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-base text-slate-700 truncate">{act.text}</p>
                    </div>
                    <span className="text-sm text-slate-400 whitespace-nowrap">{act.time}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <LoginRequiredModal isOpen={showModal} onClose={() => setShowModal(false)} />
    </div>
  );
};

export default ProfilePage;
