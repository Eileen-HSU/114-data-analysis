const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4176';
const scenarios = [
  { language: 'en', profileLanguage: 'zh-TW' },
  { language: 'zh-TW', profileLanguage: 'en' },
  { language: 'en', profileLanguage: undefined },
  { language: 'zh-TW', profileLanguage: undefined },
  { language: 'en', profileLanguage: 'zh-TW', twoFactor: true },
];

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  try {
    for (const scenario of scenarios) {
      const { language, profileLanguage, twoFactor } = scenario;
      const page = await browser.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(() => {
        window.languageWrites = [];
        window.languageFrames = [];
        for (const method of ['setItem', 'removeItem', 'clear']) {
          const original = Storage.prototype[method];
          Storage.prototype[method] = function (...args) {
            if (this === localStorage && (args[0] === 'dataanalysis_language' || method === 'clear')) {
              window.languageWrites.push({ method, value: args[1] ?? null });
            }
            return original.apply(this, args);
          };
        }
        const sample = () => {
          if (localStorage.getItem('dataanalysis_language') === 'en') {
            for (const node of document.querySelectorAll('.auth-title, .sidebar-title, .sidebar-search input')) {
              const text = node.placeholder || node.textContent;
              if (/[\u4e00-\u9fff]/.test(text)) window.languageFrames.push({ path: location.pathname, text });
            }
          }
          requestAnimationFrame(sample);
        };
        requestAnimationFrame(sample);
      });

      let profileRequests = 0;
      let expectedRequestLanguage = language;
      const wrongHeaders = [];
      const profileWrites = [];
      await page.route('**/api/**', async route => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        const user = { user_id: 123, user_name: 'Test', email: 'test@example.com', account_type: 'user', language: profileLanguage };
        let json = [];
        if (path === '/api/login' || path === '/api/profile/123' || path === '/api/auth/2fa/login/two-factor') {
          if (request.headers()['accept-language'] !== expectedRequestLanguage) wrongHeaders.push({ path, method: request.method(), language: request.headers()['accept-language'], expected: expectedRequestLanguage });
        }
        if (path === '/api/login') json = { ...user, token: 'test', requires_2fa: !!twoFactor, pre_auth_token: 'test-pending' };
        if (path === '/api/auth/2fa/login/two-factor') json = { user, token: 'test' };
        if (path === '/api/profile/123') {
          if (request.method() === 'GET') {
            await new Promise(resolve => setTimeout(resolve, 250));
            profileRequests++;
          } else {
            profileWrites.push(request.postDataJSON());
          }
          json = { ...user, language: profileLanguage };
        }
        await route.fulfill({ json });
      });

      const verify = async (expected, writes) => {
        await page.waitForFunction(value => document.documentElement.lang === value, expected);
        assert.equal(await page.locator('.nav-language-switcher .active').textContent(), expected === 'en' ? 'EN' : '中');
        assert.equal(await page.evaluate(() => localStorage.getItem('dataanalysis_language')), expected);
        assert.deepEqual(await page.evaluate(() => window.languageWrites), writes, 'Only a manual UI choice may write language storage');
        assert.deepEqual(await page.evaluate(() => window.languageFrames), [], 'English navigation must not paint Chinese UI');
      };
      const choose = async value => {
        expectedRequestLanguage = value;
        const saved = await page.locator('.nav-user-btn').count()
          ? page.waitForResponse(response => response.url().endsWith('/api/profile/123') && response.request().method() === 'PUT')
          : null;
        await page.locator('.nav-language-switcher button').filter({ hasText: value === 'en' ? 'EN' : '中' }).click();
        if (saved) await saved;
      };
      await page.goto(baseURL);
      await page.locator('.nav-language-switcher').waitFor();
      assert.deepEqual(await page.evaluate(() => window.languageWrites), [], 'First-use fallback must not write a language preference');
      await choose(language);
      let writes = [{ method: 'setItem', value: language }];
      await verify(language, writes);
      await page.locator('.nav-login-btn').click();
      // The existing login form clears autofilled fields after 200 ms.
      await page.waitForTimeout(300);
      await page.locator('input[type="email"]').fill('test@example.com');
      await page.locator('input[type="password"]').fill('test-password');
      await page.locator('button[type="submit"]').click();
      if (twoFactor) {
        await page.waitForURL('**/login/two-factor');
        await page.waitForTimeout(300);
        await page.locator('input').fill('123456');
        await page.locator('button[type="submit"]').click();
      }
      await page.waitForURL('**/workspace');
      await page.waitForFunction(() => JSON.parse(localStorage.getItem('dataanalysis_auth'))?.email_2fa_enabled === false);
      assert.ok(profileRequests > 0);
      await verify(language, writes);
      assert.equal(await page.locator('.sidebar-title').textContent(), language === 'en' ? 'Conversation history' : '歷史對話紀錄');
      assert.deepEqual(profileWrites, [], 'Login/profile initialization must not save any language preference');

      // Cases 3 and 4: reload reads persistence without writing it back.
      const refreshProfile = page.waitForResponse(response => response.url().endsWith('/api/profile/123') && response.request().method() === 'GET');
      await page.reload();
      await page.locator('.sidebar-title').waitFor();
      await refreshProfile;
      await verify(language, []);

      // Cases 5 and 6: explicitly switch after login, navigate, load profile, logout.
      await choose('zh-TW');
      await choose('en');
      writes = [{ method: 'setItem', value: 'zh-TW' }, { method: 'setItem', value: 'en' }];
      await verify('en', writes);
      await page.locator('a.nav-link-btn[href="/survey"]').click();
      await page.waitForURL('**/survey');
      await verify('en', writes);
      await page.locator('.nav-user-btn').click();
      const profileResponse = page.waitForResponse(response => response.url().endsWith('/api/profile/123') && response.request().method() === 'GET');
      await page.locator('.nav-user-dropdown a[href="/profile"]').press('Enter');
      await page.waitForURL('**/profile');
      await profileResponse;
      await page.waitForTimeout(50);
      await verify('en', writes);
      await page.locator('.nav-user-btn').click();
      await page.locator('.nav-user-dropdown a.text-danger').press('Enter');
      await page.waitForURL(url => url.pathname === '/');
      await verify('en', writes);
      assert.deepEqual(wrongHeaders, [], 'API request locale must match the current manual selection');
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS: ${language}, profile=${profileLanguage ?? 'missing'}, 2FA=${!!twoFactor}; login, refresh, manual switch, navigation, logout; no automatic language writes.`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
