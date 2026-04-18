import { RouteObject } from "react-router-dom";
import HomePage from "@/pages/home/page";
import SignUpPage from "@/pages/auth/SignUpPage";
import LoginPage from "@/pages/auth/LoginPage";
import ForgotPasswordPage from "@/pages/auth/ForgotPasswordPage";
import ProfilePage from "@/pages/profile/page";
import CollectionPage from "@/pages/collection/page";
import WorkspacePage from "@/pages/workspace/page";
import NotFound from "@/pages/NotFound";

const routes: RouteObject[] = [
  { path: "/", element: <HomePage /> },
  { path: "/signup", element: <SignUpPage /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/forgot-password", element: <ForgotPasswordPage /> },
  { path: "/profile", element: <ProfilePage /> },
  { path: "/collection", element: <CollectionPage /> },
  { path: "/workspace", element: <WorkspacePage /> },
  { path: "*", element: <NotFound /> },
];

export default routes;
