/* v1.7 改完以后，把动过的那几个界面各拍一张。
   用法（app 目录，服务起在 8090 演示库）：
     NODE_PATH=<node workspace>/node_modules FAMILY_BASE=http://127.0.0.1:8090 \
       node tools/shots_v17.js
*/
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = process.env.FAMILY_BASE || 'http://127.0.0.1:8090';
const SHOT = path.join(__dirname, '..', '.tmp', 'v17');
fs.mkdirSync(SHOT, { recursive: true });
const PW = { '爸爸': '1234', '妈妈': '1234', '女儿': '1234', '儿子': '1234' };
const KID_NAMES = ['女儿', '儿子'];

async function login(page, who) {
  await page.context().clearCookies();
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const pw = PW[who];
  if (KID_NAMES.indexOf(who) >= 0) {
    const picks = page.locator('#view .lg-pick');
    if (await picks.count() > 1) {
      await picks.filter({ hasText: who }).first().click();
      await page.waitForTimeout(500);
    }
    for (const d of pw.split('')) await page.click('#view .lg-key[data-k="' + d + '"]');
  } else {
    await page.click('#view #lgPar');
    await page.waitForTimeout(400);
    await page.fill('#view #lgU', who);
    await page.fill('#view #lgP', pw);
    await page.click('#view #lgGo');
  }
  await page.waitForTimeout(1400);
}

async function tap(page, sel) {
  await page.locator(sel).first().click();
  await page.waitForTimeout(900);
}

async function shot(page, name) {
  const p = path.join(SHOT, name + '.png');
  await page.screenshot({ path: p, fullPage: true });
  console.log('   ' + p);
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();

  // 孩子端
  await login(page, '女儿');
  await tap(page, '#tabs button:has-text("宝箱")');
  await page.waitForTimeout(700);
  await shot(page, '1-孩子端-宝箱页');
  await tap(page, '#view .card-link[data-go="boxinfo"]');
  await shot(page, '2-孩子端-宝箱详情');
  await tap(page, '#view .appbar-back');
  await tap(page, '#tabs button:has-text("我的")');
  await page.waitForTimeout(700);
  await shot(page, '3-孩子端-我的');

  // 家长端
  await login(page, '爸爸');
  await tap(page, '#tabs button:has-text("发布")');
  await page.waitForTimeout(700);
  await shot(page, '4-家长端-写任务');
  await tap(page, '#view .seg-item[data-pseg="calib"]');
  await shot(page, '5-家长端-写校准');
  await tap(page, '#view .chip[data-ct="custom"]');
  await shot(page, '6-家长端-写校准-自定义');
  await tap(page, '#tabs button:has-text("打分")');
  await page.waitForTimeout(800);
  await tap(page, '#view .seg-item[data-seg="month"]');
  await page.waitForTimeout(900);
  await shot(page, '7-家长端-月度统计');

  await browser.close();
  console.log('截图目录: ' + SHOT);
})().catch(e => { console.error(e); process.exit(1); });
