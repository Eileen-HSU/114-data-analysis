import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "./AuthContext";

const ACTIVITY_KEY_PREFIX = "dataanalysis_activity";
const MAX_ACTIVITIES = 80;

const ActivityContext = createContext({
  activities: [],
  recordActivity: () => {},
  clearActivities: () => {},
});

function getActivityKey(user) {
  return `${ACTIVITY_KEY_PREFIX}_${user?.user_id || user?.email || "guest"}`;
}

function loadActivities(key) {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function ActivityProvider({ children }) {
  const { user } = useAuth();
  const storageKey = useMemo(() => getActivityKey(user), [user]);
  const [activities, setActivities] = useState(() => loadActivities(storageKey));

  useEffect(() => {
    setActivities(loadActivities(storageKey));
  }, [storageKey]);

  const recordActivity = useCallback((activity) => {
    if (!activity?.text) return;

    setActivities((prev) => {
      const next = [
        {
          id: `activity-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          icon: activity.icon || "ri-time-line",
          iconBg: activity.iconBg || "bg-violet-50",
          iconColor: activity.iconColor || "text-violet",
          text: activity.text,
          createdAt: activity.createdAt || new Date().toISOString(),
        },
        ...prev,
      ].slice(0, MAX_ACTIVITIES);

      localStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  }, [storageKey]);

  const clearActivities = useCallback(() => {
    localStorage.removeItem(storageKey);
    setActivities([]);
  }, [storageKey]);

  return (
    <ActivityContext.Provider value={{ activities, recordActivity, clearActivities }}>
      {children}
    </ActivityContext.Provider>
  );
}

export function useActivity() {
  return useContext(ActivityContext);
}
