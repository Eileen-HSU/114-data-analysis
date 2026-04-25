import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import SurveyDetailPage from "./components/SurveyDetailPage";
import { MOCK_SURVEY_RECORDS, MOCK_SURVEY_DETAILS } from "../../mocks/surveys";
import "./profile.css";

const DEFAULT_AVATAR = "https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/b181cfaad2165c1909b7c8fa8339cbe7.png";

function getLocalSurveys() {
  return Object.values(JSON.parse(localStorage.getItem("surveys") || "{}"));
}

export default function ProfilePage() {
  const navigate = useNavigate();
  const avatarInputRef = useRef(null);
  const [activeTab, setActiveTab] = useState("info");
  const [isEditing, setIsEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [avatarSrc, setAvatarSrc] = useState(DEFAULT_AVATAR);
  const [profile, setProfile] = useState({
    name: "陳小明",
    phone: "+886 912 345 678",
    company: "DataAnalysis 團隊",
    gender: "未設定",
    location: "台北",
    bio: "資料分析與問卷洞察使用者，常用 AI 協助整理報表與回覆趨勢。",
  });
  const [editProfile, setEditProfile] = useState(profile);

  const localSurveys = useMemo(() => getLocalSurveys(), [selectedSurvey, saved]);
  const surveyRecords = [
    ...localSurveys.map((survey) => ({
      id: survey.id || survey.code,
      title: survey.title,
      code: survey.code,
      createdAt: survey.createdAt,
      responseCount: survey.responses?.length || 0,
      status: "active",
      local: true,
      detail: survey,
    })),
    ...MOCK_SURVEY_RECORDS.map((record) => ({ ...record, detail: MOCK_SURVEY_DETAILS[record.id] })),
  ];

  if (selectedSurvey) {
    return <SurveyDetailPage survey={selectedSurvey} onBack={() => setSelectedSurvey(null)} />;
  }

  const handleAvatarChange = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (loadEvent) => {
      if (loadEvent.target?.result) setAvatarSrc(loadEvent.target.result);
    };
    reader.readAsDataURL(file);
  };

  const handleSave = () => {
    setProfile(editProfile);
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      setIsEditing(false);
    }, 900);
  };

  const handleCancel = () => {
    setEditProfile(profile);
    setIsEditing(false);
  };

  const stats = [
    { icon: "ri-bar-chart-line", iconColor: "text-stat-coral", iconBg: "bg-stat-coral", barBg: "bar-coral", num: surveyRecords.length, label: "問卷數" },
    { icon: "ri-user-line", iconColor: "text-stat-mauve", iconBg: "bg-stat-mauve", barBg: "bar-mauve", num: surveyRecords.reduce((sum, survey) => sum + survey.responseCount, 0), label: "總回覆" },
    { icon: "ri-folder-line", iconColor: "text-stat-sky", iconBg: "bg-stat-sky", barBg: "bar-sky", num: 12, label: "資料夾" },
    { icon: "ri-calendar-line", iconColor: "text-stat-teal", iconBg: "bg-stat-teal", barBg: "bar-teal", num: 128, label: "使用天數" },
  ];

  const infoFields = [
    { label: "姓名", key: "name", icon: "ri-user-line", iconColor: "text-violet", iconBg: "bg-violet-50", type: "text" },
    { label: "電話", key: "phone", icon: "ri-smartphone-line", iconColor: "text-sky", iconBg: "bg-sky-50", type: "tel" },
    { label: "公司 / 組織", key: "company", icon: "ri-building-line", iconColor: "text-cyan", iconBg: "bg-cyan-50", type: "text" },
    { label: "性別", key: "gender", icon: "ri-user-heart-line", iconColor: "text-teal", iconBg: "bg-teal-50", type: "text" },
    { label: "所在地", key: "location", icon: "ri-map-pin-line", iconColor: "text-violet", iconBg: "bg-violet-50", type: "text" },
  ];

  return (
    <>
      <Navbar />
      <main className="profile-page">
        <div className="container py-5">
          <section className="profile-card mb-4">
            <div className="profile-cover">
              <img src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/4a8acdc8a7b54754399ef652077c11e9.png" alt="profile cover" />
              <button className="btn-logout" onClick={() => navigate("/")}>
                <i className="ri-logout-box-line me-1"></i>返回首頁
              </button>
            </div>

            <div className="profile-body px-4 px-md-5 pb-4">
              <div className="d-flex align-items-start gap-3 mb-4" style={{ marginTop: -48 }}>
                <div className="avatar-wrapper">
                  <div className="profile-avatar" onClick={() => avatarInputRef.current?.click()}>
                    <img src={avatarSrc} alt="avatar" />
                    <div className="avatar-overlay"><i className="ri-camera-line"></i></div>
                  </div>
                  <button className="avatar-camera" onClick={() => avatarInputRef.current?.click()}><i className="ri-camera-line"></i></button>
                  <input ref={avatarInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleAvatarChange} />
                </div>
                <div className="flex-grow-1 pt-5">
                  <h1 className="profile-name">{profile.name}</h1>
                  <p className="profile-email">chenxiaoming@example.com</p>
                </div>
                <button className="btn btn-violet ms-auto align-self-end" onClick={() => (isEditing ? handleCancel() : setIsEditing(true))}>
                  <i className={`${isEditing ? "ri-close-line" : "ri-edit-line"} me-1`}></i>
                  {isEditing ? "取消編輯" : "編輯資料"}
                </button>
              </div>

              <div className="row g-3 mb-4">
                {stats.map((stat) => (
                  <div className="col-6 col-md-3" key={stat.label}>
                    <div className="profile-stat">
                      <div className={`stat-top-bar ${stat.barBg}`}></div>
                      <div className={`stat-icon-box ${stat.iconBg}`}><i className={`${stat.icon} ${stat.iconColor}`}></i></div>
                      <div className="stat-number">{stat.num}</div>
                      <div className="stat-label">{stat.label}</div>
                    </div>
                  </div>
                ))}
              </div>
              <p className="profile-bio">{profile.bio}</p>
            </div>
          </section>

          <div className="profile-tabs mb-4">
            {[
              ["info", "基本資料"],
              ["security", "安全設定"],
              ["activity", "近期活動"],
              ["surveys", "我的問卷"],
            ].map(([key, label]) => (
              <button key={key} className={`tab-btn ${activeTab === key ? "active" : ""}`} onClick={() => setActiveTab(key)}>
                {label}
              </button>
            ))}
          </div>

          {activeTab === "info" && (
            <section className="profile-card-inner p-4 p-md-5">
              <h2 className="tab-title">基本資料</h2>
              <div className="row g-4">
                {infoFields.map((field) => (
                  <div className="col-md-6" key={field.key}>
                    <label className="auth-label">{field.label}</label>
                    {isEditing ? (
                      <div className="position-relative">
                        <div className={`field-icon-sm ${field.iconBg}`}><i className={`${field.icon} ${field.iconColor}`}></i></div>
                        <input className="form-control form-control-custom" type={field.type} value={editProfile[field.key]} onChange={(e) => setEditProfile((prev) => ({ ...prev, [field.key]: e.target.value }))} />
                      </div>
                    ) : (
                      <div className="profile-field">
                        <div className={`field-icon ${field.iconBg}`}><i className={`${field.icon} ${field.iconColor}`}></i></div>
                        <span className="field-value">{profile[field.key]}</span>
                      </div>
                    )}
                  </div>
                ))}
                <div className="col-12">
                  <label className="auth-label">自我介紹</label>
                  {isEditing ? (
                    <textarea className="form-control" rows={3} value={editProfile.bio} onChange={(e) => setEditProfile((prev) => ({ ...prev, bio: e.target.value }))} />
                  ) : (
                    <div className="profile-field"><p className="field-value m-0">{profile.bio}</p></div>
                  )}
                </div>
              </div>
              {isEditing && (
                <div className="edit-actions">
                  <button className="btn btn-violet" onClick={handleSave}>儲存變更</button>
                  <button className="btn btn-outline-secondary" onClick={handleCancel}>取消</button>
                  {saved && <span className="save-success"><i className="ri-checkbox-circle-line"></i> 已儲存</span>}
                </div>
              )}
            </section>
          )}

          {activeTab === "security" && (
            <section className="profile-card-inner p-4 p-md-5">
              <h2 className="tab-title">安全設定</h2>
              <div className="security-item">
                <div className="d-flex align-items-center gap-3">
                  <div className="security-icon bg-violet-50"><i className="ri-lock-password-line text-violet"></i></div>
                  <div>
                    <p className="security-label mb-0">密碼</p>
                    <p className="security-desc mb-0">建議定期更新密碼，提升帳號安全。</p>
                  </div>
                </div>
                <button className="btn-security-action" onClick={() => navigate("/change-password")}>變更密碼</button>
              </div>
              <div className="security-item">
                <div className="d-flex align-items-center gap-3">
                  <div className="security-icon bg-sky-50"><i className="ri-shield-check-line text-sky"></i></div>
                  <div>
                    <p className="security-label mb-0">雙因素驗證</p>
                    <p className="security-desc mb-0">透過第二層驗證保護登入流程。</p>
                  </div>
                </div>
                <button className="btn-security-action" onClick={() => navigate("/two-factor")}>設定</button>
              </div>
            </section>
          )}

          {activeTab === "activity" && (
            <section className="profile-card-inner p-4 p-md-5">
              <h2 className="tab-title">近期活動</h2>
              <div className="activity-list">
                {[
                  ["ri-upload-cloud-2-line", "匯入 customer_feedback.csv 到工作區", "2 小時前"],
                  ["ri-folder-add-line", "建立資料夾：2025 客戶分析", "昨天"],
                  ["ri-chat-3-line", "將問卷資料匯入 Chat 分析", "昨天"],
                  ["ri-file-excel-line", "儲存 Excel 分析報告", "3 天前"],
                ].map(([icon, text, time]) => (
                  <div className="activity-item" key={text}>
                    <div className="activity-icon bg-violet-50"><i className={`${icon} text-violet`}></i></div>
                    <div className="activity-text flex-grow-1">{text}</div>
                    <span className="activity-time">{time}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {activeTab === "surveys" && (
            <section className="profile-card-inner p-4 p-md-5">
              <h2 className="tab-title">我的問卷</h2>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {surveyRecords.map((survey) => (
                  <div key={`${survey.id}-${survey.code}`} className="profile-field" style={{ justifyContent: "space-between", gap: 16 }}>
                    <div>
                      <strong>{survey.title}</strong>
                      <div style={{ color: "var(--slate-400)", fontSize: 13 }}>
                        邀請碼 {survey.code} · {survey.responseCount} 份回覆 · {survey.createdAt}
                      </div>
                    </div>
                    <button className="btn btn-violet" onClick={() => setSelectedSurvey(survey.detail)}>查看詳情</button>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </main>
    </>
  );
}
