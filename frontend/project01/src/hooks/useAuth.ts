// 使用者認證狀態管理 Hook
// 使用 localStorage 模擬登入狀態持久化

import { useState, useEffect } from "react";
import { mockUser } from "@/mocks/auth";

// 使用者資料型別定義
export interface User {
  id: string;
  name: string;
  email: string;
  avatar: string;
  joinDate: string;
  bio: string;
}

// Auth Hook 回傳型別
export interface AuthState {
  isLoggedIn: boolean;
  user: User | null;
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => void;
  signup: (name: string, email: string, password: string) => Promise<boolean>;
}

// localStorage 的 key 名稱
const AUTH_KEY = "datalens_auth";

export const useAuth = (): AuthState => {
  // 從 localStorage 讀取初始登入狀態
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(() => {
    const stored = localStorage.getItem(AUTH_KEY);
    return stored ? JSON.parse(stored).isLoggedIn : false;
  });

  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem(AUTH_KEY);
    return stored ? JSON.parse(stored).user : null;
  });

  // 當狀態改變時同步到 localStorage
  useEffect(() => {
    localStorage.setItem(AUTH_KEY, JSON.stringify({ isLoggedIn, user }));
  }, [isLoggedIn, user]);

  /**
   * 模擬登入功能
   * 實際專案中應呼叫 Supabase Auth API
   */
  const login = async (email: string, _password: string): Promise<boolean> => {
    // 模擬 API 延遲
    await new Promise((resolve) => setTimeout(resolve, 800));

    // 前端 mock：任何 email/password 組合都可登入
    const loggedInUser: User = {
      ...mockUser,
      email: email || mockUser.email,
    };

    setIsLoggedIn(true);
    setUser(loggedInUser);
    return true;
  };

  /**
   * 模擬登出功能
   */
  const logout = () => {
    setIsLoggedIn(false);
    setUser(null);
    localStorage.removeItem(AUTH_KEY);
  };

  /**
   * 模擬註冊功能
   * 實際專案中應呼叫 Supabase Auth API
   */
  const signup = async (
    name: string,
    email: string,
    _password: string
  ): Promise<boolean> => {
    // 模擬 API 延遲
    await new Promise((resolve) => setTimeout(resolve, 1000));

    const newUser: User = {
      ...mockUser,
      name: name || mockUser.name,
      email: email || mockUser.email,
    };

    setIsLoggedIn(true);
    setUser(newUser);
    return true;
  };

  return { isLoggedIn, user, login, logout, signup };
};
