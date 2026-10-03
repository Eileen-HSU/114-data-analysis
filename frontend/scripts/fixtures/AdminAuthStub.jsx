// check-new-category-page.mjs 用：固定回傳已登入的 admin。
export const useAuth = () => ({ user: { token: "test-token", account_type: "admin" }, isLoggedIn: true });
