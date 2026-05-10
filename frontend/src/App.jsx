import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { AuthProvider } from "./hooks/AuthContext";
import { CollectionProvider } from "./hooks/CollectionContext";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <CollectionProvider>
          <AppRoutes />
        </CollectionProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
