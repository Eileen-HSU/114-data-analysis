import { useEffect, useRef, useState } from "react";
import { loadGoogleConfig, loadGoogleScript } from "../../lib/googleIdentity";

// 顯示 Google 官方按鈕；使用者選好帳號後以 onCredential(credential) 回傳 ID token。
// Google 未開放或元件載入失敗時不顯示（onUnavailable 可得知）。
export default function GoogleSignInButton({ onCredential, text = "signin_with", disabled = false, onUnavailable }) {
  const holderRef = useRef(null);
  const callbackRef = useRef(onCredential);
  const [ready, setReady] = useState(false);
  callbackRef.current = onCredential;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = await loadGoogleConfig();
        if (!config?.enabled || !config.client_id) throw new Error("disabled");
        const google = await loadGoogleScript();
        if (cancelled || !holderRef.current) return;
        google.accounts.id.initialize({
          client_id: config.client_id,
          callback: (response) => callbackRef.current?.(response.credential),
          ux_mode: "popup",
          auto_select: false,
          cancel_on_tap_outside: true,
        });
        holderRef.current.innerHTML = "";
        google.accounts.id.renderButton(holderRef.current, {
          type: "standard", theme: "outline", size: "large", shape: "pill",
          text, logo_alignment: "center", width: Math.min(holderRef.current.offsetWidth || 320, 400),
        });
        setReady(true);
      } catch {
        if (!cancelled) onUnavailable?.();
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  return (
    <div style={{ position: "relative", minHeight: ready ? 44 : 0, opacity: disabled ? 0.5 : 1 }}>
      <div ref={holderRef} style={{ display: "flex", justifyContent: "center", width: "100%" }} />
      {disabled && <div style={{ position: "absolute", inset: 0, cursor: "not-allowed" }} aria-hidden="true" />}
    </div>
  );
}
