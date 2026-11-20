import { useEffect, useState } from "react";
import { apiUrl } from "../../lib/api";
import GoogleSignInButton from "../../components/feature/GoogleSignInButton";

// 安全設定：綁定／解除 Google 帳號。只能綁定與本帳號 Email 完全相同的 Google 帳號，
// 綁定與解除都需重新輸入密碼；已開啟雙因子驗證者綁定時另需 Email 驗證碼。
export default function GoogleLinkSection({ token, email, twoFactorEnabled }) {
  const [status, setStatus] = useState(null); // { bound }
  const [unavailable, setUnavailable] = useState(false);
  const [mode, setMode] = useState(""); // "" | "bind" | "unbind"
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });

  const authHeaders = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  const loadStatus = () =>
    fetch(apiUrl("/api/auth/google/status"), { headers: authHeaders })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setStatus(d))
      .catch(() => {});

  useEffect(() => {
    if (token) loadStatus();
    fetch(apiUrl("/api/auth/google/config")).then((r) => r.json()).then((c) => { if (!c?.enabled) setUnavailable(true); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const reset = () => { setMode(""); setPassword(""); setOtp(""); setOtpSent(false); };

  const sendOtp = async () => {
    setBusy(true);
    setMessage({ type: "", text: "" });
    try {
      const res = await fetch(apiUrl("/api/auth/2fa/send"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
      const data = await res.json().catch(() => ({}));
      if (res.ok) { setOtpSent(true); setMessage({ type: "ok", text: "驗證碼已寄到你的信箱，請於 10 分鐘內輸入。" }); }
      else setMessage({ type: "error", text: data.error || "寄送失敗，請稍後再試。" });
    } finally { setBusy(false); }
  };

  const bind = async (credential) => {
    if (!credential) return;
    if (!password) { setMessage({ type: "error", text: "請先輸入密碼。" }); return; }
    if (twoFactorEnabled && !otp) { setMessage({ type: "error", text: "請先取得並輸入 Email 驗證碼。" }); return; }
    setBusy(true);
    setMessage({ type: "", text: "" });
    try {
      const res = await fetch(apiUrl("/api/auth/google/bind"), { method: "POST", headers: authHeaders, body: JSON.stringify({ credential, password, otp }) });
      const data = await res.json().catch(() => ({}));
      if (res.ok) { reset(); setMessage({ type: "ok", text: "已綁定 Google 帳號，之後可在登入頁使用 Google 登入。" }); loadStatus(); }
      else setMessage({ type: "error", text: data.error || "綁定失敗，請稍後再試。" });
    } catch { setMessage({ type: "error", text: "連線失敗，請稍後再試。" }); }
    finally { setBusy(false); }
  };

  const unbind = async (e) => {
    e.preventDefault();
    if (!password) { setMessage({ type: "error", text: "請輸入密碼。" }); return; }
    setBusy(true);
    setMessage({ type: "", text: "" });
    try {
      const res = await fetch(apiUrl("/api/auth/google/unbind"), { method: "POST", headers: authHeaders, body: JSON.stringify({ password }) });
      const data = await res.json().catch(() => ({}));
      if (res.ok) { reset(); setMessage({ type: "ok", text: "已解除 Google 帳號綁定，之後請使用密碼登入。" }); loadStatus(); }
      else setMessage({ type: "error", text: data.error || "解除失敗，請稍後再試。" });
    } catch { setMessage({ type: "error", text: "連線失敗，請稍後再試。" }); }
    finally { setBusy(false); }
  };

  if (unavailable || !status) return null;
  const bound = Boolean(status.bound);

  return (
    <div className="security-item" style={{ flexWrap: "wrap", gap: 12 }}>
      <div className="d-flex align-items-center gap-3">
        <div className="security-icon bg-sky-50"><i className="ri-google-line text-sky"></i></div>
        <div>
          <div className="security-title-row">
            <p className="security-label mb-0">Google 帳號</p>
            <span className={`two-factor-status ${bound ? "enabled" : "disabled"}`}>{bound ? "已綁定" : "未綁定"}</span>
          </div>
          <p className="security-desc mb-0">
            {bound ? `可使用 Google（${email}）登入。` : `可綁定與本帳號相同 Email（${email}）的 Google 帳號，之後用 Google 登入。`}
          </p>
        </div>
      </div>
      {!mode && (
        <button className="btn-security-action" type="button" onClick={() => { setMessage({ type: "", text: "" }); setMode(bound ? "unbind" : "bind"); }}>
          {bound ? "解除綁定" : "綁定 Google"}
        </button>
      )}

      {mode && (
        <form onSubmit={mode === "unbind" ? unbind : (e) => e.preventDefault()} style={{ width: "100%", maxWidth: 420 }} autoComplete="off">
          {mode === "bind" && (
            <p style={{ fontSize: 13, color: "#7a4b00", background: "#fff7e6", border: "1px solid #f5c26b", borderRadius: 8, padding: "8px 10px" }}>
              使用 Google 登入時將略過本系統的 Email 驗證，建議為你的 Google 帳號開啟兩步驟驗證。
            </p>
          )}
          <label className="profile-confirm-label" htmlFor="google-link-password">請重新輸入密碼</label>
          <input id="google-link-password" type="password" className="form-control mb-2" autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)} />
          {mode === "bind" && twoFactorEnabled && (
            <>
              <label className="profile-confirm-label" htmlFor="google-link-otp">Email 驗證碼</label>
              <div className="d-flex gap-2 mb-2">
                <input id="google-link-otp" className="form-control" inputMode="numeric" value={otp} onChange={(e) => setOtp(e.target.value)} />
                <button type="button" className="btn btn-outline-secondary" disabled={busy} onClick={sendOtp} style={{ whiteSpace: "nowrap" }}>
                  {otpSent ? "重新寄送" : "寄送驗證碼"}
                </button>
              </div>
            </>
          )}
          {mode === "bind" && (
            <div className="mb-2">
              <p style={{ fontSize: 13, margin: "4px 0 6px" }}>輸入完成後，按下方按鈕選擇 Google 帳號：</p>
              <GoogleSignInButton text="continue_with" onCredential={bind}
                disabled={busy || !password || (twoFactorEnabled && !otp)} onUnavailable={() => setUnavailable(true)} />
            </div>
          )}
          <div className="d-flex align-items-center justify-content-end gap-2 mt-2">
            <button type="button" className="btn-security-action" onClick={() => { reset(); setMessage({ type: "", text: "" }); }}>取消</button>
            {mode === "unbind" && (
              <button type="submit" className="btn-security-action" disabled={busy || !password}
                style={{ background: "#c0392b", borderColor: "#c0392b", color: "#fff", opacity: busy || !password ? 0.5 : 1 }}>
                {busy ? "處理中…" : "確認解除綁定"}
              </button>
            )}
          </div>
        </form>
      )}

      {message.text && (
        <p role="status" style={{ width: "100%", margin: 0, fontSize: 13, color: message.type === "error" ? "#c0392b" : "#1e8449" }}>{message.text}</p>
      )}
    </div>
  );
}
