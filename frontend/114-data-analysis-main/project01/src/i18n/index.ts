import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import messages from './local/index';

// Configure the detector to use the same localStorage key as the legacy app
const detector = new LanguageDetector();
detector.init({
  order: ['localStorage', 'navigator'],
  caches: ['localStorage'],
  lookupLocalStorage: 'dataanalysis_language',
});

i18n
  .use(detector)
  .use(initReactI18next)
  .init({
    lng: localStorage.getItem('dataanalysis_language') || 'en',
    fallbackLng: 'en',
    debug: false,
    resources: messages,
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;