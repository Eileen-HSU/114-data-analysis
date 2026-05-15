import { useMemo, useRef, useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import SurveyDetailPage from "./components/SurveyDetailPage";
import { useAuth } from "../../hooks/AuthContext";
import { useActivity } from "../../hooks/ActivityContext";
import { apiUrl } from "../../lib/api";
import "./profile.css";

const DEFAULT_AVATAR = "https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/b181cfaad2165c1909b7c8fa8339cbe7.png";
const TWO_FACTOR_KEY_PREFIX = "dataanalysis_two_factor_enabled";
const AVATAR_STORAGE_KEY_PREFIX = "dataanalysis_avatar";

function getUserStorageId(user) {
  return user?.user_id || user?.email || "guest";
}

function getAvatarStorageKey(user) {
  return `${AVATAR_STORAGE_KEY_PREFIX}_${getUserStorageId(user)}`;
}

function getLocalSurveys(user) {
  const stored = Object.values(JSON.parse(localStorage.getItem("surveys") || "{}"));
  return stored.filter((survey) => {
    if (!user) return false;
    if (!survey.ownerId && !survey.ownerEmail) return false;
    return survey.ownerId === user?.user_id || survey.ownerEmail === user?.email;
  });
}

function getSurveyTime(createdAt) {
  const time = new Date(createdAt || 0).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function formatActivityTime(value) {
  const time = new Date(value).getTime();
  if (!time || Number.isNaN(time)) return "";
  const diff = Date.now() - time;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diff < minute) return "剛剛";
  if (diff < hour) return `${Math.floor(diff / minute)} 分鐘前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小時前`;

  return new Intl.DateTimeFormat("zh-TW", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function getUsageDays(createdAt) {
  const createdTime = new Date(createdAt || 0).getTime();
  if (!createdTime || Number.isNaN(createdTime)) return 0;

  const start = new Date(createdTime);
  start.setHours(0, 0, 0, 0);

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return Math.max(1, Math.floor((today - start) / (24 * 60 * 60 * 1000)) + 1);
}

export default function ProfilePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, updateUser } = useAuth(); // ── 從 AuthContext 取得登入用戶
  console.log('目前登入的 user：', user);
  const { activities, recordActivity, clearActivities } = useActivity();
  const avatarInputRef = useRef(null);
  const editSectionRef = useRef(null);
  const surveysSectionRef = useRef(null);
  const [activeTab, setActiveTab] = useState("info");
  const [isEditing, setIsEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);
  const [showTwoFactorNotice, setShowTwoFactorNotice] = useState(false);
  const [showPasswordNotice, setShowPasswordNotice] = useState(false);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [surveySearch, setSurveySearch] = useState("");
  const [surveySortOrder, setSurveySortOrder] = useState("desc");
  const [avatarSrc, setAvatarSrc] = useState(DEFAULT_AVATAR);
  const [profile, setProfile] = useState({
    name: "",
    phone: "",
    company: "",
    gender: "",
    location: "",
    bio: "",
    createdAt: "",
  });
  const [editProfile, setEditProfile] = useState(profile);
  const twoFactorStorageKey = `${TWO_FACTOR_KEY_PREFIX}_${getUserStorageId(user)}`;
  const avatarStorageKey = getAvatarStorageKey(user);

  // ── 載入個人資料 ──────────────────────────────────────────
  useEffect(() => {
    if (user === null) return;
    if (!user?.user_id) return;

    fetch(apiUrl(`/api/profile/${user.user_id}`))
      .then((res) => res.json())
      .then((data) => {
        const loaded = {
          name:     data.user_name    || "",
          phone:    data.phone_number || "",
          company:  data.company_name || "",
          gender:   data.gender       || "",
          location: data.location     || "",
          bio:      data.bio          || "",
          createdAt: data.created_at  || "",
        };
        setProfile(loaded);
        setEditProfile(loaded);
      })
      .catch((err) => console.error("載入個人資料失敗", err));
  }, [user]);

  useEffect(() => {
    setTwoFactorEnabled(localStorage.getItem(twoFactorStorageKey) === "true");
  }, [twoFactorStorageKey]);

  useEffect(() => {
    if (!user) return;
    const storedAvatar = localStorage.getItem(avatarStorageKey);
    const nextAvatar = storedAvatar || user.avatar || DEFAULT_AVATAR;
    setAvatarSrc(nextAvatar);
    if (storedAvatar && storedAvatar !== user.avatar) {
      updateUser({ avatar: storedAvatar });
    }
  }, [avatarStorageKey, updateUser, user]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("two_factor") !== "enabled") return;

    localStorage.setItem(twoFactorStorageKey, "true");
    setTwoFactorEnabled(true);
    setShowTwoFactorNotice(true);
    recordActivity({
      text: "啟用雙重驗證",
      icon: "ri-shield-check-line",
      iconBg: "bg-stat-teal",
      iconColor: "text-stat-teal",
    });
    navigate("/profile", { replace: true });
  }, [location.search, navigate, recordActivity, twoFactorStorageKey]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("password_changed") !== "1") return;

    setShowPasswordNotice(true);
    recordActivity({
      text: "密碼已修改",
      icon: "ri-lock-password-line",
      iconBg: "bg-stat-teal",
      iconColor: "text-stat-teal",
    });
    navigate("/profile", { replace: true });
  }, [location.search, navigate, recordActivity]);

  const localSurveys = useMemo(() => getLocalSurveys(user), [user, selectedSurvey, saved]);
  const surveyRecords = useMemo(() => localSurveys.map((survey, index) => ({
      id: survey.id || survey.code,
      title: survey.title,
      code: survey.code,
      createdAt: survey.createdAt,
      createdAtMs: survey.createdAtMs || getSurveyTime(survey.createdAt) + index,
      responseCount: survey.responses?.length || 0,
      status: "active",
      local: true,
      detail: survey,
    })), [localSurveys]);
  const visibleSurveyRecords = useMemo(() => {
    const keyword = surveySearch.trim().toLowerCase();

    return [...surveyRecords]
      .filter((survey) => {
        if (!keyword) return true;
        return [survey.title, survey.code]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(keyword));
      })
      .sort((a, b) => {
        const diff = a.createdAtMs - b.createdAtMs;
        return surveySortOrder === "asc" ? diff : -diff;
      });
  }, [surveyRecords, surveySearch, surveySortOrder]);

  if (selectedSurvey) {
    return <SurveyDetailPage survey={selectedSurvey} onBack={() => setSelectedSurvey(null)} />;
  }

  const handleAvatarChange = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (loadEvent) => {
      if (loadEvent.target?.result) {
        const nextAvatar = loadEvent.target.result;
        localStorage.setItem(avatarStorageKey, nextAvatar);
        setAvatarSrc(nextAvatar);
        updateUser({ avatar: nextAvatar });
        recordActivity({
          text: "更新個人頭像",
          icon: "ri-camera-line",
          iconBg: "bg-stat-mauve",
          iconColor: "text-stat-mauve",
        });
      }
    };
    reader.readAsDataURL(file);
  };

  const handleSave = async () => {
    if (!user?.user_id) {
      alert('請重新登入後再試');
      return;
    }

    try {
        const res = await fetch(apiUrl(`/api/profile/${user.user_id}`), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_name:    editProfile.name,
                phone_number: editProfile.phone,
                company_name: editProfile.company,
                gender:       editProfile.gender,
                location:        editProfile.location,
                bio:          editProfile.bio,
                updated_at:   new Date().toISOString(),

            }),
        });

        const result = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(result.error || '儲存失敗，請稍後再試');

        setProfile(editProfile);
        recordActivity({
          text: "更新個人資料",
          icon: "ri-user-settings-line",
          iconBg: "bg-violet-50",
          iconColor: "text-violet",
        });
        setSaved(true);
        setTimeout(() => {
            setSaved(false);
            setIsEditing(false);
        }, 900);

      } catch (err) {
          console.error('儲存失敗', err);
          alert(err.message || '儲存失敗，請稍後再試');
      }
  };

