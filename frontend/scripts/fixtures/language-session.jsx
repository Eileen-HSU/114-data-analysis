import React from 'react';
import { createRoot } from 'react-dom/client';
import { AuthProvider, useAuth } from '../../src/hooks/AuthContext';
import { LanguageProvider, useLanguage } from '../../src/context/LanguageContext';

function Session() {
  const { login, logout, user } = useAuth();
  const { language, setLanguage } = useLanguage();
  return <div>
    <output id="language">{language}</output>
    <output id="account">{user?.language || 'guest'}</output>
    <button id="english" onClick={() => setLanguage('en')}>English</button>
    <button id="chinese" onClick={() => setLanguage('zh-TW')}>Chinese</button>
    <button id="login" onClick={() => login({ user_id: 123, token: 'test', language: language === 'en' ? 'zh-TW' : 'en' })}>Login</button>
    <button id="logout" onClick={logout}>Logout</button>
  </div>;
}
createRoot(document.getElementById('root')).render(<AuthProvider><LanguageProvider><Session /></LanguageProvider></AuthProvider>);
