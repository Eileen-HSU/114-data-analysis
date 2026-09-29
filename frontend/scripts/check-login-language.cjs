const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  try {
    for (const language of ['en', 'zh-TW']) {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      window.languageFrames = [];
      const sample = () => {
        if (localStorage.getItem('dataanalysis_language') === 'en') {
          for (const title of document.querySelectorAll('.auth-title, .sidebar-title, .sidebar-search input')) {
            const text = title.placeholder || title.textContent;
            if (/[\u4e00-\u9fff]/.test(text)) window.languageFrames.push({ path: location.pathname, text });
          }
        }
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let profileRequests = 0;
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const accountLanguage = language === 'en' ? 'zh-TW' : 'en';
      if (path === '/api/profile/123') {
        await new Promise(resolve => setTimeout(resolve, 250));
        profileRequests++;
      }
      const json = path === '/api/login' ? { user_id: 123, user_name: 'Test', token: 'test', account_type: 'user', language: accountLanguage }
        : path === '/api/profile/123' ? { language: accountLanguage, user_name: 'Test' }
        : [];
      await route.fulfill({ json });
    });
    await page.goto(process.env.TEST_BASE_URL || 'http://127.0.0.1:4176');
    const label = language === 'en' ? 'EN' : '中';
    await page.locator('.nav-language-switcher button').filter({ hasText: label }).click();
    await page.locator('.nav-login-btn').click();
    await page.waitForTimeout(300);
    await page.locator('input[type="email"]').fill('test@example.com');
    await page.locator('input[type="password"]').fill('test-password');
    await page.locator('button[type="submit"]').click();
    await page.waitForURL('**/workspace');
    await page.waitForTimeout(1500);
    const verify = async () => {
      assert.equal(await page.locator('html').getAttribute('lang'), language);
      assert.equal(await page.locator('.nav-language-switcher .active').textContent(), label);
      assert.equal(await page.evaluate(() => localStorage.getItem('dataanalysis_language')), language);
      assert.deepEqual(await page.evaluate(() => window.languageFrames), [], 'English navigation must never paint Chinese UI');
    };
    assert.ok(profileRequests > 0, 'Login must exercise loading the account profile');
    await verify();
    assert.equal(await page.locator('.sidebar-title').textContent(), language === 'en' ? 'Conversation history' : '歷史對話紀錄');
    await page.reload();
    await page.locator('.sidebar-title').waitFor();
    await verify();
    await page.locator('.nav-user-btn').click();
    await page.locator('.nav-user-dropdown a.text-danger').press('Enter');
    await page.waitForURL(url => url.pathname === '/');
    await verify();
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`PASS: ${language} homepage, login with opposite account language, workspace text, refresh, logout, and frame checks.`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
