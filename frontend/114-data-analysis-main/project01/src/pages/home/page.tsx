// 首頁主元件 - 亮色系
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "@/components/feature/Navbar";
import LoginRequiredModal from "@/components/base/LoginRequiredModal";
import HeroSection from "./components/HeroSection";
import FeaturesSection from "./components/FeaturesSection";
import HowItWorksSection from "./components/HowItWorksSection";
import CtaSection from "./components/CtaSection";
import { useAuth } from "@/hooks/useAuth";

const HomePage: React.FC = () => {
  const [showLoginModal, setShowLoginModal] = useState(false);
  const { isLoggedIn } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isLoggedIn) {
      navigate("/workspace", { replace: true });
    }
  }, [isLoggedIn, navigate]);

  // 已登入時不渲染首頁內容（等待跳轉）
  if (isLoggedIn) return null;

  return (
    <div className="min-h-screen bg-white">
      <Navbar onLoginRequired={() => setShowLoginModal(true)} />

      <main>
        <HeroSection />
        <FeaturesSection />
        <HowItWorksSection />
        <CtaSection />
      </main>

      <LoginRequiredModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} />
    </div>
  );
};

export default HomePage;
