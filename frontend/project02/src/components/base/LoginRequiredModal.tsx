// 未登入警告 Modal - 亮色系 + 中文化
import { Link } from "react-router-dom";

interface LoginRequiredModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const LoginRequiredModal: React.FC<LoginRequiredModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-[100] flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white border border-slate-100 rounded-2xl p-8 max-w-sm w-full relative"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 圖示 */}
        <div className="w-16 h-16 flex items-center justify-center bg-sky-50 border border-sky-100 rounded-2xl mx-auto mb-5">
          <i className="ri-lock-line text-3xl text-sky-500"></i>
        </div>

        {/* 標題與說明 */}
        <h2 className="text-xl font-black text-slate-800 text-center mb-2">需要登入</h2>
        <p className="text-base text-slate-500 text-center mb-6 leading-relaxed">
          您需要登入或建立帳號才能使用此功能。加入 DataAnalysis，開始分析您的資料。
        </p>

        {/* 按鈕群組 */}
        <div className="flex flex-col gap-3">
          <Link
            to="/signup"
            onClick={onClose}
            className="w-full py-3.5 bg-gradient-to-r from-sky-500 to-cyan-500 text-white text-base font-bold rounded-xl text-center hover:from-sky-400 hover:to-cyan-400 transition-all whitespace-nowrap cursor-pointer"
          >
            <i className="ri-user-add-line mr-2"></i>
            建立帳號
          </Link>
          <Link
            to="/login"
            onClick={onClose}
            className="w-full py-3.5 border border-slate-200 text-slate-600 text-base font-semibold rounded-xl text-center hover:bg-slate-50 transition-colors whitespace-nowrap cursor-pointer"
          >
            <i className="ri-login-box-line mr-2"></i>
            登入帳號
          </Link>
        </div>

        {/* 關閉按鈕 */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 w-8 h-8 flex items-center justify-center text-slate-400 hover:text-slate-600 cursor-pointer transition-colors"
        >
          <i className="ri-close-line text-xl"></i>
        </button>
      </div>
    </div>
  );
};

export default LoginRequiredModal;
