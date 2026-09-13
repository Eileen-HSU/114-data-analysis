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
Object.assign(legacyEnglish, {
  "歡迎回來": "Welcome back", "回到您的分析工作區": "Return to your analysis workspace", "快速整理資料並取得洞察": "Organize data and gain insights faster", "支援多種資料格式": "Multiple data formats supported", "AI 智能分析": "Intelligent AI analysis", "專案管理隨時回顧": "Review projects anytime",
  "立即註冊": "Sign up now", "立即登入": "Log in now", "返回登入": "Back to login", "返回登入頁面": "Back to login", "返回首頁": "Back to home", "服務條款": "Terms of Service", "隱私政策": "Privacy Policy", "確定": "OK",
  "還沒有帳號？": "Don't have an account?", "已有帳號？": "Already have an account?", "免費註冊": "Sign up for free", "忘記密碼？": "Forgot password?", "登入失敗": "Login failed", "登入失敗，請確認帳號或密碼是否正確。": "Login failed. Please check your email and password.", "登入中...": "Logging in…", "正在登入帳號...": "Signing you in…", "正在確認您的帳號資料，請稍候。": "Verifying your account, please wait.", "連線失敗，請確認後端服務是否正常。": "Connection failed. Please check that the server is available.",
  "請輸入電子郵件地址": "Please enter your email address", "請輸入電子郵件": "Please enter your email", "請輸入有效的電子郵件格式": "Please enter a valid email address", "請輸入密碼。": "Please enter your password.", "請輸入密碼": "Please enter your password", "建立帳號": "Create account", "開始您的分析旅程": "Start your analysis journey", "立即體驗 AI 驅動的資料分析": "Experience AI-powered data analysis", "快速上手": "Get started quickly", "自然語言提問": "Ask questions in natural language", "安全保護您的資料": "Keep your data secure", "您的姓名": "Your name", "手機號碼": "Mobile number", "公司 / 機構": "Company / organization", "您的公司名稱": "Your company name", "請選擇性別": "Select your gender", "您的電子郵件": "Your email", "至少 8 個字元": "At least 8 characters", "再次輸入密碼": "Enter your password again", "建立並登入中...": "Creating account and signing in…", "正在建立帳號...": "Creating your account…", "註冊完成後會直接登入並進入系統，請稍候。": "You will be signed in after registration. Please wait.", "註冊即表示您同意我們的": "By signing up, you agree to our", "請先選擇性別後再建立帳號。": "Please select your gender before creating an account.", "註冊失敗": "Registration failed", "註冊失敗，請檢查資料": "Registration failed. Please check your information.",
  "修改您的密碼": "Change your password", "保護您的帳號安全": "Protect your account", "驗證連結會寄到信箱": "A verification link will be sent by email", "確認身份後即可設定新密碼": "Set a new password after verification", "驗證連結寄送至信箱": "Verification link sent by email", "連結 10 分鐘內有效": "Link valid for 10 minutes", "完成後回到個人資料": "Return to your profile when finished", "輸入您的帳號電子郵件，我們將發送密碼修改連結。": "Enter your account email and we will send a password-change link.", "寄出的郵件可能存在垃圾郵件中": "The email may be in your spam folder", "發送修改連結": "Send password-change link", "發送中...": "Sending…", "發送失敗，請稍後再試": "Unable to send. Please try again.", "郵件已發送！": "Email sent!", "我們已將密碼修改連結發送至": "We sent the password-change link to", "請檢查您的收件匣。點擊連結後即可設定新密碼並直接進入工作區。": "Check your inbox. Follow the link to set a new password and enter your workspace.",
  "重設您的密碼": "Reset your password", "輸入您的電子郵件": "Enter your email", "我們會寄送安全重設連結": "We will send a secure reset link", "重設連結寄送至信箱": "Reset link sent by email", "連結 30 分鐘內有效": "Link valid for 30 minutes", "全程保護帳號安全": "Your account is protected throughout", "輸入您的帳號電子郵件，我們將發送密碼重設連結。": "Enter your account email and we will send a password-reset link.", "發送重設連結": "Send reset link", "請檢查您的收件匣（包含垃圾郵件資料夾）。連結將在": "Check your inbox (including spam). The link will be valid for", "重設密碼": "Reset password", "設定新密碼": "Set new password", "再次確認新密碼": "Confirm new password", "密碼重設成功": "Password reset successful", "請使用新密碼重新登入您的帳號。": "Please log in again with your new password.",
  "雙因子驗證": "Two-factor authentication", "請輸入信箱中的驗證碼": "Enter the verification code from your email", "完成後即可安全登入": "Sign in securely after verification", "降低未授權登入風險": "Reduce unauthorized access risk", "驗證碼已寄送到信箱": "Verification code sent by email", "驗證碼 10 分鐘內有效": "Code valid for 10 minutes", "輸入驗證碼": "Enter verification code", "驗證碼": "Verification code", "請輸入 6 位數驗證碼": "Enter the 6-digit verification code", "驗證中...": "Verifying…", "完成啟用": "Finish setup", "啟用雙因子驗證": "Enable two-factor authentication", "寄送驗證碼": "Send verification code", "寄送中...": "Sending…", "寄送失敗，請稍後再試": "Unable to send. Please try again.", "驗證碼錯誤，請重新輸入": "Incorrect code. Please try again.", "驗證失敗，請重新輸入": "Verification failed. Please try again.",

});
const PROTECTED_OUTPUT_SELECTOR = ".messages-area, .message-bubble, .assistant-bubble, .user-bubble, .classification-table, [data-ai-output]";
Object.assign(legacyEnglish, {
  "資料匯入": "Data import", "資料上傳與匯入": "Upload and import data", "資料分析": "Data analysis", "分析助理": "Analysis Assistant", "新增對話": "New conversation", "問卷管理": "Survey management", "問卷蒐集": "Survey collection",
  "問卷建立與回饋蒐集": "Create surveys and collect feedback", "歷史紀錄保存": "Save history", "結果呈現": "Results", "專案保存": "Save projects", "歷程追蹤": "Track history", "AI 輔助": "AI assistance",
  "新增工作區需要登入帳號才能使用，登入後即可開始分析資料。": "Please log in to create a workspace and start analyzing data.", "正在載入工作區...": "Loading workspace…", "正在載入歷史對話...": "Loading conversation history…", "正在整理您的專案管理、歷史對話紀錄與分析資料，請稍候。": "Preparing your projects, conversation history, and analysis data. Please wait.", "正在取得這個 Chat 的歷史資料，完成後會自動顯示。": "Retrieving this chat's history. It will appear automatically when ready.",
  "新增工作區": "New workspace", "搜尋歷史對話紀錄...": "Search conversation history…", "尚無工作區紀錄": "No workspace history", "找不到相關紀錄": "No matching records", "邀請檢視": "Invite viewers", "選擇或新增一個工作區開始分析": "Select or create a workspace to start analyzing", "點擊問卷圖示可直接選擇問卷分析 · 支援 CSV、Excel、TXT · Enter 發送": "Click the survey icon to analyze a survey · Supports CSV, Excel, and TXT · Press Enter to send",
  "問卷載入中...": "Loading surveys…", "選擇問卷進行分析": "Choose a survey to analyze", "搜尋問卷名稱或代碼...": "Search survey title or code…", "找不到相關問卷": "No matching surveys", "進行中": "Active", "已結束": "Closed", "人回覆": "responses", "附加檔案": "Attach file", "檔案": "File", "輸入您的問題或上傳檔案進行分析...": "Ask a question or upload a file for analysis…",
  "建立問卷": "Create survey", "問卷標題": "Survey title", "問卷說明": "Survey description", "新增題目": "Add question", "儲存問卷": "Save survey", "預覽問卷": "Preview survey", "發布問卷": "Publish survey", "問卷已發布": "Survey published", "返回問卷": "Back to survey", "送出答案": "Submit answers", "提交成功": "Submitted successfully", "謝謝您的回覆": "Thank you for your response",

  "資料上傳與匯入": "Upload and import data", "支援上傳問卷資料或文字檔案，讓使用者可將外部回饋資料匯入系統進行分析。": "Upload survey data or text files and bring external feedback into the analysis workspace.",
  "AI 輔助分析": "AI-assisted analysis", "結合 TF-IDF 與 Gemini API，協助整理文字回饋內容，產生分類結果與分析紀錄。": "Combine TF-IDF and Gemini API to organize text feedback and produce categorized results.",
  "專案管理": "Project management", "將不同培訓專案的問卷資料、分析結果與歷史紀錄集中保存，方便後續查詢與追蹤。": "Keep survey data, analysis results, and history for each training project together for easy follow-up.",
  "歷史紀錄保存": "Save history", "系統可保存過去的分析專案與操作紀錄，方便使用者回顧、查詢與延續分析流程。": "Review past analysis projects and activity history whenever you need to continue your work.",
  "表格式結果呈現": "Structured results", "分析結果以表格式呈現，方便使用者查看分類結果、回饋重點與分析紀錄。": "Review categorized results, key feedback, and analysis history in a clear table.",
  "問卷建立與回饋蒐集": "Create surveys and collect feedback", "支援建立問卷、蒐集填答內容，並可將回饋資料提供給 AI 分析助理進行整理。": "Create surveys, collect responses, and send feedback to the AI Analysis Assistant for organization.",
  "四個簡單步驟，完成培訓回饋整理與分析。": "Four simple steps to organize and analyze training feedback.",
  "個資料夾": "folders", "個 Chat": "chats", "個檔案": "files", "個項目": "items", "份回覆": "responses", "筆回答": "answers", "筆": "responses", "人回覆": "responses", "人回答": "responses",
  "歷史專案": "Project history", "近期活動": "Recent activity", "沒有未分類檔案。": "No unfiled files.", "未分類": "Unfiled", "資料夾": "Folder", "資料夾內": "In folder", "檔案名稱": "File name", "名稱": "Name",
  "開始分析": "Start analysis", "新增分析": "New analysis", "新增對話": "New conversation", "產生連結中...": "Creating link…", "已生成完成，可點擊檔案下載。": "is ready. Click the file to download.", "尚未完成": "Not finished", "處理中": "Processing", "成功": "Success", "失敗": "Failed",
  "近期活動": "Recent activity", "追蹤日期：由近到遠": "Sort by date: newest first", "追蹤日期：由遠到近": "Sort by date: oldest first", "公司 / 組織": "Company / organization", "公司／組織": "Company / organization",
  "安全設定": "Security settings", "建議定期更新密碼，提升帳號安全。": "Update your password regularly to keep your account secure.", "透過第二層驗證保護登入流程。": "Protect your sign-in with an additional verification step.", "登入時會要求輸入驗證碼。": "A verification code will be required when signing in.", "變更密碼": "Change password", "未開啟": "Not enabled",
  "分享的對話": "Shared conversation", "僅供瀏覽": "View only", "檢視連結": "View link", "複製檢視連結": "Copy view link", "已複製連結": "Link copied", "完成": "Done", "訪客檢視": "Guest view", "讓其他人一起查看這段分析對話": "Let others view this analysis conversation", "取得連結即可免登入查看。": "Anyone with the link can view without signing in.", "訪客無法傳送指令或修改這段對話。": "Guests cannot send commands or modify this conversation.", "產生連結中...": "Creating link…",
  "近期活動": "Recent activity", "查看詳情": "View details", "邀請碼": "Invite code", "截止": "Deadline", "未設定截止時間": "No deadline set", "截止日期與時間": "Deadline date and time", "選擇截止日期與時間": "Choose deadline date and time", "截止時間必須晚於現在。": "The deadline must be later than now.",
  "伺服器回應時間較長，建立問卷尚未確認完成。請先到個人頁面的問卷列表確認，再決定是否重試。": "The server is taking longer than expected. Check your profile's survey list before retrying.", "儲存中...": "Saving…", "完成問卷建立": "Finish creating survey", "請完成所有必填題目。": "Please complete all required questions.", "輸入邀請碼開啟問卷，完成填答並提交回饋內容。": "Enter an invite code to open the survey, complete it, and submit your feedback.",
  "正在生成": "Generating", "請稍候，完成後會自動前往匯出檔案。": "Please wait. You will be taken to exported files when it is ready.", "這則訊息尚未同步完成，請稍後再試一次匯出。": "This message has not finished syncing. Please try exporting again later.",
});
function translateLegacyInterface(language) {
  if (!document.body) return;
  const target = language === "en"
    ? legacyEnglish
    : Object.fromEntries(Object.entries(legacyEnglish).map(([zh, en]) => [en, zh]));
  const phrases = Object.keys(target).filter(Boolean).sort((a, b) => b.length - a.length);
  const translate = (value) => phrases.reduce((result, phrase) => result.split(phrase).join(target[phrase]), value);
  const isProtected = (element) => element?.closest?.(PROTECTED_OUTPUT_SELECTOR);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const value = node.nodeValue.trim();
      return isProtected(node.parentElement) || !value || !phrases.some((phrase) => value.includes(phrase))
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    node.nodeValue = translate(node.nodeValue);
  });

  document.querySelectorAll("[placeholder], [title], [aria-label]").forEach((element) => {
    if (isProtected(element)) return;
    ["placeholder", "title", "aria-label"].forEach((attribute) => {
      const value = element.getAttribute(attribute);
      if (value && phrases.some((phrase) => value.includes(phrase))) element.setAttribute(attribute, translate(value));
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
