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
  const [scrolled, setScrolled] = useState(false);
  const { isLoggedIn } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isLoggedIn) {
      navigate("/workspace", { replace: true });
    }
  }, [isLoggedIn, navigate]);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // 已登入時不渲染首頁內容（等待跳轉）
  if (isLoggedIn) return null;

  return (
    <div
      className="min-h-screen relative"
      style={{
        backgroundImage: "url('https://static.readdy.ai/image/db4f710102ca6cc45db44808c8658987/6c450efc85a22c575d9c702bd07d8d93.png')",
        backgroundSize: "cover",
        backgroundPosition: "center",
        backgroundAttachment: "fixed",
      }}
    >
      {/* 全頁遮罩 */}
      <div className="fixed inset-0 bg-gradient-to-b from-black/25 via-black/10 to-black/30 pointer-events-none z-0" />

      <Navbar onLoginRequired={() => setShowLoginModal(true)} scrolled={scrolled} transparent />

      <main className="relative z-10">
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
