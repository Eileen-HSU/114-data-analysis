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

function getUserStorageId(user) {
  return user?.user_id || user?.email || "guest";
}

function getSurveyTime(createdAt) {
  const time = new Date(createdAt || 0).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function formatSurveyDeadline(deadlineAt) {
  if (!deadlineAt) return "未設定截止時間";
  const date = new Date(deadlineAt);
  if (Number.isNaN(date.getTime())) return deadlineAt;
  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
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
  const { user, updateUser } = useAuth();
  const { activities, recordActivity, clearActivities } = useActivity();
  const avatarInputRef = useRef(null);
  const editSectionRef = useRef(null);
  const securitySectionRef = useRef(null);
  const surveysSectionRef = useRef(null);
  const profileLoadedRef = useRef(false);
  const [activeTab, setActiveTab] = useState("info");
  const [isEditing, setIsEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);
  const [showTwoFactorNotice, setShowTwoFactorNotice] = useState(false);
  const [showPasswordNotice, setShowPasswordNotice] = useState(false);
  const [twoFactorModal, setTwoFactorModal] = useState(null);
  const [showDisableTwoFactorModal, setShowDisableTwoFactorModal] = useState(false);
  const [twoFactorPassword, setTwoFactorPassword] = useState("");
  const [showTwoFactorPassword, setShowTwoFactorPassword] = useState(false);
  const [twoFactorPasswordError, setTwoFactorPasswordError] = useState("");
  const [isDisablingTwoFactor, setIsDisablingTwoFactor] = useState(false);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [surveySearch, setSurveySearch] = useState("");
  const [surveySortOrder, setSurveySortOrder] = useState("desc");
  const [surveyVersion, setSurveyVersion] = useState(0);
  const [avatarSrc, setAvatarSrc] = useState(DEFAULT_AVATAR);
  
  const [apiSurveys, setApiSurveys] = useState([]);
  const [isLoadingSurveys, setIsLoadingSurveys] = useState(false);

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

  const showProfileAlert = ({ type = "error", title, message }) => {
    setTwoFactorModal({ type, title, message });
  };

  const alert = (message) => {
    const text = String(message || "");
    if (text.includes("2MB")) {
      showProfileAlert({
        type: "warning",
        title: "圖片太大",
        message: "請選擇小於 2MB 的圖片後再上傳。",
      });
      return;
    }

    if (text.includes("頭像")) {
      showProfileAlert({
        type: "error",
        title: "頭像上傳失敗",
        message: "目前無法更新頭像，請稍後再試。",
      });
      return;
    }

    if (text.includes("儲存")) {
      showProfileAlert({
        type: "error",
        title: "儲存失敗",
        message: "目前無法儲存資料，請稍後再試。",
      });
      return;
    }

    showProfileAlert({
      type: "error",
      title: text.includes("登入") ? "請重新登入" : "操作失敗",
      message: text.includes("登入")
        ? "登入狀態已失效，請重新登入後再試。"
        : "目前無法完成操作，請稍後再試。",
    });
  };

  // ── 未登入跳轉 ────────────────────────────────────────────
  useEffect(() => {
    if (user === null) {
      navigate("/", { replace: true });
    }
  }, [navigate, user]);

  // ── 載入個人資料 ──────────────────
  useEffect(() => {
    if (!user?.token || !user?.user_id) return;

    fetch(apiUrl(`/api/profile/${user.user_id}`), {
      headers: { 'Authorization': `Bearer ${user.token}` }
    })
      .then((res) => res.json())
      .then((data) => {
        const loaded = {
          name:      data.user_name    || "",
          phone:     data.phone_number || "",
          company:   data.company_name || "",
          gender:    data.gender       || "",
          location:  data.location     || "",
          bio:       data.bio          || "",
          createdAt: data.created_at   || "",
        };
        setProfile(loaded);

        if (!profileLoadedRef.current) {
          setEditProfile(loaded);
          profileLoadedRef.current = true;
        }

        const oldKey = `dataanalysis_avatar_${getUserStorageId(user)}`;
        localStorage.removeItem(oldKey);
        setAvatarSrc(data.avatar_url || DEFAULT_AVATAR);
        updateUser({ avatar: data.avatar_url || DEFAULT_AVATAR });
      })
      .catch((err) => console.error("載入個人資料失敗", err));
  }, [user?.token, user?.user_id, updateUser]); 

  useEffect(() => {
    if (!user?.token) return;

    setIsLoadingSurveys(true);
    fetch(apiUrl("/api/surveys/mine"), {
      headers: { 'Authorization': `Bearer ${user.token}` }
    })
      .then((res) => {
        if (!res.ok) throw new Error("撈取問卷失敗");
        return res.json();
      })
      .then((data) => {
        setApiSurveys(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        console.error("載入問卷失敗:", err);
      })
      .finally(() => {
        setIsLoadingSurveys(false);
      });
  }, [user?.token, surveyVersion]); 

  useEffect(() => {
    setTwoFactorEnabled(localStorage.getItem(twoFactorStorageKey) === "true");
  }, [twoFactorStorageKey]);

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

  const surveyRecords = useMemo(() => {
    return apiSurveys.map((survey, index) => {
      const code = survey.code || survey.access_code;
      return {
        id: survey.id || code,
        title: survey.title || survey.survey_name || "未命名問卷", 
        code,
        createdAt: survey.createdAt || survey.created_at,
        deadlineAt: survey.deadlineAt || survey.deadline_at,
        createdAtMs: getSurveyTime(survey.createdAt || survey.created_at) + index,
        responseCount: survey.responses?.length || survey.response_count || 0,
        status: survey.status || "active",
        local: false,
        detail: survey,
      };
    });
  }, [apiSurveys]);

  const handleOpenSurveyDetail = async (survey) => {
    const auth = user || JSON.parse(localStorage.getItem("dataanalysis_auth") || "{}");
    const code = encodeURIComponent(survey.code || survey.access_code);

    try {
      const [surveyRes, responsesRes] = await Promise.all([
        fetch(apiUrl(`/api/surveys/${code}`)),
        fetch(apiUrl(`/api/surveys/${code}/responses`), {
          headers: {
            ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
          },
        }),
      ]);

      const surveyData = await surveyRes.json().catch(() => ({}));
      if (!surveyRes.ok) {
        throw new Error(surveyData.error || "載入問卷資訊失敗");
      }

      const responsesData = await responsesRes.json().catch(() => ({}));
      if (!responsesRes.ok) {
        throw new Error(responsesData.error || "載入問卷回覆失敗");
      }

      setSelectedSurvey({
        ...survey,
        title: surveyData.title || survey.title,
        description: surveyData.description,
        identity_mode: surveyData.identity_mode,
        identityMode: surveyData.identity_mode,
        deadline_at: surveyData.deadline_at,
        deadlineAt: surveyData.deadline_at,
        questions: surveyData.questions || [],
        responses: responsesData.responses || [],
      });
    } catch (error) {
      console.error("載入問卷詳情失敗:", error);
      alert(error.message || "載入問卷詳情失敗");
    }
  };

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

  const updateSurveyDeadline = async (survey, nextDeadlineAt) => {
    if (new Date(nextDeadlineAt).getTime() <= Date.now()) {
      throw new Error("截止時間必須晚於現在。");
    }

    const auth = user || JSON.parse(localStorage.getItem("dataanalysis_auth") || "{}");
    const response = await fetch(apiUrl(`/api/surveys/${encodeURIComponent(survey.code || survey.access_code)}/deadline`), {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
      },
      body: JSON.stringify({ deadline_at: nextDeadlineAt }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || "截止時間更新失敗");
    }

    setSurveyVersion((version) => version + 1);
    setSelectedSurvey(null); 

    recordActivity({
      text: `修改問卷「${survey.title || survey.survey_name}」截止時間`,
      icon: "ri-time-line",
      iconBg: "bg-stat-sky",
      iconColor: "text-stat-sky",
    });
    return data;
  };

  if (selectedSurvey) {
    return <SurveyDetailPage survey={selectedSurvey} onBack={() => setSelectedSurvey(null)} onUpdateDeadline={updateSurveyDeadline} />;
  }

  const handleAvatarChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const img = new Image();
      img.src = event.target.result;
      img.onload = () => {
        const canvas = document.createElement('canvas');
        const MAX_WIDTH = 150;
        const MAX_HEIGHT = 150;
        let width = img.width;
        let height = img.height;

        if (width > height) {
          if (width > MAX_WIDTH) {
            height *= MAX_WIDTH / width;
            width = MAX_WIDTH;
          }
        } else {
          if (height > MAX_HEIGHT) {
            width *= MAX_HEIGHT / height;
            height = MAX_HEIGHT;
          }
        }

        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);
        const compressedBase64 = canvas.toDataURL('image/jpeg', 0.6);
        setAvatarSrc(compressedBase64);
      };
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
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user.token}`,
        },
        body: JSON.stringify({
          user_name:    editProfile.name,
          phone_number: editProfile.phone,
          company_name: editProfile.company,
          gender:       editProfile.gender,
          location:     editProfile.location,
          bio:          editProfile.bio,
          avatar_url:   avatarSrc,
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

  const closeDisableTwoFactorModal = () => {
    if (isDisablingTwoFactor) return;
    setShowDisableTwoFactorModal(false);
    setTwoFactorPassword("");
    setShowTwoFactorPassword(false);
    setTwoFactorPasswordError("");
  };

  const handleDisable2FA = () => {
    setTwoFactorPassword("");
    setShowTwoFactorPassword(false);
    setTwoFactorPasswordError("");
    setShowDisableTwoFactorModal(true);
  };

  const confirmDisable2FA = async (e) => {
    e.preventDefault();
    const password = twoFactorPassword.trim();
    if (!password) {
      setTwoFactorPasswordError("請先輸入密碼。");
      return;
    }

    setIsDisablingTwoFactor(true);
    setTwoFactorPasswordError("");
    try {
      const res = await fetch(apiUrl('/api/auth/2fa/disable'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user?.token}` },
        body: JSON.stringify({ email: user?.email, password }),
      });
      await res.json().catch(() => ({}));
      if (res.ok) {
        localStorage.setItem(twoFactorStorageKey, "false");
        setTwoFactorEnabled(false);
        setShowDisableTwoFactorModal(false);
        setTwoFactorPassword("");
        setShowTwoFactorPassword(false);
        recordActivity({
          text: "關閉雙重驗證",
          icon: "ri-shield-flash-line",
          iconBg: "bg-stat-coral",
          iconColor: "text-stat-coral",
        });
        setTwoFactorModal({
          type: "success",
          title: "已關閉雙因子驗證",
          message: "雙因子驗證已成功關閉，之後登入時不會再要求輸入驗證碼。",
        });
      } else {
        setTwoFactorPasswordError("密碼輸入錯誤，請重新輸入。");
      }
    } catch (err) {
      console.error("2FA Disable Error:", err);
      setTwoFactorPasswordError("伺服器發生錯誤，請稍後再試。");
    } finally {
      setIsDisablingTwoFactor(false);
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

  const scrollToInfo = () => {
    setActiveTab("info");
    setTimeout(() => {
      editSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  };

  const scrollToSecurity = () => {
    setActiveTab("security");
    setTimeout(() => {
      securitySectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  };

  const scrollToSurveys = () => {
    setActiveTab("surveys");
    setTimeout(() => {
      surveysSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  };

  const dashboardCards = [
    { icon: "ri-profile-line", iconColor: "text-stat-mauve", iconBg: "bg-stat-mauve", barBg: "bar-mauve", label: "基本資料", action: scrollToInfo, activeKey: "info", ariaLabel: "查看基本資料" },
    { icon: "ri-shield-keyhole-line", iconColor: "text-stat-sky", iconBg: "bg-stat-sky", barBg: "bar-sky", label: "安全設定", action: scrollToSecurity, activeKey: "security", ariaLabel: "查看安全設定" },
    { icon: "ri-bar-chart-line", iconColor: "text-stat-coral", iconBg: "bg-stat-coral", barBg: "bar-coral", num: surveyRecords.length, label: "問卷數", action: scrollToSurveys, activeKey: "surveys" },
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
        <div className="profile-container py-4">
          <section className="profile-card mb-4">
            <div className="profile-cover">
              <img src="https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/4a8acdc8a7b54754399ef652077c11e9.png" alt="profile cover" />
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
                  <p className="profile-email">{user?.email || ""}</p>
                </div>
              </div>

              <div className="row g-3 mb-4">
                {dashboardCards.map((card) => {
                  const CardTag = card.action ? "button" : "div";
                  return (
                    <div className="col-6 col-md-3" key={card.label}>
                      <CardTag
                        type={card.action ? "button" : undefined}
                        className={`profile-stat ${card.action ? "profile-stat-clickable" : ""} ${card.activeKey === activeTab ? "profile-stat-active" : ""}`}
                        onClick={card.action}
                        aria-label={card.ariaLabel || (card.action ? "查看我的問卷" : undefined)}
                      >
                        <div className={`stat-top-bar ${card.barBg}`}></div>
                        <div className={`stat-icon-box ${card.iconBg}`}><i className={`${card.icon} ${card.iconColor}`}></i></div>
                        {typeof card.num === "number" && <div className="stat-number">{card.num}</div>}
                        <div className="stat-label">{card.label}</div>
                      </CardTag>
                    </div>
                  );
                })}
              </div>
              <p className="profile-bio">{profile.bio}</p>
            </div>
          </section>

          <div className="profile-tabs mb-4">
            {[
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
              <div className="profile-section-header">
                <h2 className="tab-title mb-0">基本資料</h2>
                <button className="btn btn-violet" onClick={handleEditToggle}>
                  <i className={`${isEditing ? "ri-close-line" : "ri-edit-line"} me-1`}></i>
                  {isEditing ? "取消編輯" : "編輯資料"}
                </button>
              </div>
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
            <section className="profile-card-inner p-4 p-md-5" ref={securitySectionRef}>
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
                      handleDisable2FA();
                    } else {
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
                {!isLoadingSurveys && surveyRecords.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">目前還沒有建立問卷。</span>
                  </div>
                )}
                {!isLoadingSurveys && surveyRecords.length > 0 && visibleSurveyRecords.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">找不到符合搜尋條件的問卷。</span>
                  </div>
                )}
                {!isLoadingSurveys && visibleSurveyRecords.map((survey) => (
                  <div key={`${survey.id}-${survey.code}`} className="profile-field" style={{ justifyContent: "space-between", gap: 16 }}>
                    <div>
                      <strong>{survey.title}</strong>
                      <div style={{ color: "var(--slate-400)", fontSize: 13 }}>
                        邀請碼 {survey.code} · {survey.responseCount} 份回覆 · {survey.createdAt}
                      </div>
                      <div className="survey-deadline-meta">
                        <i className="ri-time-line"></i>
                        截止 {formatSurveyDeadline(survey.deadlineAt)}
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
                        handleOpenSurveyDetail(survey);
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

      {showDisableTwoFactorModal && (
        <div className="profile-modal-backdrop" onClick={closeDisableTwoFactorModal}>
          <form className="profile-confirm-modal" role="dialog" aria-modal="true" onSubmit={confirmDisable2FA} onClick={(e) => e.stopPropagation()}>
            <div className="profile-confirm-icon">
              <i className="ri-shield-keyhole-line"></i>
            </div>
            <h3>關閉雙因子驗證</h3>
            <p>請輸入目前的登入密碼，確認是你本人操作。</p>
            <label className="profile-confirm-label" htmlFor="disable-2fa-password">密碼</label>
            <div className="profile-confirm-input-wrap">
              <input
                id="disable-2fa-password"
                className={`profile-confirm-input ${twoFactorPasswordError ? "has-error" : ""}`}
                type={showTwoFactorPassword ? "text" : "password"}
                value={twoFactorPassword}
                onChange={(e) => {
                  setTwoFactorPassword(e.target.value);
                  setTwoFactorPasswordError("");
                }}
                placeholder="請輸入密碼"
                autoFocus
              />
              <button
                className="profile-confirm-eye"
                type="button"
                onClick={() => setShowTwoFactorPassword((prev) => !prev)}
                aria-label={showTwoFactorPassword ? "隱藏密碼" : "顯示密碼"}
              >
                <i className={showTwoFactorPassword ? "ri-eye-off-line" : "ri-eye-line"}></i>
                <span>{showTwoFactorPassword ? "隱藏" : "顯示"}</span>
              </button>
            </div>
            {twoFactorPasswordError && <div className="profile-confirm-error">{twoFactorPasswordError}</div>}
            <div className="profile-confirm-actions">
              <button className="profile-confirm-secondary" type="button" onClick={closeDisableTwoFactorModal} disabled={isDisablingTwoFactor}>
                取消
              </button>
              <button className="profile-confirm-danger" type="submit" disabled={isDisablingTwoFactor}>
                {isDisablingTwoFactor ? "確認中..." : "確認關閉"}
              </button>
            </div>
          </form>
        </div>
      )}

      {twoFactorModal && (
        <div className="profile-modal-backdrop" onClick={() => setTwoFactorModal(null)}>
          <div className={`profile-alert-modal ${twoFactorModal.type}`} role="alertdialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className="profile-alert-icon">
              <i className={twoFactorModal.type === "success" ? "ri-checkbox-circle-line" : twoFactorModal.type === "warning" ? "ri-error-warning-line" : "ri-close-circle-line"}></i>
            </div>
            <div className="profile-alert-content">
              <h3>{twoFactorModal.title}</h3>
              <p>{twoFactorModal.message}</p>
            </div>
            <button className="profile-alert-primary" type="button" onClick={() => setTwoFactorModal(null)}>
              知道了
            </button>
          </div>
        </div>
      )}
    </>
  );
}