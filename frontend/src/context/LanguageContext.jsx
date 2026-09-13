import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "../hooks/AuthContext";
import { apiUrl } from "../lib/api";

const STORAGE_KEY = "dataanalysis_language";
const copy = {
  "zh-TW": {
    project: "專案管理", assistant: "分析助理", survey: "問卷調查", login: "登入", signup: "註冊",
    profile: "基本資料", edit: "編輯資料", save: "儲存變更", cancel: "取消", language: "顯示語言",
    chinese: "繁體中文", english: "English", logout: "登出", settings: "個人設定",
    welcome: "將培訓回饋整理為", highlight: "標準化分析結果", heroLabel: "AI 輔助的培訓回饋分析平台",
    heroDescription: "整合問卷蒐集、專案管理與 AI 分析助理，協助顧問快速整理文字回饋、查看分類結果，提升課後回饋分析效率。",
    start: "立即開始使用", loginAccount: "登入帳號", scroll: "向下滾動探索",
    features: "核心功能", featureTitle: "讓每一份回饋，都成為可行動的洞察", how: "使用流程", howTitle: "四個步驟，開始使用",
    "home.eyebrow": "AI 輔助的培訓回饋分析平台", "home.title": "將培訓回饋整理為", "home.highlight": "標準化分析結果",
    "home.description": "整合問卷蒐集、專案管理與 AI 分析助理，協助顧問快速整理文字回饋、查看分類結果，提升課後回饋分析效率。",
    "home.start": "立即開始使用", "home.login": "登入帳號", "home.scroll": "向下滾動探索", "home.features": "功能特色", "home.featureTitle": "培訓回饋整理所需的核心功能",
    "profile.language": "偏好語言", "profile.languageHelp": "此設定會套用到您登入後的網站介面。", "profile.chinese": "繁體中文", "profile.english": "English",
    "nav.profile": "個人資料", "nav.logout": "登出",
  },
  en: {
    project: "Projects", assistant: "Analysis Assistant", survey: "Surveys", login: "Log in", signup: "Sign up",
    profile: "Profile", edit: "Edit profile", save: "Save changes", cancel: "Cancel", language: "Display language",
    chinese: "繁體中文", english: "English", logout: "Log out", settings: "Profile settings",
    welcome: "Turn training feedback into", highlight: "standardized insights", heroLabel: "AI-assisted training feedback analysis",
    heroDescription: "Bring survey collection, project management, and AI-assisted analysis together to organize open-text feedback and surface actionable insights.",
    start: "Get started", loginAccount: "Log in", scroll: "Scroll to explore",
    features: "CORE FEATURES", featureTitle: "Make every response actionable", how: "HOW IT WORKS", howTitle: "Get started in four steps",
    "home.eyebrow": "AI-assisted training feedback analysis", "home.title": "Turn training feedback into", "home.highlight": "standardized insights",
    "home.description": "Bring survey collection, project management, and AI-assisted analysis together to organize open-text feedback and surface actionable insights.",
    "home.start": "Get started", "home.login": "Log in", "home.scroll": "Scroll to explore", "home.features": "CORE FEATURES", "home.featureTitle": "Make every response actionable",
    "profile.language": "Preferred language", "profile.languageHelp": "This setting is applied to the interface after you sign in.", "profile.chinese": "Traditional Chinese", "profile.english": "English",
    "nav.profile": "Profile", "nav.logout": "Log out",
  },
};

const LanguageContext = createContext({ language: "zh-TW", setLanguage: () => {}, t: (key) => key });

export function LanguageProvider({ children }) {
  const { user, updateUser } = useAuth();
  const [language, setLanguageState] = useState(() => localStorage.getItem(STORAGE_KEY) || "zh-TW");
  useEffect(() => {
    if (user?.language && ["zh-TW", "en"].includes(user.language)) setLanguageState(user.language);
  }, [user?.language]);
  useEffect(() => { document.documentElement.lang = language; }, [language]);
  const setLanguage = useCallback(async (next) => {
    if (!["zh-TW", "en"].includes(next)) return;
    setLanguageState(next); localStorage.setItem(STORAGE_KEY, next); updateUser?.({ language: next });
    if (user?.token && user?.user_id) {
      try { await fetch(apiUrl(`/api/profile/${user.user_id}`), { method: "PUT", headers: { "Content-Type": "application/json", Authorization: `Bearer ${user.token}` }, body: JSON.stringify({ language: next }) }); } catch { /* local preference remains available offline */ }
    }
  }, [user?.token, user?.user_id, updateUser]);
  const value = useMemo(() => ({ language, setLanguage, t: (key) => copy[language]?.[key] || copy["zh-TW"][key] || key }), [language, setLanguage]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}
export const useLanguage = () => useContext(LanguageContext);
