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

const routes = [
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
  { path: "/survey/create", element: <CreateSurveyPage /> },
  { path: "/survey/fill", element: <FillSurveyPage /> },
  { path: "/survey/fill/:code", element: <FillSurveyPage /> },
  { path: "/s/:code", element: <FillSurveyPage /> },
  { path: "/trash", element: <TrashPage /> },
  { path: "/:code", element: <FillSurveyPage /> },
  { path: "*", element: <HomePage /> },
];

export default routes;
