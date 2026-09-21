import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../../../hooks/AuthContext";
import { t } from "./shared/taxStatus";
import ClassificationList from "./shared/ClassificationList";

// internal-only query value，見 backend routes/admin/ai_admin.py 的
// reviewed_classifications() 說明；這個字串不會顯示在畫面上。
const UNASSIGNED_TOPIC_PARAM = "__unassigned__";

export default function UnassignedReviewPage() {
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const canAccess = isLoggedIn && user?.account_type === "admin";

  if (!canAccess) {
    return <main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main>;
  }

  return <main className="ai-admin-page">
    <NavLink to="/admin/ai" className="back">← {t("所有主題", "All topics")}</NavLink>
    <h1>{t("其他 / 未歸屬資料", "Other / Unassigned Data")}</h1>
    <p><small>{t("這裡列出不屬於任何目前分析主題的分類結果（例如系統判斷不出主題，或較早期的歷史資料）。", "Classifications that don't belong to any current analysis topic (e.g. topic couldn't be determined, or older historical data).")}</small></p>
    <ClassificationList topicParam={UNASSIGNED_TOPIC_PARAM} />
  </main>;
}
