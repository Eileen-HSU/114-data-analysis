import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import { AuthProvider } from "./hooks/AuthContext";
import Navbar from "./components/feature/Navbar";
import HomePage from "./pages/home/page.jsx";

function SimplePage({ title, description, primaryLabel, primaryPath }) {
  const navigate = useNavigate();

  return (
    <>
      <Navbar />
      <main className="route-page">
        <section className="route-panel">
          <p className="route-eyebrow">DataAnalysis</p>
          <h1>{title}</h1>
          <p>{description}</p>
          <div className="route-actions">
            {primaryLabel && primaryPath && (
              <button className="btn route-primary" onClick={() => navigate(primaryPath)}>
                {primaryLabel}
              </button>
            )}
            <button className="btn route-secondary" onClick={() => navigate("/")}>
              回到首頁
            </button>
          </div>
        </section>
      </main>
    </>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route
            path="/login"
            element={
              <SimplePage
                title="登入帳號"
                description="前端路由已啟用。下一步可以把完整登入表單逐頁接回來。"
                primaryLabel="前往註冊"
                primaryPath="/signup"
              />
            }
          />
          <Route
            path="/signup"
            element={
              <SimplePage
                title="建立帳號"
                description="註冊頁面路由已可進入，先確保 Render 前端互動正常。"
                primaryLabel="前往登入"
                primaryPath="/login"
              />
            }
          />
          <Route
            path="/workspace"
            element={
              <SimplePage
                title="新增工作區"
                description="工作區路由已啟用。完整分析功能可在修好原頁面後接回。"
                primaryLabel="問卷調查"
                primaryPath="/survey"
              />
            }
          />
          <Route
            path="/collection"
            element={
              <SimplePage
                title="我的作品集"
                description="作品集路由已啟用。"
                primaryLabel="新增工作區"
                primaryPath="/workspace"
              />
            }
          />
          <Route
            path="/survey"
            element={
              <SimplePage
                title="問卷調查"
                description="問卷中心路由已啟用。"
                primaryLabel="新增工作區"
                primaryPath="/workspace"
              />
            }
          />
          <Route path="*" element={<HomePage />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
