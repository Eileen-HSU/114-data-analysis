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
      "/workspace": "Opened workspace",
      "/collection": "Viewed Project Management",
      "/trash": "Viewed Recently deleted",
      "/profile": "Viewed profile",
      "/survey": "Opened surveys",
      "/survey/create": "Opened survey creation",
      "/survey/fill": "Opened survey response page",
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
