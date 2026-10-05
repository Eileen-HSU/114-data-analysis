import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/AuthContext";
import { apiUrl } from "../../lib/api";
import { translateInterfaceText, useLanguage } from "../../context/LanguageContext";

export default function ExportActions({ rows, ratingStats, chatId, sourceFilename }) {
  const { language } = useLanguage();
  const isEnglish = language === "en";
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

  async function generate(format, event) {
    if (event?.detail > 1) return;
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
    // 預設檔名 / 標題與檔名後綴是「系統產生的固定文字」，語言 = 介面語言（ui_lang）；
    // sourceFilename 是使用者上傳的原始檔名（使用者的資料），維持原樣。
    // 這個 baseFilename 也會當成 title 送給後端，變成 Excel 的分頁名稱，所以英文介面時一定要是英文。
    const resultsLabel = isEnglish ? "Classification_results" : "分類結果";
    const baseFilename = sourceFilename ? sourceFilename.replace(/\.[^.]+$/, "") : `${resultsLabel}_${timestamp}`;
    // 【新增｜評分題統計】ratingStats 是可選欄位，沒有評分題（或是 Excel
    // 上傳分類，本來就沒有這個概念）時是 undefined/[]，後端 create_export
    // 收到空值時行為跟這個欄位新增之前完全一樣，不會多產生任何 sheet/section。
    try {
      const response = await fetch(apiUrl("/api/exports"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${user.token}` },
        body: JSON.stringify({
          chat_id: chatId, filename: `${baseFilename}_${resultsLabel}.${format}`,
          export_type: format, row_count: rows.length, rows, title: baseFilename,
          rating_stats: ratingStats && ratingStats.length > 0 ? ratingStats : undefined,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "無法生成檔案，請稍後再試。");
      if (!data.export_id) throw new Error("未收到完成確認，請到匯出檔案確認後再試。");
      if (mountedRef.current) {
        navigate("/collection", { state: { activeView: "exports", exportCreated: data.export_name || "匯出檔案" } });
      }
    } catch (err) {
      if (mountedRef.current) setError(err.message || "請檢查網路連線後再試。");
    } finally {
      busyRef.current = false;
      if (mountedRef.current) setPendingFormat("");
    }
  }

  return (
    <div className="export-generation" aria-busy={!!pendingFormat}>
      <div className="assistant-output-actions assistant-output-actions--multi">
        {["xlsx", "docx"].map((format) => (
          <button key={format} className="assistant-export-btn" type="button" disabled={!!pendingFormat} onClick={(event) => generate(format, event)}>
            <i className={pendingFormat === format ? "ri-loader-4-line ri-spin" : format === "xlsx" ? "ri-file-excel-2-line" : "ri-file-word-2-line"} />
            <span data-localized>{pendingFormat === format ? (isEnglish ? "Generating…" : "生成中...") : `${isEnglish ? "Export to" : "匯出成"} ${format === "xlsx" ? "Excel" : "Word"}`}</span>
          </button>
        ))}
      </div>
      {pendingFormat && <div ref={noticeRef} className="export-generation-status" role="status" data-localized><i className="ri-loader-4-line ri-spin" />{isEnglish ? "Generating " : "正在生成 "}{pendingFormat === "xlsx" ? "Excel" : "Word"}{isEnglish ? ". Please wait. You will be taken to Exported files when it is ready." : " 檔案，請稍候，完成後會自動前往匯出檔案。"}</div>}
      {error && <div ref={noticeRef} className="export-generation-error" role="alert" data-localized><i className="ri-error-warning-line" /> {translateInterfaceText(error, language)}</div>}
    </div>
  );
}
