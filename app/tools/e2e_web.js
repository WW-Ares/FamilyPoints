/* 真机端到端巡检：用本地 Chrome 把页面点一遍，抓所有 JS 报错。 */
const { chromium } = require('playwright-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = process.env.FAMILY_BASE || 'http://127.0.0.1:8080';

const errors = [];
const log = [];
function say(s) { log.push(s); console.log(s); }

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 414, height: 900 } });
  const page = await ctx.newPage();

  page.on('pageerror', e => errors.push('[pageerror] ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });
  page.on('requestfailed', r => errors.push('[reqfail] ' + r.url() + ' ' + (r.failure() || {}).errorText));

  // ---------- 1. 首页 ----------
  await page.goto(BASE, { waitUntil: 'networkidle' });
  // v19 起登录换成账号密码，这个脚本里写的 .member-pick 早没了；
  // 页面本身在 v13 也整块重做过，剩下的断言对不上现在的界面。
  // 把话说清楚然后退出 —— 硬跑下去报的一堆红字是脚本过时，不是页面坏了。
  if (await page.locator('#view #lu').count()) {
    say('本脚本已废弃：登录在 v19 改成了账号密码，界面在 v13 整块重做过。');
    say('请跑 tools/e2e_v13.js（主用例）和 tools/e2e_empty.js（空库）。');
    await browser.close();
    return;
  }
  const loginHtml = await page.locator('#view').innerText();
  say('1. 首页渲染: ' + (loginHtml.includes('选一个名字') ? 'OK' : '空白!') + ' | ' + loginHtml.replace(/\n+/g, ' / '));
  const picks = await page.locator('.member-pick button').count();
  say('   可选成员数: ' + picks);

  // ---------- 2. 孩子视角 ----------
  await page.locator('.member-pick button[data-mid="3"]').click();
  await page.waitForTimeout(900);
  const kidTop = await page.locator('#topbar').innerText().catch(() => '');
  say('2. 登录孩子: topbar=' + kidTop.replace(/\n+/g, ' '));

  const tabs = await page.locator('#tabs button').allInnerTexts();
  say('   孩子 tab: ' + JSON.stringify(tabs));

  const kidViews = [];
  for (let i = 0; i < tabs.length; i++) {
    await page.locator('#tabs button').nth(i).click();
    await page.waitForTimeout(700);
    const t = await page.locator('#view').innerText();
    kidViews.push(tabs[i] + '(' + t.length + ')');
    if (t.length < 5) errors.push('[空视图] 孩子-' + tabs[i]);
  }
  say('   各 tab 内容长度: ' + kidViews.join(' '));

  // 孩子侧打开几个 sheet
  await page.locator('#tabs button').nth(0).click();
  await page.waitForTimeout(600);

  const kidSheetBtns = await page.locator('#view button').allInnerTexts();
  say('   今天页按钮: ' + JSON.stringify(kidSheetBtns.map(s => s.slice(0, 12))));

  // ---------- 3. 家长视角 ----------
  await page.evaluate(() => fetch('/api/logout', { method: 'POST' }));
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.locator('.member-pick button[data-mid="1"]').click();
  await page.waitForTimeout(900);

  // 若弹 PIN 输入
  const pinBox = await page.locator('#sheet.on input[type=password]').count();
  if (pinBox) {
    say('3. 家长需要 PIN，尝试输入 1234（若已设）');
    await page.locator('#sheet.on input[type=password]').fill('1234');
    const goBtn = await page.locator('#sheet.on button').allInnerTexts();
    say('   PIN 弹层按钮: ' + JSON.stringify(goBtn));
    await page.locator('#sheet.on button').last().click();
    await page.waitForTimeout(900);
  }

  const pTabs = await page.locator('#tabs button').allInnerTexts();
  say('3. 家长 tab: ' + JSON.stringify(pTabs));

  const pViews = [];
  for (let i = 0; i < pTabs.length; i++) {
    await page.locator('#tabs button').nth(i).click();
    await page.waitForTimeout(800);
    const t = await page.locator('#view').innerText();
    pViews.push(pTabs[i] + '(' + t.length + ')');
    if (t.length < 5) errors.push('[空视图] 家长-' + pTabs[i]);
  }
  say('   各 tab 内容长度: ' + pViews.join(' '));

  // ---------- 4. 家长后台各弹层 ----------
  const parentIdx = pTabs.findIndex(t => t.includes('家'));
  if (parentIdx >= 0) {
    await page.locator('#tabs button').nth(parentIdx).click();
    await page.waitForTimeout(800);
    const btns = await page.locator('#view .qa').all();
    const n = btns.length;
    say('4. 家长页快捷入口数: ' + n);
    for (let i = 0; i < n; i++) {
      const label = (await btns[i].innerText()).replace(/\n+/g, ' ').slice(0, 14);
      if (!label) continue;
      try {
        await btns[i].click();
        await page.waitForTimeout(700);
        const on = await page.locator('#sheet.on').count();
        if (on) {
          const body = await page.locator('#sheet.on .sheet-body').innerText();
          say('   [弹层] ' + label + ' -> ' + body.length + ' 字: ' + body.replace(/\n+/g, ' ').slice(0, 70));
          if (body.length < 3) errors.push('[空弹层] ' + label);
          await page.locator('#sheet').click({ position: { x: 5, y: 5 } });
          await page.waitForTimeout(350);
        } else {
          errors.push('[未弹出] ' + label);
        }
      } catch (e) {
        errors.push('[点击失败] ' + label + ': ' + e.message.split('\n')[0]);
      }
    }
  }

  // ---------- 5. 我的 ----------
  const mineIdx = pTabs.findIndex(t => t.includes('我的'));
  if (mineIdx >= 0) {
    await page.locator('#tabs button').nth(mineIdx).click();
    await page.waitForTimeout(800);
    const t = await page.locator('#view').innerText();
    say('5. 我的页: ' + t.replace(/\n+/g, ' ').slice(0, 200));
  }

  await page.screenshot({ path: require('path').join(__dirname,'..','.tmp','shot-mine.png'), fullPage: true });

  // ---------- 汇总 ----------
  say('');
  say('=== 报错汇总 ===');
  if (!errors.length) say('  0 条报错');
  else errors.forEach(e => say('  ' + e));

  await browser.close();
  process.exit(errors.length ? 1 : 0);
})().catch(e => { console.log('脚本自身失败: ' + e.stack); process.exit(2); });
