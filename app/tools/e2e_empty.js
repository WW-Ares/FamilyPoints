/* 空库边界巡检：跑 tools/empty_seed.py 造出来的 data/empty 那个库
   （只有账号，一张业务表都没有），专门看每个页面在「什么都没有」时会不会崩。
   起服务：
     python tools/empty_seed.py
     FAMILY_PORT=8099 FAMILY_DATA_DIR=data/empty python server.py
   用法（在 app 目录）：NODE_PATH=<node workspace>/node_modules node tools/e2e_empty.js
   可选：FAMILY_BASE 换目标实例（默认 http://127.0.0.1:8099）
   v19 起这里绝不能再指向 8080 正式库：那个库要屋主自己设密码，巡检碰它就是替人设密码。
*/
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = process.env.FAMILY_BASE || 'http://127.0.0.1:8099';
const SHOT = path.join(__dirname, '..', '.tmp', 'empty-shots');
fs.mkdirSync(SHOT, { recursive: true });

// 和 tools/empty_seed.py 里那份保持一致
const PW = { '爸爸': '1111', '妈妈': '2222', '女儿': '3333', '儿子': '4444' };

const errors = [];
const flat = s => String(s || '').replace(/\s+/g, '');
const bad = s => { errors.push(s); console.log('  !! ' + s); };

/* 渲染异常会被 app.js 兜底成页面上的一句话，既不产生 pageerror，
   页面上也「有内容」，所以「空视图 + 卡加载」两条断言都放它过去。
   v18 的许愿屋就是这样一路绿到用户面前的（done is not defined）。 */
const BROKEN = /没能显示出来|is not defined|Cannot read|Cannot set|TypeError|ReferenceError|undefined is not/;

async function login(page, who) {
  // 换人之前先把上一段会话的 cookie 清掉，否则会直接落回已登录状态
  await page.context().clearCookies();
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const pw = PW[who];
  if (!pw) throw new Error('没有给「' + who + '」配上密码');
  if (await page.locator('#view #lp2').count()) {
    throw new Error('这个库还没设过密码（停在首次设置页）。先跑 tools/empty_seed.py');
  }
  await page.fill('#lu', who);
  await page.fill('#lp', pw);
  await page.click('#lgo');
  await page.waitForTimeout(1100);
  if (await page.locator('#view #lu').count()) bad('[登录] ' + who + ' 没进去，还停在登录页');
}

async function walkTabs(page, tag) {
  const labels = (await page.locator('#tabs button').allInnerTexts()).map(flat);
  console.log('  %s tab: %s', tag, JSON.stringify(labels));
  for (let i = 0; i < labels.length; i++) {
    await page.locator('#tabs button').nth(i).click();
    await page.waitForTimeout(700);
    const t = await page.locator('#view').innerText();
    console.log('    %s(%d)', labels[i], flat(t).length);
    if (flat(t).length < 8) bad('[空视图] ' + tag + '-' + labels[i]);
    if (/加载中/.test(t)) bad('[卡加载] ' + tag + '-' + labels[i]);
    const bk = String(t).match(BROKEN);
    if (bk) bad('[渲染出错] ' + tag + '-' + labels[i] + ': ' + bk[0] + ' | ' + flat(t).slice(0, 100));
    await page.screenshot({ path: path.join(SHOT, tag + '-' + i + '-' + labels[i] + '.png'), fullPage: true });
  }
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
  page.on('pageerror', e => bad('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') bad('console: ' + m.text()); });

  // --- 家长端：五个 tab 全走一遍 ---
  await login(page, '爸爸');
  await walkTabs(page, '家长');

  // 速览卡 -> 详细 -> 记录
  await page.locator('#tabs button').first().click();
  await page.waitForTimeout(600);
  const cards = page.locator('.kcard');
  const cn = await cards.count();
  console.log('    速览卡 %d 张', cn);
  if (!cn) bad('总览页没有速览卡');
  else {
    await cards.first().click();
    await page.waitForTimeout(600);
    console.log('    详细页 %d 字', flat(await page.locator('#view').innerText()).length);
    await page.screenshot({ path: path.join(SHOT, '家长-详细.png'), fullPage: true });
    const rec = page.getByRole('button', { name: /记录/ }).first();
    if (await rec.count()) {
      await rec.click();
      await page.waitForTimeout(700);
      console.log('    记录页 %d 字', flat(await page.locator('#view').innerText()).length);
      await page.screenshot({ path: path.join(SHOT, '家长-记录.png'), fullPage: true });
    } else bad('详细页没有「记录」入口');
  }

  // --- 孩子端：四个 tab 全走一遍 ---
  await login(page, '女儿');
  await walkTabs(page, '孩子');

  await browser.close();
  console.log('\n=== 空库报错汇总 ===');
  console.log(errors.length ? errors.map(e => '  !! ' + e).join('\n') : '  0 条报错');
  console.log('截图目录: ' + SHOT);
})();
