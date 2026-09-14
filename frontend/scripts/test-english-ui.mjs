import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync } from 'node:fs';

// Run against the local development or preview server. All application API calls are mocked.
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4178';
const output = process.env.TEST_OUTPUT_DIR || 'test-results/english';
mkdirSync(output, { recursive: true });
const chrome = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({ headless: true, ...(existsSync(chrome) ? { executablePath: chrome } : {}) });
const errors = [];
const checked = [];
const survey = { template_id: 1, title: 'Training feedback', description: 'Share your feedback.', access_code: 'ENG123', short_code: 'ENG123', created_at: '2026-09-01T10:00:00', deadline_at: '2099-12-31T23:59:00', identity_mode: 'identified', response_count: 2, questions: [{ id: 1, question_id: 1, type: 'rating', question_type: 'rating', title: 'How useful was the course?', required: true }, { id: 2, question_id: 2, type: 'short', question_type: 'short', title: 'What could improve?', required: true }] };
const responses = [{ respondent_identity: 'Respondent A', submitted_at: '2026-09-01T12:00:00', answers: { 1: 4, 2: 'More examples' } }, { respondent_identity: 'Respondent B', submitted_at: '2026-09-02T12:00:00', answers: { 1: 5, 2: 'More practice' } }];
async function createPage(loggedIn = false, mobile = false) {
  const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 960 }, locale: 'en-US' });
  await context.addInitScript(({ loggedIn }) => {
    localStorage.setItem('dataanalysis_language', 'zh-TW');
    if (loggedIn) localStorage.setItem('dataanalysis_activity_1', JSON.stringify([{ id: 'legacy-1', text: '建立問卷「Training feedback」', createdAt: new Date().toISOString() }])); // Old preferences must not bring Chinese UI back.
    if (loggedIn) localStorage.setItem('dataanalysis_auth', JSON.stringify({ token: 'test-token', user_id: 1, name: 'Test User', email_2fa_enabled: true, email: 'test@example.com', language: 'zh-TW' }));
  }, { loggedIn });
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', async dialog => { assert(!/[\p{Script=Han}]/u.test(dialog.message()), dialog.message()); await dialog.dismiss(); });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname;
    if (p.startsWith('/api/')) {
      let json = [];
      if (p === '/api/profile/1') json = { user_name: 'Test User', email: 'test@example.com', phone_number: '0912345678', company_name: 'Example', gender: '女', language: 'zh-TW', bio: 'Researcher', created_at: '2026-09-01T00:00:00', email_2fa_enabled: true };
      else if (p === '/api/surveys/mine') json = [survey];
      else if (p === '/api/surveys/ENG123/responses') { await new Promise(r => setTimeout(r, 450)); json = { responses }; }
      else if (p === '/api/surveys/ENG123') { await new Promise(r => setTimeout(r, 450)); json = survey; }
      else if (p === '/api/public/surveys/ENG123') json = survey;
      else if (p.startsWith('/api/public/surveys/')) return route.fulfill({ status: 404, json: { error: 'Survey not found' } });
      else if (p === '/api/workspace/user') json = [{ project_id: 7, project_name: 'Training analysis', created_at: '2026-09-01' }];
      else if (p === '/api/workspace/7/share') { await new Promise(r => setTimeout(r, 450)); json = { share_code: 'ENGLISH123' }; }
      else if (p.includes('/public/workspace/')) json = { project_name: 'Training analysis', messages: [] };
      else if (p === '/api/chat/history/7') json = { chat_history: [] };
      else if (p === '/api/surveys' && request.method() === 'POST') json = { access_code: 'ENG123', short_code: 'ENG123', template_id: 1 };
      else if (p.includes('submit')) json = { message: 'Survey submitted successfully' };
      else if (p.includes('forgot') || p.includes('send')) json = { message: 'Verification code sent' };
      return route.fulfill({ json });
    }
    // No real survey-shortening requests or application writes are allowed.
    if (url.origin !== new URL(base).origin && !['cdn.jsdelivr.net', 'fonts.googleapis.com', 'fonts.gstatic.com'].includes(url.hostname)) return route.abort();
    return route.continue();
  });
  return page;
}
async function audit(page, name) {
  const leftovers = await page.evaluate(() => {
    const bad = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode, parent = node.parentElement;
      if (parent && !parent.closest('script,style') && parent.getClientRects().length && /[\p{Script=Han}]/u.test(node.nodeValue)) bad.push(node.nodeValue.trim());
    }
    for (const el of document.querySelectorAll('input,textarea,[title],[aria-label]')) {
      if (!el.getClientRects().length) continue;
      for (const attr of ['placeholder','title','aria-label']) if (/[\p{Script=Han}]/u.test(el.getAttribute(attr) || '')) bad.push(el.getAttribute(attr));
      if (['INPUT','TEXTAREA'].includes(el.tagName) && /[\p{Script=Han}]/u.test(el.value)) bad.push(el.value);
    }
    return bad;
  });
  assert.deepEqual(leftovers, [], `${name}: untranslated interface text`);
  assert.equal(await page.locator('html').getAttribute('lang'), 'en');
  checked.push(name); console.log("PASS", name);
}
async function open(page, path, name) { await page.goto(base + path); await page.waitForTimeout(180); await audit(page, name); }
try {
  const guest = await createPage();
  for (const path of ['/', '/login', '/signup', '/forgot-password', '/reset-password?email=test@example.com', '/login/two-factor', '/survey', '/survey/fill', '/shared/ENGLISH123']) await open(guest, path, `guest ${path}`);
  await guest.goto(base + '/');
  await guest.locator('.cta-title').scrollIntoViewIfNeeded();
  await audit(guest, 'home lower introduction');
  await guest.screenshot({ path: `${output}/home.png`, fullPage: true });
  await guest.goto(base + '/signup');
  await guest.getByRole('button', { name: 'Select your gender' }).click();
  for (const label of ['Male', 'Female', 'Other', 'Prefer not to say']) assert(await guest.getByRole('option', { name: label, exact: true }).isVisible());
  assert.match(await guest.locator('.password-requirement-note').innerText(), /at least 8 characters, including letters and numbers/);
  await audit(guest, 'signup gender dropdown and red password note');
  await guest.screenshot({ path: `${output}/signup.png`, fullPage: true });
  await guest.goto(base + '/survey/fill');
  await guest.locator('.btn-enter-code').click();
  await guest.getByText('Please enter an invite code.', { exact: true }).waitFor();
  await audit(guest, 'missing invite code validation');
  await guest.getByPlaceholder('Enter invite code', { exact: true }).fill('MISSING');
  await guest.locator('.btn-enter-code').click();
  await guest.getByText('Invite code not found. Please check it and try again.').waitFor();
  await audit(guest, 'invalid invite code');
  await open(guest, '/survey/fill/ENG123', 'survey response form');
  await guest.getByRole('button', { name: /Submit survey/ }).click();
  await audit(guest, 'survey required-answer validation');

  const owner = await createPage(true);
  for (const path of ['/profile', '/survey', '/survey/create', '/collection', '/trash', '/workspace', '/two-factor', '/change-password', '/admin/ai']) await open(owner, path, `signed-in ${path}`);
  await owner.goto(base + '/profile');
  await owner.getByText('Female', { exact: true }).waitFor();
  await owner.getByRole('button', { name: /Edit profile/ }).click();
  await audit(owner, 'profile editing legacy gender');
  await owner.getByRole('button', { name: /Save changes/ }).click();
  await owner.getByRole('button', { name: /Edit profile/ }).waitFor();
  await audit(owner, 'profile save success');
  await owner.getByRole('button', { name: /Recent activity/ }).click();
  await owner.getByText('Created survey: Training feedback', { exact: true }).waitFor();
  await audit(owner, 'legacy activity labels');
  await owner.getByRole('button', { name: /View security settings/ }).click();
  await audit(owner, 'profile security helper text');
  await owner.getByRole('button', { name: /Disable two-factor authentication/ }).click();
  await audit(owner, 'disable two-factor confirmation');
  await owner.getByRole('button', { name: /Cancel/ }).click();
  await owner.goto(base + '/profile?survey=ENG123');
  await owner.getByText('Loading survey details...', { exact: true }).waitFor();
  await owner.getByText('Preparing questions, statistics, and responses. Please wait.').waitFor();
  await audit(owner, 'survey detail loading title and small print');
  await owner.getByText('Rating summary', { exact: true }).waitFor();
  await audit(owner, 'survey detail statistics');
  await owner.getByRole('button', { name: /Response data/ }).click();
  await audit(owner, 'survey response table');
  await owner.screenshot({ path: `${output}/survey-details.png`, fullPage: true });
  await owner.goto(base + '/survey/create');
  await owner.locator('.deadline-picker-trigger').click();
  await audit(owner, 'deadline calendar and time picker');
  await owner.goto(base + '/survey');
  await owner.getByText('Generate a survey from PPT/PDF', { exact: true }).click();
  await audit(owner, 'AI survey dialog helper text');
  await owner.screenshot({ path: `${output}/survey-ai.png`, fullPage: true });
  await owner.goto(base + '/workspace');
  await owner.getByText('Training analysis', { exact: true }).first().click();
  await owner.locator('.workspace-share-btn').click();
  await owner.getByText('Creating link…', { exact: true }).waitFor();
  await audit(owner, 'invite link generation');
  const dialog = owner.getByRole('dialog');
  await dialog.waitFor();
  await audit(owner, 'invite dialog');
  await owner.evaluate(() => Object.defineProperty(navigator.clipboard, 'writeText', { configurable: true, value: async value => { window.copiedLink = value; } }));
  await dialog.getByRole('button', { name: 'Copy view link' }).click();
  await dialog.getByRole('status').filter({ hasText: 'Link copied. You can now share it with others.' }).waitFor();
  assert.equal(await owner.evaluate(() => window.copiedLink), base + '/shared/ENGLISH123');
  await audit(owner, 'copy link success');
  await owner.evaluate(() => Object.defineProperty(navigator.clipboard, 'writeText', { configurable: true, value: async () => { throw new Error('Clipboard unavailable'); } }));
  await dialog.getByRole('button', { name: 'Link copied' }).click();
  await dialog.getByRole('status').filter({ hasText: 'Unable to copy automatically.' }).waitFor();
  await audit(owner, 'copy link failure');
  await owner.screenshot({ path: `${output}/share.png`, fullPage: true });
  await owner.keyboard.press('Escape');
  assert.equal(await dialog.count(), 0);

  const mobile = await createPage(true, true);
  for (const path of ['/', '/signup', '/profile', '/survey', '/survey/create', '/workspace', '/shared/ENGLISH123']) await open(mobile, path, `mobile ${path}`);
  await mobile.goto(base + '/signup');
  await mobile.getByRole('button', { name: 'Select your gender' }).click();
  await audit(mobile, 'mobile gender dropdown');
  await mobile.screenshot({ path: `${output}/signup-mobile.png`, fullPage: true });

  // User-entered text must remain unchanged: the old DOM translator could corrupt it.
  await owner.goto(base + '/survey/create');
  const title = owner.getByPlaceholder('e.g. Product satisfaction survey');
  await title.fill('使用者原始問卷內容');
  await owner.waitForTimeout(200);
  assert.equal(await title.inputValue(), '使用者原始問卷內容');
  assert.deepEqual(errors, [], 'Browser runtime errors');
  console.log(`PASS: ${checked.length} English UI states, desktop/mobile, legacy preference, clipboard success/failure, user content preserved.`);
  console.log(checked.join('\n'));
} finally { await browser.close(); }

