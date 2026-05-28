import { useNavigate, useLocation } from "react-router-dom";
import { useRoutes } from "react-router-dom";
import { useEffect, useRef } from "react";
import { useActivity } from "../hooks/ActivityContext";
import routes from "./config";

let navigateResolver;

export const navigatePromise = new Promise((resolve) => {
  navigateResolver = resolve;
});

export function AppRoutes() {
  const element = useRoutes(routes);
  const navigate = useNavigate();
  const location = useLocation();
  const { recordActivity } = useActivity();
  const lastPathRef = useRef("");

  useEffect(() => {
    window.REACT_APP_NAVIGATE = navigate;
    navigateResolver(window.REACT_APP_NAVIGATE);
  });

  useEffect(() => {
    const path = location.pathname;
    if (lastPathRef.current === path) return;
    lastPathRef.current = path;

    const labels = {
      "/workspace": "進入工作區",
      "/collection": "查看作品集",
      "/trash": "查看最近刪除",
      "/profile": "查看個人資料",
      "/survey": "進入問卷調查",
      "/survey/create": "建立問卷頁面",
      "/survey/fill": "填寫問卷頁面",
    };

    const isShortSurveyPath = /^\/[A-Z0-9]{1,12}$/i.test(path);
    const label = labels[path] || (path.startsWith("/s/") || path.startsWith("/survey/fill/") || isShortSurveyPath ? labels["/survey/fill"] : "");

    if (label) {
      recordActivity({
        text: label,
        icon: "ri-compass-3-line",
        iconBg: "bg-sky-50",
        iconColor: "text-sky",
      });
    }
  }, [location.pathname, recordActivity]);

  return element;
}
