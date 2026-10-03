import { Navigate } from "react-router-dom";
import HomePage from "../pages/home/page.jsx";
import LoginPage from "../pages/auth/LoginPage.jsx";
import SignUpPage from "../pages/auth/SignUpPage.jsx";
import ForgotPasswordPage from "../pages/auth/ForgotPasswordPage.jsx";
import ChangePasswordPage from "../pages/auth/ChangePasswordPage.jsx";
import ResetPasswordPage from "../pages/auth/ResetPasswordPage.jsx";
import LoginTwoFactorPage from "../pages/auth/LoginTwoFactorPage.jsx";
import TwoFactorPage from "../pages/auth/TwoFactorPage.jsx";
import WorkspacePage from "../pages/workspace/page.jsx";
import CollectionPage from "../pages/collection/page.jsx";
import ProfilePage from "../pages/profile/page.jsx";
import SurveyPage from "../pages/survey/SurveyPage.jsx";
import CreateSurveyPage from "../pages/survey/CreateSurveyPage.jsx";
import FillSurveyPage from "../pages/survey/FillSurveyPage.jsx";
import TrashPage from "../pages/trash/TrashPage.jsx";
import AiAdminPage from "../pages/admin/AiAdminPage.jsx";
import TopicDetailLayout from "../pages/admin/ai-admin/TopicDetail/TopicDetailLayout.jsx";
import TaxonomyPanel from "../pages/admin/ai-admin/TopicDetail/TaxonomyPanel.jsx";
import { TopicReviewRedirect } from "../pages/admin/ai-admin/TopicDetail/TopicDetailLayout.jsx";
import AnswersPanel from "../pages/admin/ai-admin/TopicDetail/AnswersPanel.jsx";
import SandboxPanel from "../pages/admin/ai-admin/TopicDetail/SandboxPanel.jsx";
import ReportAdminPage from "../pages/admin/ai-admin/ReportAdminPage.jsx";
import AdminLayout from "../pages/admin/ai-admin/shared/AdminLayout.jsx";
import ReviewHubPage from "../pages/admin/ai-admin/ReviewHubPage.jsx";
import TaxonomyHubPage from "../pages/admin/ai-admin/TaxonomyHubPage.jsx";
import SystemLogPage from "../pages/admin/ai-admin/SystemLogPage.jsx";

import SharedWorkspacePage from "../pages/workspace/SharedWorkspacePage.jsx";

const routes = [
  { path: "/shared/:shareCode", element: <SharedWorkspacePage /> },
  { path: "/", element: <HomePage /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/signup", element: <SignUpPage /> },
  { path: "/forgot-password", element: <ForgotPasswordPage /> },
  { path: "/reset-password", element: <ResetPasswordPage /> },
  { path: "/change-password", element: <ChangePasswordPage /> },
  { path: "/login/two-factor", element: <LoginTwoFactorPage /> },
  { path: "/two-factor", element: <TwoFactorPage /> },
  { path: "/workspace", element: <WorkspacePage /> },
  { path: "/collection", element: <CollectionPage /> },
  { path: "/profile", element: <ProfilePage /> },
  { path: "/survey", element: <SurveyPage /> },
  { path: "/survey/ppt", element: <SurveyPage pptOnly /> },
  { path: "/survey/create", element: <CreateSurveyPage /> },
  { path: "/survey/fill", element: <FillSurveyPage /> },
  { path: "/survey/fill/:code", element: <FillSurveyPage /> },
  { path: "/s/:code", element: <FillSurveyPage /> },
  { path: "/trash", element: <TrashPage /> },
  // Admin：固定左側導覽（總覽／分類審查／分類架構／報告管理／系統管理）
  {
    path: "/admin/ai",
    element: <AdminLayout />,
    children: [
      { index: true, element: <AiAdminPage /> },
      { path: "review", element: <ReviewHubPage /> },
      { path: "taxonomy", element: <TaxonomyHubPage /> },
      { path: "reports", element: <ReportAdminPage /> },
      { path: "system", element: <SystemLogPage /> },
      // 舊網址
      { path: "unassigned", element: <Navigate to="/admin/ai/review?view=unassigned" replace /> },
      { path: "new-categories", element: <Navigate to="/admin/ai/taxonomy?view=candidates" replace /> },
      {
        path: "topics/:topicKey",
        element: <TopicDetailLayout />,
        children: [
          { index: true, element: <TaxonomyPanel /> },
          { path: "answers", element: <AnswersPanel /> },
          { path: "sandbox", element: <SandboxPanel /> },
          { path: "review", element: <TopicReviewRedirect /> },
        ],
      },
    ],
  },
  { path: "/:code", element: <FillSurveyPage /> },
  { path: "*", element: <HomePage /> },
];

export default routes;