// 雙因子驗證開關
const handleDisable2FA = async () => {
  if (!window.confirm("確定要關閉雙因子驗證嗎？這會降低您的帳號安全性。")) return;

  console.log("打的URL:", apiUrl('/api/auth/2fa/disable'));
  try {
    const res = await fetch(apiUrl('/api/auth/2fa/disable'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${user.token}`,
      },
    });

    if (res.ok) {
      localStorage.setItem(twoFactorStorageKey, "false");
      setTwoFactorEnabled(false);
      recordActivity({
        text: "關閉雙重驗證",
        icon: "ri-shield-flash-line",
        iconBg: "bg-stat-coral",
        iconColor: "text-stat-coral",
      });
      alert("雙因子驗證已關閉");
    } else {
      const data = await res.json();

      console.log("後端回傳:", data);

      alert(data.error || "關閉失敗，請稍後再試");
    }
  } catch (err) {
    console.error("關閉 2FA 失敗", err);
    alert("網路錯誤");
  }
};

  const handleCancel = () => {
    setEditProfile(profile);
    setIsEditing(false);
  };

  const handleEditToggle = () => {
    if (isEditing) {
      handleCancel();
      return;
    }

    setActiveTab("info");
    setIsEditing(true);
    setTimeout(() => {
      editSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  };

  const scrollToSurveys = () => {
    setActiveTab("surveys");
    setTimeout(() => {
      surveysSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  };

  const stats = [
    { icon: "ri-bar-chart-line", iconColor: "text-stat-coral", iconBg: "bg-stat-coral", barBg: "bar-coral", num: surveyRecords.length, label: "問卷數", action: scrollToSurveys },
    { icon: "ri-user-line", iconColor: "text-stat-mauve", iconBg: "bg-stat-mauve", barBg: "bar-mauve", num: surveyRecords.reduce((sum, survey) => sum + survey.responseCount, 0), label: "總回覆" },
    { icon: "ri-folder-line", iconColor: "text-stat-sky", iconBg: "bg-stat-sky", barBg: "bar-sky", num: 0, label: "資料夾" },
    { icon: "ri-calendar-line", iconColor: "text-stat-teal", iconBg: "bg-stat-teal", barBg: "bar-teal", num: getUsageDays(profile.createdAt), label: "使用天數" },
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
                  <p className="profile-email">{user?.email || ""}</p> {/* ── 從 AuthContext 取得 email */}
                </div>
                <button className="btn btn-violet ms-auto align-self-end" onClick={handleEditToggle}>
                  <i className={`${isEditing ? "ri-close-line" : "ri-edit-line"} me-1`}></i>
                  {isEditing ? "取消編輯" : "編輯資料"}
                </button>
              </div>

              <div className="row g-3 mb-4">
                {stats.map((stat) => {
                  const StatTag = stat.action ? "button" : "div";
                  return (
                    <div className="col-6 col-md-3" key={stat.label}>
                      <StatTag
                        type={stat.action ? "button" : undefined}
                        className={`profile-stat ${stat.action ? "profile-stat-clickable" : ""}`}
                        onClick={stat.action}
                        aria-label={stat.action ? "查看我的問卷" : undefined}
                      >
                        <div className={`stat-top-bar ${stat.barBg}`}></div>
                        <div className={`stat-icon-box ${stat.iconBg}`}><i className={`${stat.icon} ${stat.iconColor}`}></i></div>
                        <div className="stat-number">{stat.num}</div>
                        <div className="stat-label">{stat.label}</div>
                      </StatTag>
                    </div>
                  );
                })}
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
            <section className="profile-card-inner p-4 p-md-5" ref={editSectionRef}>
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
                  <div className={`security-icon ${twoFactorEnabled ? "security-icon-enabled" : "bg-sky-50"}`}>
                    <i className={`ri-shield-check-line ${twoFactorEnabled ? "" : "text-sky"}`}></i>
                  </div>
                  <div>
                    <div className="security-title-row">
                      <p className="security-label mb-0">雙因素驗證</p>
                      <span className={`two-factor-status ${twoFactorEnabled ? "enabled" : "disabled"}`}>
                        {twoFactorEnabled ? "已開啟" : "未開啟"}
                      </span>
                    </div>
                    <p className="security-desc mb-0">
                      {twoFactorEnabled ? "登入時會要求輸入驗證碼。" : "透過第二層驗證保護登入流程。"}
                    </p>
                  </div>
                </div>
                <button
                  className={`two-factor-switch ${twoFactorEnabled ? "enabled" : ""}`}
                  onClick={() => {
                    if (twoFactorEnabled) {
                      // 如果已經開啟，點擊就是為了關閉
                      handleDisable2FA();
                    } else {
                      // 如果未開啟，跳轉到開啟頁面
                      navigate("/two-factor");
                    }
                  }}
                  type="button"
                  aria-label={twoFactorEnabled ? "關閉雙因素驗證" : "開啟雙因素驗證"}
                >
                  <span className="two-factor-switch-label">{twoFactorEnabled ? "ON" : "OFF"}</span>
                  <span className="two-factor-switch-knob"></span>
                </button>
              </div>
            </section>
          )}

          {activeTab === "activity" && (
            <section className="profile-card-inner p-4 p-md-5">
              <div className="activity-header">
                <h2 className="tab-title mb-0">近期活動</h2>
                {activities.length > 0 && (
                  <button className="activity-clear-btn" type="button" onClick={clearActivities}>
                    清除紀錄
                  </button>
                )}
              </div>
              <div className="activity-list">
                {activities.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">目前還沒有活動紀錄。</span>
                  </div>
                )}
                {activities.map((activity) => (
                  <div className="activity-item" key={activity.id}>
                    <div className={`activity-icon ${activity.iconBg || "bg-violet-50"}`}>
                      <i className={`${activity.icon || "ri-time-line"} ${activity.iconColor || "text-violet"}`}></i>
                    </div>
                    <div className="activity-main">
                      <span className="activity-text">{activity.text}</span>
                      <span className="activity-time">{formatActivityTime(activity.createdAt)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {activeTab === "surveys" && (
            <section className="profile-card-inner p-4 p-md-5" ref={surveysSectionRef}>
              <div className="surveys-toolbar">
                <div className="surveys-title-group">
                  <h2 className="tab-title mb-0">我的問卷</h2>
                  <div className="survey-search">
                    <i className="ri-search-line"></i>
                    <input
                      type="search"
                      value={surveySearch}
                      onChange={(event) => setSurveySearch(event.target.value)}
                      placeholder="搜尋問卷名稱或邀請碼"
                      aria-label="搜尋問卷"
                    />
                  </div>
                </div>
                <div className="survey-controls">
                  <div className="survey-sort-options" role="radiogroup" aria-label="問卷時間排序">
                    <label className="survey-sort-option">
                      <span>追蹤日期：由近到遠</span>
                      <input
                        type="radio"
                        name="survey-sort-order"
                        value="desc"
                        checked={surveySortOrder === "desc"}
                        onChange={() => setSurveySortOrder("desc")}
                      />
                    </label>
                    <label className="survey-sort-option">
                      <span>追蹤日期：由遠到近</span>
                      <input
                        type="radio"
                        name="survey-sort-order"
                        value="asc"
                        checked={surveySortOrder === "asc"}
                        onChange={() => setSurveySortOrder("asc")}
                      />
                    </label>
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {surveyRecords.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">目前還沒有建立問卷。</span>
                  </div>
                )}
                {surveyRecords.length > 0 && visibleSurveyRecords.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">找不到符合搜尋條件的問卷。</span>
                  </div>
                )}
                {visibleSurveyRecords.map((survey) => (
                  <div key={`${survey.id}-${survey.code}`} className="profile-field" style={{ justifyContent: "space-between", gap: 16 }}>
                    <div>
                      <strong>{survey.title}</strong>
                      <div style={{ color: "var(--slate-400)", fontSize: 13 }}>
                        邀請碼 {survey.code} · {survey.responseCount} 份回覆 · {survey.createdAt}
                      </div>
                    </div>
                    <button
                      className="btn btn-violet"
                      onClick={() => {
                        recordActivity({
                          text: `查看問卷「${survey.title}」`,
                          icon: "ri-survey-line",
                          iconBg: "bg-stat-coral",
                          iconColor: "text-stat-coral",
                        });
                        setSelectedSurvey(survey.detail);
                      }}
                    >
                      查看詳情
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </main>

      {showTwoFactorNotice && (
        <div className="profile-toast" role="status">
          <div className="profile-toast-icon">
            <i className="ri-checkbox-circle-line"></i>
          </div>
          <div>
            <strong>已開啟雙因子驗證</strong>
            <p>下次登入時會要求輸入驗證碼。</p>
          </div>
          <button onClick={() => setShowTwoFactorNotice(false)} aria-label="關閉通知">
            <i className="ri-close-line"></i>
          </button>
        </div>
      )}

      {showPasswordNotice && (
        <div className="profile-toast" role="status">
          <div className="profile-toast-icon">
            <i className="ri-checkbox-circle-line"></i>
          </div>
          <div>
            <strong>密碼已修改</strong>
            <p>你的登入密碼已成功更新。</p>
          </div>
          <button onClick={() => setShowPasswordNotice(false)} aria-label="關閉通知">
            <i className="ri-close-line"></i>
          </button>
        </div>
      )}
    </>
  );
}
