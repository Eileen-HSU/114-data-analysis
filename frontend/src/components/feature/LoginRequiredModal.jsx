export default function LoginRequiredModal({
  message = "Please log in to use this feature.",
  onLogin,
  onCancel,
}) {
  return (
    <div className="login-required-backdrop" onClick={onCancel}>
      <div className="login-required-modal" onClick={(e) => e.stopPropagation()}>
        <div className="login-required-icon">
          <i className="ri-lock-line"></i>
        </div>
        <h2 className="login-required-title">Login required</h2>
        <p className="login-required-desc">{message}</p>
        <button className="btn-login-now" onClick={onLogin}>
          <i className="ri-login-box-line me-2"></i>
          Go to login
        </button>
        <button className="btn-cancel-modal" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
