import { useEffect, useState } from "react";
import { api } from "./apiClient";
import { t } from "./taxStatus";
import { errorMessage } from "./reviewStates";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

// 系統狀態頁：安全標頭模式提示 + CSP 違規回報彙總
export default function SecurityHeadersPanel({ token }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/admin/security/csp", token).then(setData).catch((e) => setError(errorMessage(e)));
  }, [token]);

  if (error) return <p className="ai-admin-error">{error}</p>;
  if (!data) return null;
  const reportOnly = data.mode !== "enforce";
  return (
    <section className="admin-section" style={{ marginTop: 16 }}>
      <h3>{t("安全標頭（CSP）", "Security headers (CSP)")}</h3>
      <p>
        <b>{reportOnly
          ? t("Report-Only 模式（尚未阻擋）", "Report-Only mode (not blocking yet)")
          : t("正式阻擋模式", "Enforcing")}</b>
        {" — "}
        {reportOnly
          ? t("瀏覽器只回報違規、不會擋任何資源；確認下方沒有誤報後，再改為正式阻擋。",
              "Browsers only report violations and block nothing. Switch to enforcing once the list below has no false positives.")
          : t("違規的資源會被瀏覽器阻擋。", "Violating resources are blocked by browsers.")}
      </p>
      <p><small>{t(`共 ${data.total_reports} 次回報、${data.distinct} 種不同違規。網址只保留網域與路徑。`,
        `${data.total_reports} reports, ${data.distinct} distinct violations. URLs keep only host and path.`)}</small></p>
      {data.items.length === 0 ? (
        <p>{t("目前沒有違規回報。", "No violation reports.")}</p>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr>
              <th>{t("被擋的資源", "Blocked resource")}</th><th>{t("規則", "Directive")}</th><th>{t("發生頁面", "Page")}</th>
              <th>{t("次數", "Count")}</th><th>{t("最後一次", "Last seen")}</th>
            </tr></thead>
            <tbody>
              {data.items.map((r, i) => (
                <tr key={i}>
                  <td>{r.blocked}</td><td>{r.directive}</td><td>{r.document_path || "—"}</td>
                  <td>{r.count}</td><td>{fmt(r.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
