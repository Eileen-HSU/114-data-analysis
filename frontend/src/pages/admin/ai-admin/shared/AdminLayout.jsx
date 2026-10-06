import { Link, NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import Navbar from "../../../../components/feature/Navbar";
import { useAuth } from "../../../../hooks/AuthContext";
import { t } from "./taxStatus";

// Admin 共用外框：固定左側導覽 + 內容區。權限檢查集中在這裡。
const NAV = [
  { to: "/admin/ai", end: true, icon: "ri-dashboard-line", zh: "總覽", en: "Overview" },
  { to: "/admin/ai/review", icon: "ri-checkbox-multiple-line", zh: "分類審查", en: "Review" },
  // 主題詳細頁（/admin/ai/topics/...）屬於分類架構
  { to: "/admin/ai/taxonomy", icon: "ri-node-tree", zh: "分類架構", en: "Taxonomy", also: "/admin/ai/topics/" },
  { to: "/admin/ai/reports", icon: "ri-file-chart-line", zh: "報告管理", en: "Reports" },
  { to: "/admin/ai/system", icon: "ri-settings-3-line", zh: "系統管理", en: "System" },
];

const SYSTEM_VIEWS = {
  status: ["系統狀態", "System status"], jobs: ["背景工作", "Background jobs"],
  errors: ["錯誤紀錄", "Error log"], audit: ["操作紀錄", "Activity log"],
};

// 依目前網址（路徑 + ?view=）決定麵包屑；總覽與主題詳細頁不在這裡處理
// （主題詳細頁需要主題名稱，由 TopicDetailLayout 自己組）。
function crumbsFor(pathname, view) {
  const path = pathname.replace(/\/+$/, "");
  if (path === "/admin/ai/review") {
    return [{ label: t("分類審查", "Review"), to: "/admin/ai/review" },
      { label: view === "unassigned" ? t("無法分類", "Can't classify") : t("待審查", "To review") }];
  }
  if (path === "/admin/ai/taxonomy") {
    return view === "candidates"
      ? [{ label: t("分類架構", "Taxonomy"), to: "/admin/ai/taxonomy" }, { label: t("新類別候選", "New category candidates") }]
      : [{ label: t("分類架構", "Taxonomy") }];
  }
  if (path === "/admin/ai/reports") return [{ label: t("報告管理", "Reports") }];
  if (path === "/admin/ai/system") {
    const tab = SYSTEM_VIEWS[view] || SYSTEM_VIEWS.status;
    return [{ label: t("系統管理", "System"), to: "/admin/ai/system" }, { label: t(...tab) }];
  }
  return null;
}

// 小型麵包屑：第一段「AI 管理」固定可點回總覽；最後一段是目前位置，不可點。
export function AdminBreadcrumb({ items }) {
  const all = [{ label: t("AI 管理", "AI Admin"), to: "/admin/ai" }, ...items];
  return (
    <nav className="admin-breadcrumb" aria-label={t("目前位置", "Breadcrumb")}>
      <ol>
        {all.map((item, i) => {
          const last = i === all.length - 1;
          return <li key={`${i}-${item.label}`}>
            {item.to && !last ? <Link to={item.to}>{item.label}</Link>
              : <span aria-current={last ? "page" : undefined}>{item.label}</span>}
            {!last && <span className="admin-breadcrumb-sep" aria-hidden="true">/</span>}
          </li>;
        })}
      </ol>
    </nav>
  );
}

export default function AdminLayout() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  const crumbs = crumbsFor(pathname, searchParams.get("view"));
  const { user, isLoggedIn } = useAuth();
  const canAccess = isLoggedIn && user?.account_type === "admin";

  if (!canAccess) {
    return <><Navbar /><main className="ai-admin-empty">
      <h1>{t("僅管理者可存取 AI 管理介面", "AI admin access restricted to administrators")}</h1>
      <button onClick={() => navigate("/workspace")}>{t("回到分析助理", "Back to Analysis Assistant")}</button>
    </main></>;
  }

  return <><Navbar />
    <div className="admin-shell">
      <aside className="admin-sidebar" aria-label={t("管理功能", "Admin sections")}>
        <p className="admin-sidebar-title">{t("AI 管理", "AI Admin")}</p>
        <nav>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}
              className={({ isActive }) => `admin-nav-link${isActive || (item.also && pathname.startsWith(item.also)) ? " admin-nav-link--active" : ""}`}>
              <i className={item.icon} aria-hidden="true" />
              <span>{t(item.zh, item.en)}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="ai-admin-page admin-main">
        {crumbs && <AdminBreadcrumb items={crumbs} />}
        <Outlet />
      </main>
    </div>
  </>;
}

// 各頁的標題列（標題＋一句說明），讓每一頁看起來一致
export function AdminPageHeader({ title, description, actions }) {
  return (
    <header className="admin-page-header">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="admin-page-actions">{actions}</div>}
    </header>
  );
}

// 頁內分頁（用網址 ?view= 記住目前分頁，重新整理或分享連結都會回到同一頁）
export function AdminTabs({ tabs, value, onChange }) {
  return (
    <div className="admin-tabs" role="tablist">
      {tabs.map((tab) => (
        <button key={tab.key} role="tab" aria-selected={value === tab.key}
          className={`admin-tab${value === tab.key ? " admin-tab--active" : ""}`} onClick={() => onChange(tab.key)}>
          {tab.label}{tab.count != null && <span className="admin-tab-count">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}
