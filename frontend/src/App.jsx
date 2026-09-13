import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { AuthProvider } from "./hooks/AuthContext";
import { ActivityProvider } from "./hooks/ActivityContext";
import { CollectionProvider } from "./hooks/CollectionContext";
import { LanguageProvider } from "./context/LanguageContext";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <LanguageProvider>
          <ActivityProvider>
            <CollectionProvider>
              <AppRoutes />
            </CollectionProvider>
          </ActivityProvider>
        </LanguageProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
