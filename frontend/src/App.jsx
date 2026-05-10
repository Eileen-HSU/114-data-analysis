import { HashRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { AuthProvider } from "./hooks/AuthContext";
import { CollectionProvider } from "./hooks/CollectionContext";

function App() {
  return (
    <HashRouter>
      <AuthProvider>
        <CollectionProvider>
          <AppRoutes />
        </CollectionProvider>
      </AuthProvider>
    </HashRouter>
  );
}

export default App;
