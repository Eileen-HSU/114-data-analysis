import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { AuthProvider } from "./hooks/AuthContext";
import { ActivityProvider } from "./hooks/ActivityContext";
import { CollectionProvider } from "./hooks/CollectionContext";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ActivityProvider>
          <CollectionProvider>
            <AppRoutes />
          </CollectionProvider>
        </ActivityProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
