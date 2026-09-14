export default function LoginRequiredModal({
  message = "此功能需要登入帳號才能使用。",
  onLogin,
  onCancel,
}) {
  return (
    <div className="login-required-backdrop" onClick={onCancel}>
      <div className="login-required-modal" onClick={(e) => e.stopPropagation()}>
        <div className="login-required-icon">
          <i className="ri-lock-line"></i>
        </div>
        <h2 className="login-required-title">需要登入</h2>
        <p className="login-required-desc">{message}</p>
        <button className="btn-login-now" onClick={onLogin}>
          <i className="ri-login-box-line me-2"></i>
          前往登入
        </button>
        <button className="btn-cancel-modal" onClick={onCancel}>
          取消
        </button>
      </div>
    </div>
  );
}
