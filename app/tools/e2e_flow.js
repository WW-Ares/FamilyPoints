/* 核心交互真机验证 + 截图 */
const { chromium } = require('playwright-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = process.env.FAMILY_BASE || 'http://127.0.0.1:8080';
const OUT = require('path').join(__dirname, '..', '.tmp') + require('path').sep;

const errors = [];
function say(s) { console.log(s); }

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 414, height: 880 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on('pageerror', e => errors.push('[pageerror] ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

  await page.goto(BASE, { waitUntil: 'networkidle' });
  // 同 e2e_web.js：v19 登录改账号密码、v13 界面整块重做，这里已经对不上了。
  if (await page.locator('#view #lu').count()) {
    say('本脚本已废弃：登录在 v19 改成了账号密码，界面在 v13 整块重做过。');
    say('请跑 tools/e2e_v13.js（主用例）和 tools/e2e_empty.js（空库）。');
    await browser.close();
    process.exit(0);
  }
  await page.screenshot({ path: OUT + 's1-login.png' });

  // 孩子视角
  await page.locator('.member-pick button[data-mid="3"]').click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: OUT + 's2-kid-week.png' });
  const kidWeek = await page.locator('#view').innerText();
  say('孩子-这周 全文:\n' + kidWeek);

  await page.locator('#tabs button').nth(1).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + 's3-kid-boxes.png', fullPage: true });

  await page.locator('#tabs button').nth(2).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + 's4-kid-shop.png', fullPage: true });

  await page.locator('#tabs button').nth(3).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + 's5-kid-mine.png', fullPage: true });
  say('孩子券商店可点按钮: ' + JSON.stringify((await page.locator('#view button').allInnerTexts()).map(s => s.replace(/\n/g, ' ').slice(0, 10))));

  // 家长
  await page.evaluate(() => fetch('/api/logout', { method: 'POST' }));
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.locator('.member-pick button[data-mid="1"]').click();
  await page.waitForTimeout(1000);
  const pin = await page.locator('#sheet.on input[type=password]').count();
  if (pin) { await page.locator('#sheet.on input[type=password]').fill('1234'); await page.locator('#sheet.on button').last().click(); await page.waitForTimeout(1000); }

  await page.screenshot({ path: OUT + 's6-parent-today.png', fullPage: true });
  const dims = await page.locator('#view .dim-item').count();
  say('家长-今日页 维度项数: ' + dims + '（应为 7）');
  if (dims !== 7) errors.push('[维度数不对] ' + dims);

  const daycells = await page.locator('#view .daycell').count();
  say('日期条格子数: ' + daycells + '（应为 7）');

  // 打分交互：按当前状态点，断言合计增减各 1
  const sumBefore = Number(await page.locator('#sumNow').innerText());
  const cls0 = await page.locator('#view .dim-item').nth(0).getAttribute('class');
  const wasOff = cls0.indexOf('off') >= 0;
  await page.locator('#view .dim-item').nth(0).click();
  await page.waitForTimeout(200);
  const sumAfter = Number(await page.locator('#sumNow').innerText());
  const expect = wasOff ? sumBefore + 1 : sumBefore - 1;
  say('点第 1 项（原 ' + (wasOff ? '关' : '开') + '）: 合计 ' + sumBefore + ' -> ' + sumAfter + '，期望 ' + expect);
  if (sumAfter !== expect) errors.push('[合计算错] ' + sumBefore + '->' + sumAfter + ' 期望 ' + expect);

  // 再点一次同一项，应该回到原值
  await page.locator('#view .dim-item').nth(0).click();
  await page.waitForTimeout(200);
  const sumBack = Number(await page.locator('#sumNow').innerText());
  say('再点同一项: 回到 ' + sumBack);
  if (sumBack !== sumBefore) errors.push('[来回点没复原] ' + sumBefore + '->' + sumBack);

  // 点掉一项确认提交
  await page.locator('#view .dim-item').nth(4).click();
  await page.waitForTimeout(200);
  const sumCommit = Number(await page.locator('#sumNow').innerText());
  say('准备提交的合计: ' + sumCommit);
  await page.screenshot({ path: OUT + 's7-parent-scored.png', fullPage: true });

  // 提交
  await page.locator('#saveScore').click();
  await page.waitForTimeout(1200);
  const toastTxt = await page.locator('#toast').innerText().catch(() => '');
  say('提交后提示: ' + toastTxt + '（应含 ' + sumCommit + ' 分）');
  if (toastTxt && /失败|错误|Error/.test(toastTxt)) errors.push('[提交失败] ' + toastTxt);
  if (toastTxt && !/记下|扣掉|满分/.test(toastTxt)) errors.push('[提交提示异常] ' + toastTxt);

  // 切到另一个孩子，看打分是否独立
  await page.locator('#tabs button').nth(4).click();
  await page.waitForTimeout(900);
  await page.screenshot({ path: OUT + 's8-parent-dash.png', fullPage: true });
  const dash = await page.locator('#view').innerText();
  say('家长-家 全文:\n' + dash);

  say('');
  say('=== 报错汇总 ===');
  if (!errors.length) say('  0 条报错');
  else errors.forEach(e => say('  ' + e));
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})().catch(e => { console.log('脚本失败: ' + e.stack); process.exit(2); });
