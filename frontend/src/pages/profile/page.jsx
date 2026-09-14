import { useMemo, useRef, useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import SurveyDetailPage from "./components/SurveyDetailPage";
import { useAuth } from "../../hooks/AuthContext";
import { useActivity } from "../../hooks/ActivityContext";
import { apiUrl } from "../../lib/api";
import { useLanguage } from "../../context/LanguageContext";
import "./profile.css";

const genderLabel = (value) => ({ "男": "Male", "女": "Female", "其他": "Other", "不願透露": "Prefer not to say" }[value] || value);

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
  if (!deadlineAt) return "No deadline set";
  const date = new Date(deadlineAt);
  if (Number.isNaN(date.getTime())) return deadlineAt;
  return new Intl.DateTimeFormat("en-US", {
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

  if (diff < minute) return "Just now";
  if (diff < hour) return `${Math.floor(diff / minute)}  minutes ago`;
  if (diff < day) return `${Math.floor(diff / hour)}  hours ago`;

  return new Intl.DateTimeFormat("en-US", {
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
  const { user, updateUser, profileCache } = useAuth();
  const { language, t } = useLanguage();
  const { activities, recordActivity, clearActivities } = useActivity();
  const avatarInputRef = useRef(null);
  const editSectionRef = useRef(null);
  const securitySectionRef = useRef(null);
  const surveysSectionRef = useRef(null);
  const profileLoadedRef = useRef(false);
  const [activeTab, setActiveTab] = useState("info");
  const [isEditing, setIsEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(user?.email_2fa_enabled === true);
  const [showTwoFactorNotice, setShowTwoFactorNotice] = useState(false);
  const [showPasswordNotice, setShowPasswordNotice] = useState(false);
  const [twoFactorModal, setTwoFactorModal] = useState(null);
  const [showDisableTwoFactorModal, setShowDisableTwoFactorModal] = useState(false);
  const [twoFactorPassword, setTwoFactorPassword] = useState("");
  const [showTwoFactorPassword, setShowTwoFactorPassword] = useState(false);
  const [twoFactorPasswordError, setTwoFactorPasswordError] = useState("");
  const [isDisablingTwoFactor, setIsDisablingTwoFactor] = useState(false);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [isLoadingSurveyDetail, setIsLoadingSurveyDetail] = useState(false);
  const [surveySearch, setSurveySearch] = useState("");
  const [surveySortOrder, setSurveySortOrder] = useState("desc");
  const [surveyVersion, setSurveyVersion] = useState(0);
  const [avatarSrc, setAvatarSrc] = useState(DEFAULT_AVATAR);

  const [apiSurveys, setApiSurveys] = useState([]);
  const [isLoadingSurveys, setIsLoadingSurveys] = useState(false);
  const [hasLoadedSurveys, setHasLoadedSurveys] = useState(false);

  const [profile, setProfile] = useState({
    name: "",
    phone: "",
    company: "",
    gender: "",
    location: "",
    bio: "",
    createdAt: "",
    language: language,
  });
  const [editProfile, setEditProfile] = useState(profile);
  const twoFactorStorageKey = `${TWO_FACTOR_KEY_PREFIX}_${getUserStorageId(user)}`;

  const getAuthHeader = () =>
    user?.token ? { Authorization: `Bearer ${user.token}` } : {};

  const showProfileAlert = ({ type = "error", title, message }) => {
    setTwoFactorModal({ type, title, message });
  };

  const alert = (message) => {
    const text = String(message || "");
    if (text.includes("2MB")) {
      showProfileAlert({
        type: "warning",
        title: "Image too large",
        message: "Please upload an image smaller than 2 MB.",
      });
      return;
    }

    if (text.includes("Profile picture")) {
      showProfileAlert({
        type: "error",
        title: "Profile picture upload failed",
        message: "Unable to update your profile picture. Please try again later.",
      });
      return;
    }

    if (text.includes("Save")) {
      showProfileAlert({
        type: "error",
        title: "Save failed",
        message: "Unable to save your information. Please try again later.",
      });
      return;
    }

    showProfileAlert({
      type: "error",
      title: text.includes("Log in") ? "Please log in again" : "Action failed",
      message: text.includes("Log in")
        ? "Your session has expired. Please log in and try again."
        : "Unable to complete this action. Please try again later.",
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

    profileLoadedRef.current = false;

    // 有 cache 先用
    if (profileCache) {
      const loaded = {
        name:      profileCache.user_name    || "",
        phone:     profileCache.phone_number || "",
        company:   profileCache.company_name || "",
        gender:    profileCache.gender       || "",
        location:  profileCache.location     || "",
        bio:       profileCache.bio          || "",
        createdAt: profileCache.created_at   || "",
        language: language,
      };
      setProfile(loaded);
      if (!profileLoadedRef.current) {
        setEditProfile(loaded);
        profileLoadedRef.current = true;
      }
      setAvatarSrc(profileCache.avatar_url || DEFAULT_AVATAR);
    }

    // 背景打 API 確保最新
    fetch(apiUrl(`/api/profile/${user.user_id}`), {
      headers: { Authorization: `Bearer ${user.token}` },
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
          language: language,
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
      .catch((err) => console.error("Failed to load profile", err));
  }, [user?.token, user?.user_id, updateUser]);

  useEffect(() => {
    if (!user?.token) {
      setHasLoadedSurveys(true);
      return;
    }

    setHasLoadedSurveys(false);
    setIsLoadingSurveys(true);
    fetch(apiUrl("/api/surveys/mine"), {
      headers: { Authorization: `Bearer ${user.token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch surveys");
        return res.json();
      })
      .then((data) => {
        setApiSurveys(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        console.error("Failed to load surveys:", err);
      })
      .finally(() => {
        setIsLoadingSurveys(false);
        setHasLoadedSurveys(true);
      });
  }, [user?.token, surveyVersion]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("two_factor") !== "enabled") return;

    localStorage.setItem(twoFactorStorageKey, "true");
    setTwoFactorEnabled(true);
    setShowTwoFactorNotice(true);
    recordActivity({
      text: "Enable two-factor authentication",
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
      text: "Password updated",
      icon: "ri-lock-password-line",
      iconBg: "bg-stat-teal",
      iconColor: "text-stat-teal",
    });
    navigate("/profile", { replace: true });
  }, [location.search, navigate, recordActivity]);

  const surveyRecords = useMemo(() => {
    return apiSurveys.map((survey, index) => {
      const code = survey.code || survey.access_code;
      const shortCode = survey.shortCode || survey.short_code;
      return {
        id: survey.id || code,
        title: survey.title || survey.survey_name || "Untitled survey",
        code,
        shortCode,
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
    const headers = {
      "Content-Type": "application/json",
      ...getAuthHeader(),
    };

    const rawCode = survey.code || survey.access_code;

    if (!rawCode) {
      alert("Survey code not found");
      return;
    }

    const code = encodeURIComponent(rawCode);

    setIsLoadingSurveyDetail(true);

    try {
      const [surveyRes, responsesRes] = await Promise.all([
        fetch(apiUrl(`/api/surveys/${code}`), { headers }),
        fetch(apiUrl(`/api/surveys/${code}/responses`), { headers }),
      ]);

      const surveyData = await surveyRes.json().catch(() => ({}));
      const responsesData = await responsesRes.json().catch(() => ({}));

      if (!surveyRes.ok) {
        throw new Error(surveyData.error || "Failed to load survey data");
      }

      if (!responsesRes.ok) {
        throw new Error(responsesData.error || "Failed to load survey responses");
      }

      setSelectedSurvey({
        ...survey,

        template_id: surveyData.template_id || survey.template_id,

        title: surveyData.title || survey.title,

        access_code: surveyData.access_code || rawCode,
        code: surveyData.access_code || rawCode,

        created_at: surveyData.created_at || survey.created_at,
        createdAt: surveyData.created_at || survey.createdAt,

        deadline_at: survey.deadline_at,
        deadlineAt: survey.deadlineAt,

        short_code: survey.short_code || survey.shortCode,
        shortCode: survey.shortCode || survey.short_code,

        questions: Array.isArray(surveyData.questions)
          ? surveyData.questions
          : [],

        responses: Array.isArray(responsesData.responses)
          ? responsesData.responses
          : [],
      });
    } catch (error) {
      console.error("Failed to load survey details:", error);
      alert(error.message || "Failed to load survey details");
    } finally {
      setIsLoadingSurveyDetail(false);
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

  const requestedSurveyCode = new URLSearchParams(location.search).get("survey");

  useEffect(() => {
    if (selectedSurvey) return;
    if (!requestedSurveyCode) return;
    if (!hasLoadedSurveys) return;

    const targetSurvey = surveyRecords.find((survey) => survey.code === requestedSurveyCode);
    if (!targetSurvey) {
      alert("Failed to load survey details");
      navigate("/profile", { replace: true });
      return;
    }

    handleOpenSurveyDetail(targetSurvey);
    navigate("/profile", { replace: true });
  }, [hasLoadedSurveys, requestedSurveyCode, navigate, selectedSurvey, surveyRecords]);

  const updateSurveyDeadline = async (survey, nextDeadlineAt) => {
    if (new Date(nextDeadlineAt).getTime() <= Date.now()) {
      throw new Error("The deadline must be later than now.");
    }

    const headers = { "Content-Type": "application/json", ...getAuthHeader() };
    const response = await fetch(
      apiUrl(`/api/surveys/${encodeURIComponent(survey.code || survey.access_code)}/deadline`),
      {
        method: "PATCH",
        headers,
        body: JSON.stringify({ deadline_at: nextDeadlineAt }),
      }
    );

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || "Failed to update deadline");
    }

    setSurveyVersion((version) => version + 1);
    setSelectedSurvey(null);

    recordActivity({
      text: `Updated the deadline for survey: ${survey.title || survey.survey_name} `,
      icon: "ri-time-line",
      iconBg: "bg-stat-sky",
      iconColor: "text-stat-sky",
    });
    return data;
  };

  if (selectedSurvey) {
    return (
      <SurveyDetailPage
        survey={selectedSurvey}
        onBack={() => setSelectedSurvey(null)}
        onUpdateDeadline={updateSurveyDeadline}
        onImportToChat={({ survey, questions, responses, sessionTitle, message }) => {
          navigate("/workspace", {
            state: {
              surveyImport: {
                sessionTitle,
                message,
                surveyDetail: { ...survey, questions, responses },
              },
            },
          });
        }}
      />
    );
  }

  if (isLoadingSurveyDetail || requestedSurveyCode) {
    return (
      <>
        <Navbar />
        <main className="profile-page profile-loading-page">
          <div className="profile-survey-loading" role="status" aria-live="polite">
            <div className="profile-survey-loading-icon">
              <i className="ri-loader-4-line ri-spin"></i>
            </div>
            <h1>Loading survey details...</h1>
            <p>Preparing questions, statistics, and responses. Please wait.</p>
          </div>
        </main>
      </>
    );
  }

  // 頭貼壓縮
  const handleAvatarChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const img = new Image();
      img.src = event.target.result;
      img.onload = async () => {
        const canvas = document.createElement('canvas');
        const MAX_SIZE = 300;
        let width = img.width;
        let height = img.height;
        if (width > height) {
          if (width > MAX_SIZE) { height = Math.round(height * MAX_SIZE / width); width = MAX_SIZE; }
        } else {
          if (height > MAX_SIZE) { width = Math.round(width * MAX_SIZE / height); height = MAX_SIZE; }
        }
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);
        const compressedBase64 = canvas.toDataURL('image/jpeg', 0.9);
        setAvatarSrc(compressedBase64);

        // 立刻儲存頭像
        try {
          const res = await fetch(apiUrl(`/api/profile/${user.user_id}`), {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${user.token}`,
            },
            body: JSON.stringify({ avatar_url: compressedBase64 }),
          });
          if (!res.ok) throw new Error("Failed to save profile picture");
          updateUser({ avatar: compressedBase64 });
        } catch (err) {
          console.error("Profile picture upload failed", err);
        }
      };
    };
    reader.readAsDataURL(file);
  };

  const handleSave = async () => {
    if (!user?.user_id) {
      alert("Please log in again and retry");
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
          language:     editProfile.language,
          avatar_url:   avatarSrc,
          updated_at:   new Date().toISOString(),
        }),
      });

      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.error || "Save failed. Please try again later.");

      setProfile(editProfile);
      recordActivity({
        text: "Updated profile",
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
      console.error("Save failed", err);
      alert(err.message || "Save failed. Please try again later.");
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
      setTwoFactorPasswordError("Please enter your password first.");
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
          text: "Disable two-factor authentication",
          icon: "ri-shield-flash-line",
          iconBg: "bg-stat-coral",
          iconColor: "text-stat-coral",
        });
        setTwoFactorModal({
          type: "success",
          title: "Two-factor authentication disabled",
          message: "Two-factor authentication is now disabled. A verification code will no longer be required when logging in.",
        });
      } else {
        setTwoFactorPasswordError("Incorrect password. Please try again.");
      }
    } catch (err) {
      console.error("2FA Disable Error:", err);
      setTwoFactorPasswordError("A server error occurred. Please try again later.");
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
    { icon: "ri-profile-line", iconColor: "text-stat-mauve", iconBg: "bg-stat-mauve", barBg: "bar-mauve", label: "Profile", action: scrollToInfo, activeKey: "info", ariaLabel: "View profile" },
    { icon: "ri-shield-keyhole-line", iconColor: "text-stat-sky", iconBg: "bg-stat-sky", barBg: "bar-sky", label: "Security settings", action: scrollToSecurity, activeKey: "security", ariaLabel: "View security settings" },
    { icon: "ri-bar-chart-line", iconColor: "text-stat-coral", iconBg: "bg-stat-coral", barBg: "bar-coral", num: surveyRecords.length, loading: isLoadingSurveys, label: "Surveys", action: scrollToSurveys, activeKey: "surveys" },
    { icon: "ri-calendar-line", iconColor: "text-stat-teal", iconBg: "bg-stat-teal", barBg: "bar-teal", num: getUsageDays(profile.createdAt), label: "Days active" },
  ];

  const infoFields = [
    { label: "Name", key: "name", icon: "ri-user-line", iconColor: "text-violet", iconBg: "bg-violet-50", type: "text" },
    { label: "Phone", key: "phone", icon: "ri-smartphone-line", iconColor: "text-sky", iconBg: "bg-sky-50", type: "tel" },
    { label: "Company / organization", key: "company", icon: "ri-building-line", iconColor: "text-cyan", iconBg: "bg-cyan-50", type: "text" },
    { label: "Gender", key: "gender", icon: "ri-user-heart-line", iconColor: "text-teal", iconBg: "bg-teal-50", type: "text" },
    { label: "Location", key: "location", icon: "ri-map-pin-line", iconColor: "text-violet", iconBg: "bg-violet-50", type: "text" },
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
                  <p className="profile-bio">{profile.bio}</p>
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
                        aria-label={card.ariaLabel || (card.action ? "View my surveys" : undefined)}
                      >
                        <div className={`stat-top-bar ${card.barBg}`}></div>
                        <div className={`stat-icon-box ${card.iconBg}`}><i className={`${card.icon} ${card.iconColor}`}></i></div>
                        {card.loading ? (
                          <div className="stat-number stat-number-loading" aria-label={`${card.label}Loading`}>
                            <i className="ri-loader-4-line ri-spin"></i>
                          </div>
                        ) : (
                          typeof card.num === "number" && <div className="stat-number">{card.num}</div>
                        )}
                        <div className="stat-label">{card.label}</div>
                      </CardTag>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          <div className="profile-tabs mb-4">
            {[
              ["activity", "Recent activity"],
              ["surveys", "My surveys"],
            ].map(([key, label]) => (
              <button key={key} className={`tab-btn ${activeTab === key ? "active" : ""}`} onClick={() => setActiveTab(key)}>
                {label}
              </button>
            ))}
          </div>

          {activeTab === "info" && (
            <section className="profile-card-inner p-4 p-md-5" ref={editSectionRef}>
              <div className="profile-section-header">
                <h2 className="tab-title mb-0">Profile</h2>
                <button className="btn btn-violet" onClick={handleEditToggle}>
                  <i className={`${isEditing ? "ri-close-line" : "ri-edit-line"} me-1`}></i>
                  {isEditing ? "Cancel editing" : "Edit profile"}
                </button>
              </div>
              <div className="row g-4">
                {infoFields.map((field) => (
                  <div className="col-md-6" key={field.key}>
                    <label className="auth-label">{field.label}</label>
                    {isEditing ? (
                      <div className="position-relative">
                        <div className={`field-icon-sm ${field.iconBg}`}><i className={`${field.icon} ${field.iconColor}`}></i></div>
                        <input className="form-control form-control-custom" type={field.type} value={field.key === "gender" ? genderLabel(editProfile[field.key]) : editProfile[field.key]} onChange={(e) => setEditProfile((prev) => ({ ...prev, [field.key]: e.target.value }))} />
                      </div>
                    ) : (
                      <div className="profile-field">
                        <div className={`field-icon ${field.iconBg}`}><i className={`${field.icon} ${field.iconColor}`}></i></div>
                        <span className="field-value">{field.key === "gender" ? genderLabel(profile[field.key]) : profile[field.key]}</span>
                      </div>
                    )}
                  </div>
                ))}
                <div className="col-12">
                  <label className="auth-label">About you</label>
                  {isEditing ? (
                    <textarea className="form-control" rows={3} value={editProfile.bio} onChange={(e) => setEditProfile((prev) => ({ ...prev, bio: e.target.value }))} />
                  ) : (
                    <div className="profile-field"><p className="field-value m-0">{profile.bio}</p></div>
                  )}
                </div>
              </div>
              {isEditing && (
                <div className="edit-actions">
                  <button className="btn btn-violet" onClick={handleSave}>Save changes</button>
                  <button className="btn btn-outline-secondary" onClick={handleCancel}>Cancel</button>
                  {saved && <span className="save-success"><i className="ri-checkbox-circle-line"></i> Saved</span>}
                </div>
              )}
            </section>
          )}

          {activeTab === "security" && (
            <section className="profile-card-inner p-4 p-md-5" ref={securitySectionRef}>
              <h2 className="tab-title">Security settings</h2>
              <div className="security-item">
                <div className="d-flex align-items-center gap-3">
                  <div className="security-icon bg-violet-50"><i className="ri-lock-password-line text-violet"></i></div>
                  <div>
                    <p className="security-label mb-0">Password</p>
                    <p className="security-desc mb-0">Update your password regularly to keep your account secure.</p>
                  </div>
                </div>
                <button className="btn-security-action" onClick={() => navigate("/change-password")}>Change password</button>
              </div>
              <div className="security-item">
                <div className="d-flex align-items-center gap-3">
                  <div className={`security-icon ${twoFactorEnabled ? "security-icon-enabled" : "bg-sky-50"}`}>
                    <i className={`ri-shield-check-line ${twoFactorEnabled ? "" : "text-sky"}`}></i>
                  </div>
                  <div>
                    <div className="security-title-row">
                      <p className="security-label mb-0">Two-factor authentication</p>
                      <span className={`two-factor-status ${twoFactorEnabled ? "enabled" : "disabled"}`}>
                        {twoFactorEnabled ? "Enabled" : "Not enabled"}
                      </span>
                    </div>
                    <p className="security-desc mb-0">
                      {twoFactorEnabled ? "A verification code will be required when signing in." : "Protect your sign-in with an additional verification step."}
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
                  aria-label={twoFactorEnabled ? "Disable two-factor authentication" : "Enable two-factor authentication"}
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
                <h2 className="tab-title mb-0">Recent activity</h2>
                {activities.length > 0 && (
                  <button className="activity-clear-btn" type="button" onClick={clearActivities}>
                    Clear activity
                  </button>
                )}
              </div>
              <div className="activity-list">
                {activities.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">No activity yet.</span>
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
                  <h2 className="tab-title mb-0">My surveys</h2>
                  <div className="survey-search">
                    <i className="ri-search-line"></i>
                    <input
                      type="search"
                      value={surveySearch}
                      onChange={(event) => setSurveySearch(event.target.value)}
                      placeholder="Search survey title or invite code"
                      aria-label="Search surveys"
                    />
                  </div>
                </div>
                <div className="survey-controls">
                  <div className="survey-sort-options" role="radiogroup" aria-label="Sort surveys by date">
                    <label className="survey-sort-option">
                      <span>Sort by date: newest first</span>
                      <input
                        type="radio"
                        name="survey-sort-order"
                        value="desc"
                        checked={surveySortOrder === "desc"}
                        onChange={() => setSurveySortOrder("desc")}
                      />
                    </label>
                    <label className="survey-sort-option">
                      <span>Sort by date: oldest first</span>
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
                {isLoadingSurveys && (
                  <div className="profile-field">
                    <span className="field-value">Loading surveys…</span>
                  </div>
                )}
                {!isLoadingSurveys && surveyRecords.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">No surveys yet.</span>
                  </div>
                )}
                {!isLoadingSurveys && surveyRecords.length > 0 && visibleSurveyRecords.length === 0 && (
                  <div className="profile-field">
                    <span className="field-value">No surveys match your search.</span>
                  </div>
                )}
                {!isLoadingSurveys && visibleSurveyRecords.map((survey) => (
                  <div key={`${survey.id}-${survey.code}`} className="profile-field" style={{ justifyContent: "space-between", gap: 16 }}>
                    <div>
                      <strong>{survey.title}</strong>
                      <div style={{ color: "var(--slate-400)", fontSize: 13 }}>
                        Invite code {survey.code} · {survey.responseCount} responses ·  {survey.createdAt}
                      </div>
                      <div className="survey-deadline-meta">
                        <i className="ri-time-line"></i>
                        Deadline {formatSurveyDeadline(survey.deadlineAt)}
                      </div>
                    </div>
                    <button
                      className="btn btn-violet"
                      onClick={() => {
                        recordActivity({
                          text: `View survey: ${survey.title}」`,
                          icon: "ri-survey-line",
                          iconBg: "bg-stat-coral",
                          iconColor: "text-stat-coral",
                        });
                        handleOpenSurveyDetail(survey);
                      }}
                    >
                      View details
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
            <strong>Two-factor authentication enabled</strong>
            <p>A verification code will be required the next time you log in.</p>
          </div>
          <button onClick={() => setShowTwoFactorNotice(false)} aria-label="Dismiss notification">
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
            <strong>Password updated</strong>
            <p>Your login password has been updated successfully.</p>
          </div>
          <button onClick={() => setShowPasswordNotice(false)} aria-label="Dismiss notification">
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
            <h3>Disable two-factor authentication</h3>
            <p>Enter your current login password to confirm your identity.</p>
            <label className="profile-confirm-label" htmlFor="disable-2fa-password">Password</label>
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
                placeholder="Please enter your password"
                autoFocus
              />
              <button
                className="profile-confirm-eye"
                type="button"
                onClick={() => setShowTwoFactorPassword((prev) => !prev)}
                aria-label={showTwoFactorPassword ? "Hide password" : "Show password"}
              >
                <i className={showTwoFactorPassword ? "ri-eye-off-line" : "ri-eye-line"}></i>
                <span>{showTwoFactorPassword ? "Hide" : "Show"}</span>
              </button>
            </div>
            {twoFactorPasswordError && <div className="profile-confirm-error">{twoFactorPasswordError}</div>}
            <div className="profile-confirm-actions">
              <button className="profile-confirm-secondary" type="button" onClick={closeDisableTwoFactorModal} disabled={isDisablingTwoFactor}>
                Cancel
              </button>
              <button className="profile-confirm-danger" type="submit" disabled={isDisablingTwoFactor}>
                {isDisablingTwoFactor ? "Confirming..." : "Confirm disable"}
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
              Got it
            </button>
          </div>
        </div>
      )}
    </>
  );
}
