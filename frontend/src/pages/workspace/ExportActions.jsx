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
      setError("This message has not finished syncing. Please try exporting again later.");
      return;
    }
    if (!user?.token) {
      setError("Please log in to export files.");
      return;
    }
    busyRef.current = true;
    setPendingFormat(format);
    const timestamp = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 19).replace(/[:T]/g, "-");
    const baseFilename = sourceFilename ? sourceFilename.replace(/\.[^.]+$/, "") : `classification_results_${timestamp}`;
    try {
      const response = await fetch(apiUrl("/api/exports"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${user.token}` },
        body: JSON.stringify({
          chat_id: chatId, filename: `${baseFilename}_classification_results.${format}`,
          export_type: format, row_count: rows.length, rows, title: baseFilename,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Unable to generate the file. Please try again later.");
      if (!data.export_id) throw new Error("Completion was not confirmed. Check Exported files before retrying.");
      if (mountedRef.current) {
        navigate("/collection", { state: { activeView: "exports", exportCreated: data.export_name || "Exported files" } });
      }
    } catch (err) {
      if (mountedRef.current) setError(`Export failed: ${err.message || "Check your internet connection and try again."}`);
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
            {pendingFormat === format ? "Generating..." : `Export as  ${format === "xlsx" ? "Excel" : "Word"}`}
          </button>
        ))}
      </div>
      {pendingFormat && <div ref={noticeRef} className="export-generation-status" role="status"><i className="ri-loader-4-line ri-spin" /> Generating {pendingFormat === "xlsx" ? "Excel" : "Word"}  file. Please wait. Exported files will open when it is ready.</div>}
      {error && <div ref={noticeRef} className="export-generation-error" role="alert"><i className="ri-error-warning-line" /> {error}</div>}
    </div>
  );
}
