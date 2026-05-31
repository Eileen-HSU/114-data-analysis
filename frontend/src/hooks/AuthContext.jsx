import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { apiUrl } from "../lib/api";

const AUTH_KEY = "dataanalysis_auth";
const AVATAR_STORAGE_KEY_PREFIX = "dataanalysis_avatar";
const AuthContext = createContext({
  isLoggedIn: false,
  user: null,
  profileCache: null,
  login: () => {},
  logout: () => {},
  updateUser: () => {},
});

function loadStoredUser() {
  const raw = localStorage.getItem(AUTH_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(AUTH_KEY);
    return null;
  }
}

function getUserStorageId(user) {
  return user?.user_id || user?.email || "guest";
}

function withStoredAvatar(userData) {
  const avatar = localStorage.getItem(`${AVATAR_STORAGE_KEY_PREFIX}_${getUserStorageId(userData)}`);
  return avatar ? { ...userData, avatar } : userData;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(loadStoredUser);
  const [profileCache, setProfileCache] = useState(null);
  const isLoggedIn = Boolean(user);

  // 登入後或重新整理時自動預載 profile 並更新 avatar
  useEffect(() => {
    if (!user?.token || !user?.user_id) return;
    fetch(apiUrl(`/api/profile/${user.user_id}`), {
      headers: { Authorization: `Bearer ${user.token}` },
    })
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!data) return;
        setProfileCache(data);
        // 登入後馬上把 avatar 存進 user，Navbar 不用等 ProfilePage
        setUser((currentUser) => {
          if (!currentUser) return currentUser;
          const nextUser = { ...currentUser, avatar: data.avatar_url || "" };
          localStorage.setItem(AUTH_KEY, JSON.stringify(nextUser));
          return nextUser;
        });
      })
      .catch(() => {});
  }, [user?.token, user?.user_id]);

  const login = useCallback((userData) => {
    const nextUser = withStoredAvatar(userData);
    localStorage.setItem(AUTH_KEY, JSON.stringify(nextUser));
    setUser(nextUser);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(AUTH_KEY);
    localStorage.removeItem("dataanalysis_workspace_sessions");
    localStorage.removeItem("dataanalysis_collection_folders");
    localStorage.removeItem("dataanalysis_collection_files");
    localStorage.removeItem("dataanalysis_deleted_items");
    setUser(null);
    setProfileCache(null);
  }, []);

  const updateUser = useCallback((updates) => {
    setUser((currentUser) => {
      if (!currentUser) return currentUser;
      const nextUser = { ...currentUser, ...updates };
      localStorage.setItem(AUTH_KEY, JSON.stringify(nextUser));
      return nextUser;
    });
  }, []);

  return (
    <AuthContext.Provider value={{ isLoggedIn, user, profileCache, login, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}