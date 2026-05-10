const backendUrl =
  import.meta.env.VITE_API_BASE_URL || "https://one14-data-analysis.onrender.com";

function App() {
  return (
    <main className="deploy-page">
      <section className="deploy-hero">
        <div className="deploy-copy">
          <p className="deploy-eyebrow">DataAnalysis</p>
          <h1>資料分析平台前端已啟動</h1>
          <p className="deploy-subtitle">
            這是重新部署到 Render Static Site 的前端入口。後端 API 會連到你已完成的 Render
            服務。
          </p>
          <div className="deploy-actions">
            <a className="deploy-primary" href={`${backendUrl}/api/status`}>
              檢查後端狀態
            </a>
            <a className="deploy-secondary" href={backendUrl}>
              開啟後端服務
            </a>
          </div>
        </div>

        <div className="deploy-panel" aria-label="Deployment settings">
          <div className="panel-row">
            <span>Frontend</span>
            <strong>Render Static Site</strong>
          </div>
          <div className="panel-row">
            <span>Build</span>
            <strong>npm ci && npm run build</strong>
          </div>
          <div className="panel-row">
            <span>Publish</span>
            <strong>dist</strong>
          </div>
          <div className="panel-row">
            <span>Backend API</span>
            <strong>{backendUrl}</strong>
          </div>
        </div>
      </section>
    </main>
  );
}

export default App;
