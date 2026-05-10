import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./hooks/AuthContext";
import HomePage from "./pages/home/page.jsx";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <HomePage />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
