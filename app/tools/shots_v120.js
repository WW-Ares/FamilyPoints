/* 这一轮的两处改动，各拍一张实机图（2026-10-11）。
   用法（app 目录，服务起在 8090 演示库）：
     NODE_PATH=<node workspace>/node_modules FAMILY_BASE=http://127.0.0.1:8090 \
       node tools/shots_v120.js
   演示库里要先有一条待核实的求助（tools/demo_seed.py 之后手工加一条，
   或者让种子脚本自己种）。 */
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = process.env.FAMILY_BASE || 'http://127.0.0.1:8090';
const SHOT = path.join(__dirname, '..', '.tmp', 'v120');
fs.mkdirSync(SHOT, { recursive: true });

async function shot(page, name) {
  const p = path.join(SHOT, name + '.png');
  await page.screenshot({ path: p, fullPage: true });
  console.log('   ' + p);
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();

  // 家长端：审核页那张「说卡住了」的卡，现在有次按钮了
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.click('#view #lgPar');
  await page.waitForTimeout(400);
  await page.fill('#view #lgU', '爸爸');
  await page.fill('#view #lgP', '1234');
  await page.click('#view #lgGo');
  await page.waitForTimeout(1600);

  await page.locator('#tabs button:has-text("审核")').first().click();
  await page.waitForTimeout(1400);
  // 滚到「他找你说的事」那一栏（求助卡在那儿）
  await page.locator('#view').evaluate(el => {
    const band = el.querySelector('.sec-h, .sec-title, [class*="sec"]');
    const all = Array.from(el.querySelectorAll('*'));
    const t = all.filter(n => n.children.length === 0 && /说的事/.test(n.textContent || ''))[0];
    if (t) t.scrollIntoView({ block: 'start' });
    else el.scrollTop = el.scrollHeight * 0.55;
  });
  await page.waitForTimeout(800);
  await shot(page, '1-家长端-审核页-求助卡带次按钮');

  // 点那颗次按钮，看拒绝对话框
  const no = page.locator('#view button[data-td="help-no"]').first();
  if (await no.count()) {
    await no.click();
    await page.waitForTimeout(900);
    await shot(page, '2-家长端-求助拒绝对话框');
  } else {
    console.log('   [skip] 演示库里没有待核实的求助，拍不到次按钮');
  }

  // 设置页「奖励与道具」组（券与道具那两项在这一组里）。
  // 另开一页：拒绝对话框还开着的时候跳 hash，那层弹层会跟着不落。
  // 同一 context 里 cookie 是共享的，这一页多半已经是登录态 —— 认登录页
  // 那颗「家长登录」在不在，别认别的（#lgGo 在两种屏上都可能有）。
  const p2 = await ctx.newPage();
  await p2.goto(BASE + '/#settings/' + encodeURIComponent('奖励与道具'), { waitUntil: 'networkidle' });
  await p2.waitForTimeout(1600);
  if (await p2.locator('#view #lgPar').count()) {
    await p2.click('#view #lgPar');
    await p2.waitForTimeout(400);
    await p2.fill('#view #lgU', '爸爸');
    await p2.fill('#view #lgP', '1234');
    await p2.click('#view #lgGo');
    await p2.waitForTimeout(1600);
  }
  await p2.waitForTimeout(800);
  // hash 恢复组名只在刷新那一步生效，直接进这一页是安静落在一级 —— 点开它。
  const grow = p2.locator('#view [data-setgrp="奖励与道具"]').first();
  if (await grow.count()) {
    await grow.click();
    await p2.waitForTimeout(1200);
  }
  // 滚到那两项硬停止（页面很长，不滚看不到）
  await p2.locator('#view').evaluate(el => { el.scrollTop = el.scrollHeight * 0.30; });
  await p2.waitForTimeout(600);
  await shot(p2, '3-家长端-设置-硬停止两项改口径');

  // 孩子端「券和卡」说明页那条收工文案。另开第三页：第二页里那张拒绝
  // 弹层还开着时清 cookie 重进，弹层会跟着不落（第一版就踩了这个）。
  // cookie 是这个 context 共享的，先把家长那套会话清掉再走孩子登录。
  await ctx.clearCookies();
  const p3 = await ctx.newPage();
  await p3.goto(BASE + '/#guidecard', { waitUntil: 'networkidle' });
  await p3.waitForTimeout(1500);
  if (await p3.locator('#view .lg-pick').count()) {
    await p3.locator('#view .lg-pick').filter({ hasText: '女儿' }).first().click();
    await p3.waitForTimeout(500);
    for (const d of '1234') await p3.click('#view .lg-key[data-k="' + d + '"]');
    await p3.waitForTimeout(1600);
  }
  await p3.goto(BASE + '/#guidecard', { waitUntil: 'networkidle' });
  await p3.waitForTimeout(1600);
  // 登录后可能先弹一层「这次发的券先还了欠账」之类的通知 —— 先收掉再拍。
  // 这层是 `#kNoteOk`（child.js kDebtNotices），可能不止一层，最多收三层。
  for (let i = 0; i < 3; i++) {
    const ok = p3.locator('#kNoteOk');
    if (!(await ok.count())) break;
    await ok.first().evaluate(b => b.click());
    await p3.waitForTimeout(700);
  }
  await p3.locator('.content, #view').first().evaluate(el => {
    const all = Array.from(el.querySelectorAll('*'));
    const t = all.filter(n => n.children.length === 0 && /前要停|前停/.test(n.textContent || ''))[0];
    if (t) t.scrollIntoView({ block: 'center' });
    else el.scrollTop = el.scrollHeight;
  });
  await p3.waitForTimeout(700);
  await p3.screenshot({ path: path.join(SHOT, '4-孩子端-券和卡-硬停止改口径.png') });
  console.log('   ' + path.join(SHOT, '4-孩子端-券和卡-硬停止改口径.png'));

  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });