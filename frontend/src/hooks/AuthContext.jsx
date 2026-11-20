import { createContext, useContext, useState, useCallback, useEffect, useRef } from "react";
import axios from "axios";
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

// 讀取 JWT 的到期時間（毫秒）；只解碼 payload，不驗證簽章（驗證由後端負責）
function tokenExpiryMs(token) {
  try {
    const part = String(token || "").split(".")[1];
    if (!part) return null;
    const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof json.exp === "number" ? json.exp * 1000 : null;
  } catch {
    return null;
  }
}

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


// ───────────────────────── 登入逾時：不跳頁，彈出重新登入視窗 ─────────────────────────
// 收到 401（token 逾時或已失效）時，頁面不卸載，輸入中的內容全部保留；
// 在視窗內重新登入後，自動用新 token 重送剛才失敗的那個請求。
// fetch 與 axios 都在這裡統一處理，各頁面不用個別改。
let reauthHandler = null; // 由 AuthProvider 註冊
let reauthPromise = null; // 同時多個請求 401 時共用同一個登入視窗

function requestReauth() {
  if (!reauthHandler) return Promise.resolve(null);
  if (!reauthPromise) {
    reauthPromise = reauthHandler().finally(() => { reauthPromise = null; });
  }
  return reauthPromise;
}

// sentAuth：失敗的那個請求帶的 Authorization。回傳可用的新 token；null 代表不重試。
async function tokenForRetry(sentAuth) {
  if (!sentAuth || !sentAuth.startsWith("Bearer ")) return null; // 沒帶登入資訊的請求（公開頁面）不處理
  const stored = loadStoredUser()?.token;
  if (!stored) return null; // 已登出
  if (sentAuth !== `Bearer ${stored}`) return stored; // 別的請求已重新登入過，直接用新 token
  return requestReauth();
}

function installAuthRetry() {
  if (typeof window === "undefined" || window.__dataAnalysisAuthRetry) return;
  window.__dataAnalysisAuthRetry = true;

  const previousFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const response = await previousFetch(input, init);
    if (response.status !== 401 || input instanceof Request) return response;
    const headers = new Headers(init.headers || {});
    const newToken = await tokenForRetry(headers.get("Authorization"));
    if (!newToken) return response;
    headers.set("Authorization", `Bearer ${newToken}`);
    return previousFetch(input, { ...init, headers });
  };

  axios.interceptors.response.use((r) => r, async (error) => {
    const config = error?.config;
    if (error?.response?.status !== 401 || !config || config.__authRetried) throw error;
    const sent = config.headers?.Authorization ?? config.headers?.get?.("Authorization");
    const newToken = await tokenForRetry(sent);
    if (!newToken) throw error;
    config.__authRetried = true;
    if (config.headers?.set) config.headers.set("Authorization", `Bearer ${newToken}`);
    else config.headers = { ...(config.headers || {}), Authorization: `Bearer ${newToken}` };
    return axios.request(config);
  });
}

installAuthRetry();

function ReauthDialog({ user, onSuccess, onLogout }) {
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [preAuth, setPreAuth] = useState(null); // 有開雙因子驗證時的第二步
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const finish = (data) => {
    if (data?.user_id && user?.user_id && Number(data.user_id) !== Number(user.user_id)) {
      setError("請使用原本的帳號登入，才能繼續剛才的操作。");
      return;
    }
    onSuccess(data);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      let res;
      if (preAuth) {
        res = await fetch(apiUrl("/api/auth/2fa/login/two-factor"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: user.email, otp, pre_auth_token: preAuth }),
        });
      } else {
        res = await fetch(apiUrl("/api/login"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: user.email, password }),
        });
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || "登入失敗，請再試一次。");
      } else if (data.require_2fa) {
        setPreAuth(data.pre_auth_token);
      } else {
        finish(preAuth ? { ...(data.user || {}), token: data.token } : data);
      }
    } catch {
      setError("連線失敗，請稍後再試。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="reauth-title"
      style={{ position: "fixed", inset: 0, background: "rgba(15, 23, 42, .35)", backdropFilter: "blur(4px)", WebkitBackdropFilter: "blur(4px)", zIndex: 5000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <form onSubmit={submit} autoComplete="off"
        style={{ background: "#fff", borderRadius: 20, padding: "32px 28px 24px", width: "100%", maxWidth: 400, boxShadow: "0 20px 60px rgba(236, 72, 153, .18)" }}>
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div style={{ width: 52, height: 52, borderRadius: 16, margin: "0 auto 14px", display: "flex", alignItems: "center", justifyContent: "center", background: "linear-gradient(135deg, #ffe4e6, #fce7f3)", color: "var(--pink-500)", fontSize: 24 }}>
            <i className="ri-time-line" aria-hidden="true"></i>
          </div>
          <h2 id="reauth-title" style={{ fontSize: 20, fontWeight: 700, color: "var(--slate-800, #1e293b)", margin: "0 0 6px" }}>登入已逾時</h2>
          <p style={{ fontSize: 14, color: "var(--slate-500)", margin: 0, lineHeight: 1.6 }}>
            請重新輸入密碼，頁面上的內容都會保留。
          </p>
          <p style={{ fontSize: 13, color: "var(--slate-400)", margin: "8px 0 0" }}>{user?.email}</p>
        </div>

        {preAuth ? (
          <>
            <label className="auth-label" htmlFor="reauth-otp">Email 驗證碼</label>
            <div className="position-relative mb-3">
              <i className="ri-mail-check-line form-icon" aria-hidden="true"></i>
              <input id="reauth-otp" className="form-control-custom" inputMode="numeric" autoFocus placeholder="6 位數驗證碼"
                value={otp} onChange={(e) => setOtp(e.target.value)} />
            </div>
          </>
        ) : (
          <>
            <label className="auth-label" htmlFor="reauth-password">密碼</label>
            <div className="position-relative mb-3">
              <i className="ri-lock-line form-icon" aria-hidden="true"></i>
              <input id="reauth-password" className="form-control-custom" type="password" autoFocus autoComplete="current-password"
                placeholder="請輸入密碼" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </>
        )}

        {error && (
          <div style={{ color: "#dc2626", background: "#fef2f2", borderRadius: 10, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>{error}</div>
        )}

        <button type="submit" className="btn-auth-submit w-100" disabled={busy || (preAuth ? !otp : !password)}
          style={{ opacity: busy || (preAuth ? !otp : !password) ? 0.6 : 1 }}>
          {busy ? "登入中…" : "重新登入"}
        </button>
        <div style={{ textAlign: "center", marginTop: 14 }}>
          <button type="button" onClick={onLogout}
            style={{ background: "none", border: "none", color: "var(--slate-400)", fontSize: 13, cursor: "pointer" }}>
            改用其他帳號（登出）
          </button>
        </div>
      </form>
    </div>
  );
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(loadStoredUser);
  const [profileCache, setProfileCache] = useState(null);
  const isLoggedIn = Boolean(user);
  const [reauthOpen, setReauthOpen] = useState(false);
  const reauthResolver = useRef(null);
  const userRef = useRef(user);
  userRef.current = user;

  // 登入後或重新整理時自動預載 profile 並更新 avatar
  // Admin 沒有 User_Profile 這張表，所以只在 account_type 是 user
  // （或舊資料沒有 account_type 欄位，視為 user 以維持相容）時才打。
  useEffect(() => {
    if (!user?.token || !user?.user_id) return;
    if (user?.account_type && user.account_type !== "user") return;
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
          const nextUser = {
            ...currentUser,
            avatar: data.avatar_url || "",
            email_2fa_enabled: data.email_2fa_enabled === true,
          };
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
    // 通知後端讓這組 token 立即失效（失敗也照常登出）
    const staleToken = loadStoredUser()?.token;
    if (staleToken) {
      fetch(apiUrl("/api/auth/logout"), { method: "POST", headers: { Authorization: `Bearer ${staleToken}` }, keepalive: true }).catch(() => {});
    }
    if (reauthResolver.current) { reauthResolver.current(null); reauthResolver.current = null; }
    setReauthOpen(false);
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

  // 註冊「登入逾時」處理：回傳 Promise，重新登入成功時 resolve 新 token，取消則 resolve null
  useEffect(() => {
    reauthHandler = () => new Promise((resolve) => {
      if (!userRef.current?.token) { resolve(null); return; }
      reauthResolver.current = resolve;
      setReauthOpen(true);
    });
    return () => { reauthHandler = null; };
  }, []);

  // 時間一到就主動跳出重新登入視窗（使用者正在輸入也一樣），不用等到送出請求才發現。
  // 每 5 秒檢查一次，並在切回分頁、電腦從睡眠醒來時立即檢查（睡眠時計時器會暫停）。
  useEffect(() => {
    const expiry = tokenExpiryMs(user?.token);
    if (!expiry) return undefined;
    const check = () => {
      if (Date.now() >= expiry && !reauthPromise) requestReauth();
    };
    check();
    const timer = setInterval(check, 5000);
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", check);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", check);
    };
  }, [user?.token]);

  const handleReauthSuccess = useCallback((data) => {
    const token = data?.token;
    if (!token) return;
    updateUser({ token });
    setReauthOpen(false);
    if (reauthResolver.current) { reauthResolver.current(token); reauthResolver.current = null; }
  }, [updateUser]);

  return (
    <AuthContext.Provider value={{ isLoggedIn, user, profileCache, login, logout, updateUser }}>
      {children}
      {reauthOpen && user && <ReauthDialog user={user} onSuccess={handleReauthSuccess} onLogout={logout} />}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
