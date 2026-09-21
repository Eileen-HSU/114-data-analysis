import { NavLink, Outlet, useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../../../../hooks/AuthContext";
import { t } from "../shared/taxStatus";

export default function TopicDetailLayout() {
  const { topicKey } = useParams();
  const navigate = useNavigate();
  const { user, isLoggedIn } = useAuth();
  const canAccess = isLoggedIn && user?.account_type === "admin";

  if (!canAccess) {
    return <main className="ai-admin-empty"><h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1><button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button></main>;
  }

  return <main className="ai-admin-page topic-detail-layout">
    <NavLink to="/admin/ai" className="back">← {t("所有主題", "All topics")}</NavLink>
    <nav className="topic-detail-tabs">
      <NavLink to={`/admin/ai/topics/${topicKey}`} end>{t("分類架構", "Taxonomy")}</NavLink>
      <NavLink to={`/admin/ai/topics/${topicKey}/review`}>{t("分類審查", "Review")}</NavLink>
      <NavLink to={`/admin/ai/topics/${topicKey}/sandbox`}>{t("沙盒測試", "Sandbox")}</NavLink>
    </nav>
    <Outlet />
  </main>;
}
