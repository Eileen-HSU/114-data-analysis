import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";

export default function ExportActions({ rows, chatId, sourceFilename }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [pendingFormat, setPendingFormat] = useState("");
  const [error, setError] = useState("");
  const busyRef = useRef(false);
  const noticeRef = useRef(null);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!pendingFormat && !error) return;
    const frame = requestAnimationFrame(() => noticeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    return () => cancelAnimationFrame(frame);
  }, [pendingFormat, error]);

  async function generate(format) {
    if (busyRef.current) return;
    setError("");
    if (!chatId) {
      setError("這則訊息尚未同步完成，請稍後再試一次匯出。");
      return;
    }
    if (!user?.token) {
      setError("請先登入後再匯出檔案。");
      return;
    }
    busyRef.current = true;
    setPendingFormat(format);
    const timestamp = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 19).replace(/[:T]/g, "-");
    const baseFilename = sourceFilename ? sourceFilename.replace(/\.[^.]+$/, "") : `分類結果_${timestamp}`;
    try {
      const response = await fetch(apiUrl("/api/exports"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${user.token}` },
        body: JSON.stringify({
          chat_id: chatId, filename: `${baseFilename}_分類結果.${format}`,
          export_type: format, row_count: rows.length, rows, title: baseFilename,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "無法生成檔案，請稍後再試。");
      if (!data.export_id) throw new Error("未收到完成確認，請到匯出檔案確認後再試。");
      if (mountedRef.current) {
        navigate("/collection", { state: { activeView: "exports", exportCreated: data.export_name || "匯出檔案" } });
      }
    } catch (err) {
      if (mountedRef.current) setError(`匯出失敗：${err.message || "請檢查網路連線後再試。"}`);
    } finally {
      busyRef.current = false;
      if (mountedRef.current) setPendingFormat("");
    }
  }

  return (
    <div className="export-generation" aria-busy={!!pendingFormat}>
      <div className="assistant-output-actions assistant-output-actions--multi">
        {["xlsx", "docx"].map((format) => (
          <button key={format} className="assistant-export-btn" type="button" disabled={!!pendingFormat} onClick={() => generate(format)}>
            <i className={pendingFormat === format ? "ri-loader-4-line ri-spin" : format === "xlsx" ? "ri-file-excel-2-line" : "ri-file-word-2-line"} />
            {pendingFormat === format ? "生成中..." : `匯出成 ${format === "xlsx" ? "Excel" : "Word"}`}
          </button>
        ))}
      </div>
      {pendingFormat && <div ref={noticeRef} className="export-generation-status" role="status"><i className="ri-loader-4-line ri-spin" /> 正在生成 {pendingFormat === "xlsx" ? "Excel" : "Word"} 檔案，請稍候，完成後會自動前往匯出檔案。</div>}
      {error && <div ref={noticeRef} className="export-generation-error" role="alert"><i className="ri-error-warning-line" /> {error}</div>}
    </div>
  );
}
