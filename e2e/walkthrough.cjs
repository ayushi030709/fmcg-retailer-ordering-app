const { chromium, devices } = require('playwright');
// End-to-end walkthrough of the core journeys in a real browser (Playwright + Chromium):
//   retailer sign-in -> catalogue -> cart -> order; AI capture of the brief's sample message ->
//   clarifications -> explicit confirm -> alias learning; order desk approve-from-hold ->
//   line correction -> Tally CSV export. Start the API and web app first, on a freshly seeded DB:
//     cd backend && python -m app.seed --reset && uvicorn app.main:app --port 8000
//     cd frontend && npm run dev
//   then:  npm i -D playwright && npx playwright install chromium   (once)
//          node e2e/walkthrough.cjs e2e/output
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://localhost:5173';
const OUT = process.argv[2] || 'e2e-output';
fs.mkdirSync(OUT, { recursive: true });
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['Pixel 5'] });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  const shot = async (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });

  await page.goto(BASE + '/');
  await page.waitForURL('**/signin');
  await shot('01-signin');
  await page.getByRole('button', { name: /Retailer A/ }).click();
  await page.getByLabel('One-time code').fill('123456');
  await shot('02-otp');
  await page.getByRole('button', { name: 'Verify and sign in' }).click();
  await page.waitForURL(BASE + '/');
  await page.getByText('Glucose biscuit 75 g').waitFor();
  await shot('03-catalogue');

  // Manual order: add biscuit, bump to 10, add detergent 5
  const cards = page.locator('li.card');
  await cards.filter({ hasText: 'Glucose biscuit' }).getByRole('button', { name: 'Add' }).click();
  const bq = cards.filter({ hasText: 'Glucose biscuit' }).getByLabel(/quantity in cases/);
  await bq.fill('10');
  await cards.filter({ hasText: 'Detergent' }).getByRole('button', { name: 'Add' }).click();
  await cards.filter({ hasText: 'Detergent' }).getByLabel(/quantity in cases/).fill('5');
  await page.getByRole('link', { name: /Review order/ }).click();
  await page.getByText('Total payable').waitFor();
  await page.waitForTimeout(600);
  await shot('04-cart');
  await page.getByRole('button', { name: /^Place order/ }).click();
  await page.waitForURL('**/orders/*');
  await page.getByText(/placed/).first().waitFor();
  await shot('05-order-confirmation');

  // AI flow
  await page.goto(BASE + '/ai');
  await page.getByRole('button', { name: 'Use sample message' }).click();
  await shot('06-ai-capture');
  await page.getByRole('button', { name: 'Extract order lines' }).click();
  await page.waitForURL('**/ai/review/*');
  await page.getByText('Check the AI').waitFor();
  await page.waitForTimeout(800);
  await shot('07-ai-review-initial');
  // Resolve: confirm peti = case on lines, remove tea
  const lines = page.locator('ul > li.card');
  const n = await lines.count();
  for (let i = 0; i < n; i++) {
    const li = lines.nth(i);
    const txt = await li.innerText();
    if (txt.includes('chai patti')) { await li.getByRole('button', { name: "Don't order this" }).click(); continue; }
    const yes = li.getByRole('button', { name: /Yes, 1 peti = 1 case/ });
    if (await yes.count()) await yes.click();
    if (txt.includes('biscuit')) {
      const sel = li.locator('select');
      if (!(await sel.inputValue())) await sel.selectOption('SKU-BS-075');
    }
  }
  await page.waitForTimeout(1200);
  await shot('08-ai-review-resolved');
  await page.getByRole('button', { name: /Confirm and place order/ }).click();
  await page.waitForURL('**/orders/*');
  await page.getByText('Order reference').waitFor();
  await shot('09-ai-order-placed');

  // Second extraction: peti now learned
  await page.goto(BASE + '/ai');
  await page.getByRole('button', { name: 'Use sample message' }).click();
  await page.getByRole('button', { name: 'Extract order lines' }).click();
  await page.waitForURL('**/ai/review/*');
  await page.waitForTimeout(800);
  await shot('10-ai-review-learned');

  // Desk
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.waitForURL('**/signin');
  const desk = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const dp = await desk.newPage();
  dp.on('pageerror', e => errors.push(String(e)));
  await dp.goto(BASE + '/signin');
  await dp.getByRole('button', { name: /Order desk/ }).click();
  await dp.getByLabel('One-time code').fill('123456');
  await dp.getByRole('button', { name: 'Verify and sign in' }).click();
  await dp.waitForURL('**/desk');
  await dp.locator('table').waitFor();
  await dp.screenshot({ path: `${OUT}/11-desk-queue.png`, fullPage: true });
  await dp.getByRole('tab', { name: /On hold/ }).click();
  await dp.waitForTimeout(500);
  await dp.locator('table a').first().click();
  await dp.getByText('Credit check').waitFor();
  await dp.screenshot({ path: `${OUT}/12-desk-held-detail.png`, fullPage: true });
  await dp.getByRole('button', { name: 'Approve' }).click();
  await dp.getByLabel('Reason').fill('Retailer paid cash at counter');
  await dp.getByRole('button', { name: /Confirm approve/ }).click();
  await dp.getByText('Approved from hold').waitFor();
  // AI order: correct a line
  await dp.goto(BASE + '/desk');
  await dp.locator('table').waitFor();
  await dp.locator('tbody tr').filter({ has: dp.getByText('AI', { exact: true }) }).first().locator('a').click();
  await dp.getByText('Original AI message').waitFor();
  await dp.getByRole('button', { name: 'Correct line' }).first().click();
  await dp.getByLabel('Paid cases').fill('6');
  await dp.getByPlaceholder(/Reason/).fill('Retailer called to add one');
  await dp.getByRole('button', { name: 'Save correction' }).click();
  await dp.getByText('Line corrected').waitFor();
  await dp.screenshot({ path: `${OUT}/13-desk-ai-corrected.png`, fullPage: true });
  await dp.getByRole('button', { name: 'Approve' }).click();
  await dp.getByRole('button', { name: /Confirm approve/ }).click();
  await dp.getByText(/^Approved$/).first().waitFor();
  await dp.goto(BASE + '/desk/export');
  await dp.getByText(/Export \d+ order/).waitFor();
  await dp.screenshot({ path: `${OUT}/14-desk-export.png`, fullPage: true });
  const [dl] = await Promise.all([dp.waitForEvent('download'), dp.getByRole('button', { name: /Export \d+ order/ }).click()]);
  await dl.saveAs(`${OUT}/export.csv`);
  await dp.getByText(/Exported EXP-/).waitFor();
  await dp.screenshot({ path: `${OUT}/15-desk-export-done.png`, fullPage: true });
  await dp.goto(BASE + '/desk/aliases');
  await dp.waitForTimeout(800);
  await dp.screenshot({ path: `${OUT}/16-desk-aliases.png`, fullPage: true });
  console.log(errors.length ? 'Console errors: ' + JSON.stringify(errors) : 'Walkthrough passed with no console errors. Screenshots + export.csv in ' + OUT);
  await browser.close();
})().catch(e => { console.error('FAILED', e); process.exit(1); });
