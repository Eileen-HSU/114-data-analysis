const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  try {
    for (const selected of [null, 'en', 'zh-TW']) {
      const context = await browser.newContext();
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      let releaseProfile;
      const delayedProfile = new Promise(resolve => { releaseProfile = resolve; });
      await page.route('**/api/profile/*', async route => {
        if (route.request().method() === 'GET') await delayedProfile;
        await route.fulfill({ json: { language: selected === 'en' ? 'zh-TW' : 'en' } });
      });
      await page.route('**/__language_session__', route => route.fulfill({
        contentType: 'text/html',
        body: '<div id="root"></div><script type="module" src="/scripts/fixtures/language-session.jsx"></script>',
      }));
      await page.goto(`${process.env.TEST_BASE_URL || 'http://127.0.0.1:4175'}/__language_session__`);
      await page.locator('#language').waitFor();
      if (selected) await page.locator(selected === 'en' ? '#english' : '#chinese').click();
      const expected = selected || 'zh-TW';
      const verify = async (language, stored = language) => {
        await page.waitForFunction(value => document.documentElement.lang === value, language);
        assert.equal(await page.locator('#language').textContent(), language);
        assert.equal(await page.evaluate(() => localStorage.getItem('dataanalysis_language')), stored);
      };
      await verify(expected, selected);
      await page.locator('#login').click();
      await verify(expected, selected);
      // A manual choice while the profile is loading must survive its late response.
      await page.locator('#english').click();
      await verify('en');
      releaseProfile();
      await page.waitForFunction(value => document.getElementById('profile').textContent === value, selected === 'en' ? 'zh-TW' : 'en');
      await verify('en');
      await page.reload();
      await page.locator('#language').waitFor();
      await verify('en');
      await page.locator('#logout').click();
      await verify('en');
      await page.locator('#chinese').click();
      await verify('zh-TW');
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log('PASS: login, delayed profile, refresh, logout, and manual language switching.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
