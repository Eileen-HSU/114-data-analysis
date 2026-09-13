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

// Translation bridge for legacy screens that still contain static Chinese copy.
// It deliberately skips chat and classification output so AI/user-generated content stays untouched.
const legacyEnglish = {
  "問卷管理": "Survey management", "AI 輔助分析": "AI-assisted analysis", "專案管理": "Project management", "表格式結果呈現": "Structured results",
  "功能特色": "Core features", "使用流程": "How it works", "如何使用": "How it works", "四個簡單步驟，完成培訓回饋整理與分析。": "Four simple steps to organize and analyze training feedback.",
  "建立帳號": "Create an account", "建立問卷或上傳資料": "Create a survey or upload data", "使用 AI 分析助理": "Use the AI Analysis Assistant", "保存與查看結果": "Save and review results",
  "準備好開始整理培訓回饋了嗎？": "Ready to organize your training feedback?", "已有帳號？登入": "Already have an account? Log in",
  "基本資料": "Profile", "安全設定": "Security settings", "問卷數": "Surveys", "使用天數": "Days active", "編輯資料": "Edit profile", "取消編輯": "Cancel editing", "儲存變更": "Save changes", "已儲存": "Saved",
  "姓名": "Name", "電話": "Phone", "公司／組織": "Company / organization", "性別": "Gender", "所在地": "Location", "自我介紹": "About you",
  "活動紀錄": "Activity", "清除紀錄": "Clear activity", "目前還沒有活動紀錄。": "No activity yet.", "我的問卷": "My surveys", "搜尋問卷": "Search surveys", "載入問卷中…": "Loading surveys…", "目前還沒有建立問卷。": "No surveys yet.",
  "問卷調查": "Surveys", "建立問卷": "Create survey", "填寫問卷": "Complete survey", "問卷名稱": "Survey title", "問卷代碼": "Survey code", "建立日期": "Created", "回覆人數": "Responses", "題目數量": "Questions",
  "統計總覽": "Overview", "回覆明細": "Response details", "評分題統計": "Rating summary", "問答題摘要": "Open-ended response summary", "所有回覆": "All responses", "平均分": "Average score", "提交時間": "Submitted", "填答人": "Respondent", "匿名": "Anonymous",
  "歷史對話紀錄": "Conversation history", "搜尋歷史對話紀錄...": "Search conversations…", "尚無工作區紀錄": "No workspaces yet", "新增工作區": "New workspace", "找不到相關紀錄": "No matching conversations", "重新命名": "Rename", "刪除工作區": "Delete workspace",
  "邀請檢視": "Invite viewers", "產生連結中...": "Creating link…", "選擇或新增一個工作區開始分析": "Select or create a workspace to start analyzing", "AI 思考中": "AI is thinking", "選擇問卷進行分析": "Choose a survey to analyze", "問卷載入中...": "Loading surveys…", "找不到相關問卷": "No matching surveys", "進行中": "Active", "已結束": "Closed",
  "附加檔案": "Attach file", "輸入您的問題或上傳檔案進行分析...": "Ask a question or upload a file for analysis…", "取消": "Cancel", "確定": "Confirm", "刪除中...": "Deleting…", "確認刪除": "Delete", "更多": "More",
  "專案管理需要登入帳號才能使用。": "Please log in to use Project Management.", "需要登入": "Login required", "前往登入": "Go to login", "此功能需要登入帳號才能使用。": "Please log in to use this feature.",
  "資料夾": "Folder", "新增資料夾": "New folder", "資料夾名稱": "Folder name", "建立": "Create", "未分類檔案": "Unfiled items", "匯出檔案": "Exported files", "最近刪除": "Recently deleted", "還原": "Restore", "永久刪除": "Delete permanently",
  "搜尋匯出檔案名稱...": "Search exported file names…", "目前沒有匯出檔案。": "No exported files yet.", "目前沒有最近刪除的項目。": "There are no recently deleted items.", "拖曳檔案到這裡": "Drag files here",
  "登入": "Log in", "註冊": "Sign up", "返回首頁": "Back to home", "電子郵件": "Email", "密碼": "Password", "確認密碼": "Confirm password", "忘記密碼？": "Forgot password?", "建立帳號": "Create account", "登入帳號": "Log in",
  "修改密碼": "Change password", "發送修改連結": "Send reset link", "重新發送": "Resend", "郵件已發送！": "Email sent!", "返回個人資料": "Back to profile",
  "AI 管理": "AI Administration", "系統管理": "System administration", "全部": "All", "查看設定": "View settings", "繼續修改": "Continue editing", "儲存": "Save", "發布": "Publish",
};

const PROTECTED_OUTPUT_SELECTOR = ".messages-area, .message-bubble, .assistant-bubble, .user-bubble, .classification-table, [data-ai-output]";

function translateLegacyInterface(language) {
  if (!document.body) return;
  const target = language === "en" ? legacyEnglish : Object.fromEntries(Object.entries(legacyEnglish).map(([zh, en]) => [en, zh]));
  const translate = (value) => target[value] || value;
  const isProtected = (element) => element?.closest?.(PROTECTED_OUTPUT_SELECTOR);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return isProtected(node.parentElement) || !target[node.nodeValue.trim()] ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const whitespace = node.nodeValue.match(/^(\s*)|(?:\s*)$/g) || ["", ""];
    node.nodeValue = `${whitespace[0]}${translate(node.nodeValue.trim())}${whitespace[1] || ""}`;
  });

  document.querySelectorAll("[placeholder], [title], [aria-label]").forEach((element) => {
    if (isProtected(element)) return;
    ["placeholder", "title", "aria-label"].forEach((attribute) => {
      const value = element.getAttribute(attribute);
      if (value && target[value]) element.setAttribute(attribute, translate(value));
    });
  });
}

const LanguageContext = createContext({ language: "zh-TW", setLanguage: () => {}, t: (key) => key });

export function LanguageProvider({ children }) {
  const { user, updateUser } = useAuth();
  const [language, setLanguageState] = useState(() => localStorage.getItem(STORAGE_KEY) || "zh-TW");
  useEffect(() => {
    if (user?.language && ["zh-TW", "en"].includes(user.language)) setLanguageState(user.language);
  }, [user?.language]);
  useEffect(() => { document.documentElement.lang = language; }, [language]);
  useEffect(() => {
    const applyTranslations = () => translateLegacyInterface(language);
    const frame = window.requestAnimationFrame(applyTranslations);
    const observer = new MutationObserver(() => window.requestAnimationFrame(applyTranslations));
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [language]);
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
