import { createContext, useContext, useEffect } from "react";

const copy = {
  "project": "Projects",
  "assistant": "Analysis Assistant",
  "survey": "Surveys",
  "login": "Log in",
  "signup": "Sign up",
  "profile": "Profile",
  "edit": "Edit profile",
  "save": "Save changes",
  "cancel": "Cancel",
  "language": "Display language",
  "chinese": "Traditional Chinese",
  "english": "English",
  "logout": "Log out",
  "settings": "Profile settings",
  "welcome": "Turn training feedback into",
  "highlight": "standardized insights",
  "heroLabel": "AI-assisted training feedback analysis",
  "heroDescription": "Bring survey collection, project management, and AI-assisted analysis together to organize open-text feedback and surface actionable insights.",
  "start": "Get started",
  "loginAccount": "Log in",
  "scroll": "Scroll to explore",
  "features": "CORE FEATURES",
  "featureTitle": "Make every response actionable",
  "how": "HOW IT WORKS",
  "howTitle": "Get started in four steps",
  "home.eyebrow": "AI-assisted training feedback analysis",
  "home.title": "Turn training feedback into",
  "home.highlight": "standardized insights",
  "home.description": "Bring survey collection, project management, and AI-assisted analysis together to organize open-text feedback and surface actionable insights.",
  "home.start": "Get started",
  "home.login": "Log in",
  "home.scroll": "Scroll to explore",
  "home.features": "CORE FEATURES",
  "home.featureTitle": "Make every response actionable",
  "profile.language": "Preferred language",
  "profile.languageHelp": "This setting is applied to the interface after you sign in.",
  "profile.chinese": "Traditional Chinese",
  "profile.english": "English",
  "nav.profile": "Profile",
  "nav.logout": "Log out"
};
const languageValue = Object.freeze({ language: "en", setLanguage: () => {}, t: (key) => copy[key] || key });
const LanguageContext = createContext(languageValue);

// Interface copy is English at its source. Never rewrite rendered DOM or user content.
export function LanguageProvider({ children }) {
  useEffect(() => {
    document.documentElement.lang = "en";
    localStorage.setItem("dataanalysis_language", "en");
  }, []);
  return <LanguageContext.Provider value={languageValue}>{children}</LanguageContext.Provider>;
}
export const useLanguage = () => useContext(LanguageContext);
