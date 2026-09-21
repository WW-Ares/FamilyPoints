/* v13 真机巡检：家长端 / 孩子端两套界面各走一遍，抓所有 JS 报错。
   用法（在 app 目录）：
     NODE_PATH=<node workspace>/node_modules node tools/e2e_v13.js
   前置：服务已在 FAMILY_BASE（默认 http://127.0.0.1:8080）跑起来。
*/
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = process.env.FAMILY_BASE || 'http://127.0.0.1:8080';
const SHOT = path.join(__dirname, '..', '.tmp', 'v29');
fs.mkdirSync(SHOT, { recursive: true });

const errors = [];
function say(s) { console.log(s); }
function bad(s) { errors.push(s); console.log('  !! ' + s); }
const flat = s => String(s || '').replace(/\s+/g, '');

/* 渲染异常会被 app.js 兜底成页面上的一句话（原来只是一句裸的 e.message），
   既不产生 pageerror，也不产生 console.error，页面上还「有内容」，
   所以「空视图 + 卡加载」两条断言全放它过去。
   v18 的许愿屋就是这样一路绿到用户面前的（done is not defined）。
   凡是页面上出现这些字样，一律判错。 */
const BROKEN = /没能显示出来|is not defined|Cannot read|Cannot set|TypeError|ReferenceError|undefined is not/;
function brokenText(t) { const m = String(t || '').match(BROKEN); return m ? m[0] : ''; }

/* 演示库的账号密码。和 tools/demo_seed.py 里那份必须一致，改一边就得改两边。
   v36 起孩子不算「账号」了：登录是「点自己那张头像 + 按 4 位数字」。
   家长那条没变，还是账号 + 密码，从右下角那行「家长登录」进。
   四个人统一用 1234，是 WW 先生点名要的 —— 装完先保证一家人都进得去，
   之后由他自己在系统里改。所以「进来的是不是本人」不能靠密码不一样来验，
   下面的 login() 每次都会拿 bootstrap 的 me.name 对一遍。 */
const PW = { '爸爸': '1234', '妈妈': '1234', '女儿': '1234', '儿子': '1234' };
const KID_NAMES = ['女儿', '儿子'];

async function login(page, who) {
  // 换人之前先把上一段会话的 cookie 清掉，否则会直接落回已登录状态
  await page.context().clearCookies();
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const pw = PW[who];
  if (!pw) throw new Error('没有给「' + who + '」配上密码');
  // 正式库升级到 v19 后第一次打开会停在「给管理员设密码」，那是屋主自己的事，
  // 巡检不能代劳 —— 代劳等于替人设密码，还会把正式库真的改掉。
  if (await page.locator('#view #lgP2').count()) {
    throw new Error('这个库还没设过密码（停在首次设置页）。巡检要指向演示库，不要指向正式库');
  }
  if (KID_NAMES.indexOf(who) >= 0) {
    // ① 选头像：一进来就该是一面头像墙，密码框在这屏不该出现
    const picks = page.locator('#view .lg-pick');
    if (await picks.count() > 1) {
      await picks.filter({ hasText: who }).first().click();
      await page.waitForTimeout(500);
    }
    // ② 输密码：按九宫格，输满 4 位自己提交，没有确认键
    for (const d of pw.split('')) {
      await page.click('#view .lg-key[data-k="' + d + '"]');
    }
  } else {
    // 家长：右下角那行下划线文字才是入口
    await page.click('#view #lgPar');
    await page.waitForTimeout(400);
    await page.fill('#view #lgU', who);
    await page.fill('#view #lgP', pw);
    await page.click('#view #lgGo');
  }
  await page.waitForTimeout(1200);
  if (await page.locator('#view .lg-inner').count()) {
    bad('[登录] ' + who + ' 没进去，还停在登录页');
    return who;
  }
  // 进来的是不是本人。少了这一条，成员号接错线也查不出来 ——
  // 页面照样有内容，只是换成了另一个人的。
  const me = await page.evaluate(async () => {
    const r = await fetch('/api/bootstrap', { credentials: 'same-origin' });
    return (await r.json()).me;
  });
  if (!me || me.name !== who) {
    bad('[登录] 进来的是「' + ((me && me.name) || '谁都不是') + '」，不是「' + who + '」');
  }
  return who;
}

async function tabLabels(page) {
  return (await page.locator('#tabs button').allInnerTexts()).map(flat);
}

/* 按名字点 tab。早先这里写的是 nth(3) / nth(4)，加一格导航就全错位，
   表现是一堆「某某页里没有某某」的假报错。名字比序号稳。 */
async function tabTo(page, name) {
  const btns = page.locator('#tabs button');
  const n = await btns.count();
  for (let i = 0; i < n; i++) {
    if (flat(await btns.nth(i).innerText()).indexOf(name) >= 0) {
      await btns.nth(i).click();
      return true;
    }
  }
  bad('[导航] 找不到 tab「' + name + '」');
  return false;
}

/* 二级页没有底栏格，靠页面上那个真实入口点进去（总览 → 查看全部、
   我的 → 心愿与许愿池这种）。点得动才说明接线是通的 —— 直接改
   location.hash 跳过去，会把「入口压根没绑上」这半边漏掉。 */
async function clickSel(page, sel, tag) {
  const el = page.locator(sel).first();
  if (!(await el.count())) {
    bad('[导航] 找不到入口 ' + sel + (tag ? '（' + tag + '）' : ''));
    return false;
  }
  await el.click();
  await page.waitForTimeout(1100);
  return true;
}

async function walkTabs(page, tag) {
  const tabs = await tabLabels(page);
  const out = [];
  for (let i = 0; i < tabs.length; i++) {
    await page.locator('#tabs button').nth(i).click();
    await page.waitForTimeout(700);
    const t = await page.locator('#view').innerText();
    out.push(tabs[i] + '(' + flat(t).length + ')');
    if (flat(t).length < 8) bad('[空视图] ' + tag + '-' + tabs[i] + ' 内容过短');
    if (/加载中/.test(t)) bad('[卡加载] ' + tag + '-' + tabs[i]);
    const bk = brokenText(t);
    if (bk) bad('[渲染出错] ' + tag + '-' + tabs[i] + ': ' + bk + ' | ' + flat(t).slice(0, 100));
    await page.screenshot({ path: path.join(SHOT, tag + '-' + i + '-' + tabs[i] + '.png'), fullPage: true });
  }
  return out;
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 414, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', e => bad('[pageerror] ' + e.message));
  /* 「故意输错一次密码」那一会儿服务器必回 400 —— 那是预期结果，不是页面坏了。
     靠 LG_EXPECT_400 这一个开关临时放行，别为了巡检不报错就不敢试错密码。
     整个脚本里只有那几秒钟是 true。 */
  let LG_EXPECT_400 = false;
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (LG_EXPECT_400 && /status of 400/.test(t)) return;
    bad('[console] ' + t);
  });
  page.on('requestfailed', r => bad('[reqfail] ' + r.url() + ' ' + ((r.failure() || {}).errorText || '')));

  // ---------- 登录页 · 三个状态（v36）----------
  /* 冷启动只落一屏：一面头像墙 + 一句「你是谁呀？」，点谁的头像才切到输密码。
     交付包 §2 那三条硬要求在这里各验一条 —— 状态进 URL（刷新不丢）、
     返回键能退、首屏不出现密码框。 */
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const loginText = await page.locator('#view').innerText();
  const okWall = /你是谁呀/.test(loginText) && /家长登录/.test(loginText);
  say('1. 登录页（选头像）: ' + (okWall ? 'OK' : '异常') + ' | ' + flat(loginText));
  if (!okWall) bad('[v36] 登录页不是「选头像」那一态');
  if (await page.locator('#view input').count()) bad('[v36] 选头像那屏不该出现密码框');
  if ((await page.locator('#view .lg-pick').count()) < 2) {
    bad('[v36] 头像墙上没摆出两个孩子的头像');
  }
  if (!/NAS/.test(loginText)) bad('[v36] 登录页脚注没了（数据只存在自己家里的 NAS 上）');
  if ((await page.evaluate(() => location.hash)) !== '#login') {
    bad('[v36] 冷启动没把状态写进 URL');
  }
  await page.screenshot({ path: path.join(SHOT, '0-login-wall.png'), fullPage: true });

  // ③ 家长登录：是右下角那行下划线文字，不是跟孩子并排的一张卡
  await page.click('#view #lgPar');
  await page.waitForTimeout(450);
  const parText = flat(await page.locator('#view').innerText());
  say('1b. 家长登录: ' + (parText.indexOf('家长端') >= 0 ? 'OK' : '异常') +
    ' | ' + parText.slice(0, 70));
  if (parText.indexOf('家长端') < 0) bad('[v36] 家长登录页没有品牌标题');
  if (parText.indexOf('我是孩子') < 0) bad('[v36] 家长登录页没有回孩子端的入口');
  if (parText.indexOf('忘记密码') < 0) bad('[v36] 家长登录页少了「忘记密码？」');
  if (!(await page.locator('#view #lgRem').isChecked())) bad('[v36] 「记住我」默认该是勾上的');
  // 眼睛：点一下把密码变明文，再点一下变回密文
  await page.fill('#view #lgP', 'abc');
  await page.click('#view #lgEye');
  const eye1 = await page.getAttribute('#view #lgP', 'type');
  if (eye1 !== 'text') bad('[v36] 眼睛没能把密码变明文（type=' + eye1 + '）');
  await page.click('#view #lgEye');
  const eye2 = await page.getAttribute('#view #lgP', 'type');
  if (eye2 !== 'password') bad('[v36] 眼睛再点一下没变回密文');
  await page.screenshot({ path: path.join(SHOT, '0b-login-parent.png'), fullPage: true });

  // 返回键：状态在 URL 里，所以退得回去，而不是退出页面
  await page.evaluate(() => history.back());
  await page.waitForTimeout(650);
  const backText = await page.locator('#view').innerText();
  say('1c. 返回键: ' + (backText.indexOf('你是谁呀') >= 0 ? '退回选头像 OK' : '没退回去'));
  if (backText.indexOf('你是谁呀') < 0) bad('[v36] 从家长登录返回，没退回选头像那一屏');

  // ② 输密码：点自己的头像，这一屏顶上要写清在给谁输
  await page.locator('#view .lg-pick').filter({ hasText: '女儿' }).first().click();
  await page.waitForTimeout(550);
  const pinText = flat(await page.locator('#view').innerText());
  say('1d. 输密码: ' + (pinText.indexOf('输密码吧') >= 0 ? 'OK' : '异常') +
    ' | ' + pinText.slice(0, 70));
  if (pinText.indexOf('女儿，输密码吧') < 0) bad('[v36] 输密码屏没写清在给谁输');
  if (pinText.indexOf('忘了密码？找爸妈帮忙') < 0) bad('[v36] 输密码屏少了那句「找爸妈帮忙」');
  const pinHash = await page.evaluate(() => location.hash);
  if (pinHash.indexOf('#login/') !== 0) {
    bad('[v36] 输密码这一态没进 URL（' + pinHash + '），刷新一下就丢了');
  }
  const nCells = await page.locator('#view .lg-cell').count();
  const nKeys = await page.locator('#view .lg-key:not(.gap)').count();
  say('   密码格 ' + nCells + ' 个 · 数字键 ' + nKeys + ' 个');
  if (nCells !== 4) bad('[v36] 密码格不是 4 个');
  if (nKeys !== 11) bad('[v36] 键盘不是 1-9 + 0 + 退格（' + nKeys + ' 个）');
  if (await page.locator('#view input').count()) bad('[v36] 输密码那屏不该有文本输入框');
  const lit = await page.locator('#view .lg-pick.on').count();
  if (lit !== 1) bad('[v36] 输密码屏高亮的头像不是恰好 1 个（' + lit + ' 个）');
  await page.screenshot({ path: path.join(SHOT, '0c-login-pin.png'), fullPage: true });

  // 退格
  await page.click('#view .lg-key[data-k="7"]');
  await page.waitForTimeout(200);
  if ((await page.locator('#view .lg-cell i').count()) !== 1) {
    bad('[v36] 按了一个数字，格子里没画出点');
  }
  await page.click('#view .lg-key[data-k="del"]');
  await page.waitForTimeout(200);
  if (await page.locator('#view .lg-cell i').count()) bad('[v36] 退格键没删掉');

  // 输错：清格 + 抖一下，不锁次数（家里用的东西，锁了添乱）
  LG_EXPECT_400 = true;
  for (const d of '9999') await page.click('#view .lg-key[data-k="' + d + '"]');
  await page.waitForTimeout(1300);
  LG_EXPECT_400 = false;
  if (await page.locator('#view .lg-cell i').count()) bad('[v36] 密码输错没清格');
  if (!(await page.locator('#view .lg-inner').count())) {
    bad('[v36] 密码输错不该把人踢出登录页');
  }
  say('1e. 输错一次: 已清格，人还留在输密码屏');

  // 返回键退回选头像
  await page.evaluate(() => history.back());
  await page.waitForTimeout(650);
  if ((await page.locator('#view').innerText()).indexOf('你是谁呀') < 0) {
    bad('[v36] 从输密码屏返回，没退回选头像那一屏');
  }

  // ---------- 孩子端 ----------
  /* v31：孩子端换了整套皮（「糖果冒险」）。底栏从 7 格收成 5 格，
     任务大厅 / 券商店 / 成长报告 / 心愿屋 / 图鉴 / 我的记录 / 家庭
     变成压在底栏之上的二级页，靠 hash 进、靠返回键退。

     这一节跟着重写，但守的东西一条没少，只是改成按**文案和 data 属性**查，
     不再按 DOM 的形状查（`.sec-h h2` / `.boxtrack` 这类东西一换皮就没了）。 */
  const kid = await login(page, '女儿');
  say('');
  say('2. 孩子端已登录: ' + kid);

  // 二级页没有自己的底栏格，走 hash 进去；底栏要亮点着它所属的那一格
  async function kidGo(v) {
    const cur = await page.evaluate(() => String(location.hash || '').replace(/^#/, ''));
    if (cur !== v) await page.evaluate(x => { location.hash = x; }, v);
    await page.waitForTimeout(950);
  }
  async function kidText() { return flat(await page.locator('#view').innerText()); }

  const bodyCls = String(await page.getAttribute('body', 'class') || '');
  say('   body class: ' + bodyCls);
  if (bodyCls.indexOf('kid') < 0) bad('[v31] 孩子端没挂上 body.kid，糖果那套样式不会生效');

  const kidTabs = await tabLabels(page);
  say('   tab: ' + JSON.stringify(kidTabs));
  if (kidTabs.length !== 5) bad('[v31] 孩子端底栏不是 5 格，是 ' + kidTabs.length);
  for (const want of ['首页', '任务', '宝箱', '券包', '我的']) {
    if (kidTabs.join('|').indexOf(want) < 0) bad('[导航缺项] 孩子端少了「' + want + '」');
  }
  for (const forbidden of ['总览', '审核', '设置', '打分']) {
    if (kidTabs.join('|').indexOf(forbidden) >= 0) bad('[越权导航] 孩子端出现了「' + forbidden + '」');
  }
  const kidBtnText = (await page.locator('#view button').allInnerTexts()).join('|');
  if (/结算|发星星|校准|发任务|批准|同意/.test(kidBtnText)) {
    bad('[越权按钮] 孩子端出现家长操作: ' + kidBtnText);
  }

  say('');
  say('3. 孩子端五个底栏页:');
  const kidView = {};
  for (const v of ['home', 'task', 'chest', 'coupon', 'mine']) {
    await kidGo(v);
    const rawTxt = await page.locator('#view').innerText();
    kidView[v] = flat(rawTxt);
    say('   ' + v.padEnd(6) + ' ' + String(kidView[v].length).padStart(4) + ' 字  | ' +
      kidView[v].slice(0, 44));
    if (kidView[v].length < 60) bad('[空视图] 孩子端「' + v + '」内容过短（' + kidView[v].length + ' 字）');
    if (/加载中/.test(rawTxt)) bad('[卡加载] 孩子端「' + v + '」');
    const bk = brokenText(rawTxt);
    if (bk) bad('[渲染出错] 孩子端「' + v + '」: ' + bk + ' | ' + kidView[v].slice(0, 90));
    await page.screenshot({ path: path.join(SHOT, 'kid-' + v + '.png'), fullPage: true });
  }

  // 首页：今天几分、多少星尘、这一周的七分、要做的事
  await kidGo('home');
  const kHome = kidView.home;
  for (const want of ['这一周的七分', '要做的事', '星尘']) {
    if (kHome.indexOf(want) < 0) bad('[v39] 首页缺少「' + want + '」');
  }
  /* v39：首页那张「本周能量」卡撤了 —— 宝箱页头一行就在报同一个数。
     留着的话孩子会在两处看到同一根进度条各说各话。 */
  if (kHome.indexOf('本周能量') >= 0) bad('[v39] 首页还留着「本周能量」卡');
  if (!/今天能量\d+\/\d+/.test(kHome)) bad('[v39] 首页副标没写成「今天能量 X/Y · 第 N 天」');
  const k7rows = await page.locator('#view .k7-row:not(.k7-cols)').count();
  const k7cells = await page.locator('#view .k7-c').count();
  say('   七分矩阵: ' + k7rows + ' 行 × 7 列 = ' + k7cells + ' 格');
  if (k7rows !== 7) bad('[v39] 七分矩阵不是 7 行，是 ' + k7rows);
  if (k7cells !== 49) bad('[v39] 七分矩阵不是 49 格，是 ' + k7cells);
  // 任务三态点：待做 → 在做 → 交上去 → 已完成
  const dots = await page.locator('#view .dots').count();
  const dotsOn = await page.locator('#view .dots i.is-on, #view .dots i.is-done').count();
  say('   任务三态点: ' + dots + ' 处，其中亮着 ' + dotsOn + ' 个');
  if (!dots) bad('[v31] 首页一个任务三态点都没有');
  if (!dotsOn) bad('[v31] 三态点全是空的（演示库里有交了等确认的任务）');
  // 「正在玩」：钟表倒计时 + 进度条 + 秒数真的在走
  const runBox = page.locator('#view [data-tkend]');
  const runCount = await runBox.count();
  say('   正在玩: ' + runCount + ' 块');
  if (!runCount) {
    bad('[v31] 首页没有「正在玩」那一块（演示库里留着一条正在玩的）');
  } else {
    const runTxt = flat(await runBox.first().innerText());
    if (runTxt.indexOf('正在玩') < 0) bad('[v31] 正在玩那块没写「正在玩」：' + runTxt.slice(0, 40));
    if (!/\d{2}:\d{2}|时间到了/.test(runTxt)) {
      bad('[v31] 正在玩那块不是钟表倒计时：' + runTxt.slice(0, 40));
    }
    const barW = await page.locator('#view [data-tkend] [data-tkbar]').first()
      .evaluate(el => el.style.width).catch(() => '');
    if (!barW || barW === '0%') bad('[v31] 正在玩的进度条没画出来：' + barW);
    const t1 = flat(await page.locator('#view [data-tkend] [data-tkleft]').first().innerText());
    await page.waitForTimeout(1400);
    const t2 = flat(await page.locator('#view [data-tkend] [data-tkleft]').first().innerText());
    say('   倒计时: ' + t1 + ' -> ' + t2);
    if (t1 === t2) bad('[v31] 倒计时没在走，还是 ' + t1);
  }
  await page.screenshot({ path: path.join(SHOT, 'kid-home-run.png'), fullPage: true });

  // 任务页 + 任务大厅（分段器第二段）
  await kidGo('task');
  const taskTxt = kidView.task;
  for (const want of ['我的任务', '任务大厅', '在做', '等爸爸妈妈确认']) {
    if (taskTxt.indexOf(want) < 0) bad('[v31] 任务页缺少「' + want + '」');
  }
  const tDone = await page.locator('#view button[data-tdone]').count();
  const tGive = await page.locator('#view button[data-tgive]').count();
  say('   手上的任务按钮: 做完了 ' + tDone + '，我不做了 ' + tGive);
  if (tGive > tDone) bad('[v31] 「我不做了」比「做完了」还多，按钮配错了');
  // v33：家长直接派下来的活是 pending（待做），大厅里领的才是 claimed（在做）。
  // 孩子端两处列表原先只认 claimed，派下来的那条被整个藏掉，而首页和大厅的
  // 计数又把它数进去 —— 表现是「你在做 1 件」，点进去空空如也。
  if (taskTxt.indexOf('给弟弟读一本绘本') < 0) {
    bad('[v33] 家长直接派下来的任务（待做）在孩子端看不见');
  }
  if (taskTxt.indexOf('待做') < 0) bad('[v33] 待做的任务没标出「待做」');
  if (tDone < 1) bad('[v33] 待做的任务没有「交上去」按钮，孩子交不了（退回之后也回不来）');
  await page.locator('#view button[data-go="hall"]').first().click();
  await page.waitForTimeout(950);
  const hall = await kidText();
  say('   任务大厅: ' + hall.slice(0, 46));
  if (hall.indexOf('大厅里现在有') < 0) bad('[v31] 任务大厅没写「现在有几件能接」');
  // 大厅头上那个「你在做 N 件」和「我的任务」里那份列表必须同源，
  // 报的数和列出来的条数对不上，孩子会以为任务丢了。
  const mDoing = hall.match(/你在做(\d+)件/);
  if (!mDoing) bad('[v33] 任务大厅没写「你在做几件」');
  else if (+mDoing[1] !== tDone) {
    bad('[v33] 大厅说「你在做 ' + mDoing[1] + ' 件」，「我的任务」里却是 ' + tDone + ' 条');
  }
  const kidClaim = await page.locator('#view button[data-tclaim]').count();
  say('   大厅「我要做」按钮: ' + kidClaim + ' 个');
  if (!kidClaim) bad('[v31] 任务大厅一件都接不了（演示库里挂着能接的任务）');
  await page.screenshot({ path: path.join(SHOT, 'kid-hall.png'), fullPage: true });

  // 宝箱页：七档一格一格、七个图标各不相同、概率只在这页
  await kidGo('chest');
  const chest = kidView.chest;
  for (const want of ['七档宝箱', '星尘直接买', '本周能量']) {
    if (chest.indexOf(want) < 0) bad('[v31] 宝箱页缺少「' + want + '」');
  }
  const boxCols = await page.locator('#view .btcol').count();
  say('   七档: ' + boxCols + ' 列');
  if (boxCols !== 7) bad('[v39] 七档不是 7 列，是 ' + boxCols);
  const hrefs = await page.evaluate(() => Array.from(
    document.querySelectorAll('#view .btcol svg use')).map(u => u.getAttribute('href')));
  say('   七档图标: ' + hrefs.join(' '));
  if (hrefs.length !== 7) bad('[v39] 七档图标不是 7 个，是 ' + hrefs.length);
  if (new Set(hrefs).size !== hrefs.length) bad('[v39] 七档宝箱的图标有重复：' + hrefs.join(' '));
  for (const nm of ['木箱', '铜箱', '银箱', '金箱', '钻石箱', '王者箱', '完美箱']) {
    if (chest.indexOf(nm) < 0) bad('[v31] 宝箱页没出现「' + nm + '」');
  }
  if (!/10%/.test(chest) || !/70%/.test(chest)) {
    bad('[v31] 宝箱页没写随机件概率（概率只该写在这一页）');
  }
  /* v39：七档从「一条横向阶梯 ＋ 卡下七行明细」并成七列一列一档，
     内容行进到列里，概率从每一列里收走、只在卡尾那一句出现一次。
     列里再冒出百分比的话，孩子读到的是七个数字而不是一个结论。 */
  const colTxt = await page.evaluate(() => Array.from(
    document.querySelectorAll('#view .btcol')).map(c => c.innerText.replace(/\s+/g, ' ')));
  say('   七档内容: ' + colTxt.join(' | '));
  if (colTxt.filter(t => /券/.test(t)).length !== 7) bad('[v39] 七档里有哪一列没写券数');
  if (colTxt.some(t => /%/.test(t))) bad('[v39] 七列的列里不该写概率');
  if (chest.indexOf('随机掉稀有道具') < 0) bad('[v39] 宝箱页没写随机件概率那一句');
  if (chest.indexOf('箱子里有什么，点开那一刻才抽') >= 0) {
    bad('[v39] 宝箱页还留着上一条卡尾文案');
  }
  const buyBoxes = await page.locator('#view button[data-box]').count();
  say('   星尘直接买: ' + buyBoxes + ' 档');
  if (buyBoxes !== 3) bad('[v31] 星尘直接买不是三档，是 ' + buyBoxes);
  if (await page.locator('#view button[data-buy]').count()) bad('[v31] 宝箱栏还在卖箱子');

  /* v38：结算只发一只箱子，箱子里有什么点开那一刻才抽。
     演示库给女儿留了一只没点开的箱，这里把它走完整条路：
     提醒卡 → 四拍动画 → 结果屏 → 提醒卡消失。 */
  const alert = page.locator('#view .chest-pod');
  if (!(await alert.count())) {
    bad('[v38] 宝箱页没有「有箱子可以开」的提醒卡（演示库留了一只待开箱）');
  } else {
    say('   待开箱提醒: ' + flat(await alert.innerText()).slice(0, 50));
    await alert.click();
    await page.waitForTimeout(2700);          // 四拍动画走完，结果铺出来
    const openTxt = flat(await page.locator('#sheetBody').innerText());
    say('   开箱结果: ' + openTxt.slice(0, 80));
    if (openTxt.indexOf('开出来了') < 0) {
      bad('[v38] 点开箱子没走到结果屏：' + openTxt.slice(0, 50));
    }
    if (!/娱乐券|星尘|卡/.test(openTxt)) bad('[v38] 开箱结果里什么都没写');
    const okBtn = page.locator('#sheetBody #kOk');
    if (await okBtn.count()) await okBtn.click();
    else await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(1000);
    if (await page.locator('#view .chest-pod').count()) {
      bad('[v38] 箱子已经开过了，提醒卡还挂着');
    }
  }
  await page.screenshot({ path: path.join(SHOT, 'kid-chest.png'), fullPage: true });

  // 券包页：六种券都摆着（×0 的置灰），核销入口和「为什么现在不能用」都要有
  await kidGo('coupon');
  const coupon = kidView.coupon;
  // v38：「我手上的卡」整段从图鉴搬到了券包，跟券挨着 ——
  // 「我手上现在有什么能用的」应该在这一页一眼看全。
  for (const want of ['今天还能玩多少', '我手上的券', '我手上的卡']) {
    if (coupon.indexOf(want) < 0) bad('[v31] 券包页缺少「' + want + '」');
  }
  if (!/去用|现在不行/.test(coupon)) bad('[券核销] 券包里没有核销按钮');
  if (!/要休息\s*\d+\s*分钟/.test(coupon)) bad('[券核销] 没画出「一轮结束要休息多久」');
  if (coupon.indexOf('收工') < 0) bad('[券核销] 没画出「几点收工」');
  for (const tp of ['娱乐券', '陪伴券', '选择券', '豁免券', '独处券', '好友券']) {
    if (coupon.indexOf(tp) < 0) bad('[v31] 券包里没有「' + tp + '」（六种都该摆着）');
  }
  await page.screenshot({ path: path.join(SHOT, 'kid-coupon.png'), fullPage: true });

  /* 「要几张」那排是数量选择的唯一入口。演示库里女儿手上有三十来张娱乐券，
     一轮白天还剩三张，所以这里至少得给出两个可选的数 —— 只能选 1 张就说明
     库存没接上来的线（以前这里把库存写死成 0，于是永远只有一张）。
     过了收工时间「去用」是灰的，那时候不点，也就不验：那一屏是合理的。
     它能不能真的提交出去由人判断，巡检不点，点了就把演示库那条数据花掉。 */
  const useBtn = page.locator('#view button[data-tk="ticket_fun"]');
  if (await useBtn.count() && !(await useBtn.first().isDisabled())) {
    const held = +(await useBtn.first().getAttribute('data-tkq') || 0);
    await useBtn.first().click();
    await page.waitForTimeout(450);
    const chips = page.locator('#sheetBody .chip[data-q]');
    const n = await chips.count();
    const txt = flat(await page.locator('#sheetBody').innerText());
    say('   娱乐券数量可选 ' + n + ' 档（手上 ' + held + ' 张）');
    if (n < 1 || n > Math.max(1, held)) {
      bad('[v36] 「要几张」给的档数是 ' + n + '，手上却只有 ' + held + ' 张');
    }
    if (txt.indexOf('要几张') < 0) bad('[v36] 用券弹层里没有「要几张」那一行');
    await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(350);
  } else {
    say('   娱乐券「去用」此刻是灰的（多半过了收工点），跳过数量选择这一步');
  }

  // 券商店（分段器第二段）：明牌，不卖卡，不写概率
  await page.locator('#view button[data-go="shop"]').first().click();
  await page.waitForTimeout(950);
  const shop = await kidText();
  say('   券商店: ' + shop.slice(0, 46));
  if (!/1星尘=0\.5元/.test(shop)) bad('[v31] 券商店没写汇率');
  if (!/本月还能换\d+(\.\d+)?元/.test(shop)) {
    bad('[v31] 「本月还能换」没按元显示（应该形如 «本月还能换 20 元»，不是星尘数）');
  }
  const shopBoxes = await page.locator('#view button[data-box]').count();
  say('   商店卖的箱子: ' + shopBoxes + ' 档');
  if (shopBoxes !== 3) bad('[v31] 券商店卖的箱子不是三档，是 ' + shopBoxes);
  for (const tp of ['娱乐券', '陪伴券', '选择券', '豁免券', '独处券', '好友券']) {
    if (shop.indexOf(tp) < 0) bad('[v31] 券商店里没有「' + tp + '」');
  }
  if (shop.indexOf('不含随机件') < 0) bad('[v31] 券商店的箱子没写「不含随机件」');
  if (/出随机件/.test(shop)) bad('[v31] 券商店还在写「% 出随机件」（概率只写在宝箱页）');
  if (shop.indexOf('随机件只在宝箱里出') < 0) bad('[v31] 券商店没说清随机件只在宝箱里出');
  if (shop.indexOf('卡也不卖') < 0) bad('[v31] 券商店没说清卡不卖');
  if (await page.locator('#view button[data-c]').count()) bad('[v31] 券商店在卖卡');
  if (shop.indexOf('零花钱记录') < 0) bad('[v31] 券商店没摆零花钱记录');
  await page.screenshot({ path: path.join(SHOT, 'kid-shop.png'), fullPage: true });

  // 换零花钱：弹层里当场把星尘换算成元，别让孩子自己乘 0.5
  const cashBtn = page.locator('#view #kExCash');
  if (await cashBtn.count()) {
    await cashBtn.click();
    await page.waitForTimeout(700);
    const kSheetTxt = flat(await page.locator('#sheetBody').innerText().catch(() => ''));
    say('   换零花钱弹层: ' + kSheetTxt.slice(0, 120));
    if (!/扣\d+(\.\d+)?星尘，换\d+(\.\d+)?元/.test(kSheetTxt)) {
      bad('[v31] 兑换弹层没把星尘换算成元：' + kSheetTxt.slice(0, 80));
    }
    if (kSheetTxt.indexOf('爸爸妈妈点同意') < 0) bad('[v31] 兑换弹层没说是家长批了才发钱');
    if (kSheetTxt.indexOf('收到了') < 0) bad('[v31] 兑换弹层没说孩子还要确认收到');
    await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(300);
  } else {
    say('   换零花钱：手上没星尘，弹层没出现（不算错）');
  }

  // ---------- 「我的」和它下面的二级页 ----------
  say('');
  say('4. 孩子端「我的」与二级页:');
  await kidGo('mine');
  const mine = kidView.mine;
  for (const want of ['心愿屋', '图鉴', '我的记录', '家庭', '头像与皮肤']) {
    if (mine.indexOf(want) < 0) bad('[v31] 「我的」里没有「' + want + '」入口');
  }
  if (mine.indexOf('升级进度') < 0) bad('[v31] 「我的」里没有升级进度');
  if (!/Lv\.\d/.test(mine)) bad('[v31] 「我的」里没显示等级');
  /* v38：三宫格第二格从「券在手 · 张」改成「特权道具」，数的是一共多少件
     （券 + 卡）。点它、或者点它上面那个数字，都该去券包；第三格「本月完美日」
     点去我的记录。这两格原来只是一块不能点的文字。 */
  if (mine.indexOf('特权道具') < 0) bad('[v38] 「我的」第二格没改成「特权道具」');
  if (mine.indexOf('券在手') >= 0) bad('[v38] 「我的」里还留着「券在手」');
  const tapPriv = page.locator('#view .k-tap[data-go="coupon"]');
  const tapPerf = page.locator('#view .k-tap[data-go="record"]');
  if (!(await tapPriv.count())) bad('[v38] 「特权道具」那一格点不动');
  if (!(await tapPerf.count())) bad('[v38] 「本月完美日」那一格点不动');
  if (await tapPriv.count()) {
    await tapPriv.first().click();
    await page.waitForTimeout(900);
    if ((await kidText()).indexOf('我手上的卡') < 0) {
      bad('[v38] 点「特权道具」没跳到券包');
    }
    await kidGo('mine');
    await page.waitForTimeout(600);
  }
  if (await tapPerf.count()) {
    await tapPerf.first().click();
    await page.waitForTimeout(900);
    const recTxt = await kidText();
    if (recTxt.indexOf('我的记录') < 0) bad('[v38] 点「本月完美日」没跳到我的记录');
    await kidGo('mine');
    await page.waitForTimeout(600);
  }
  // 头像：孩子自己能挑。最后一步数图片有没有真的加载出来 ——
  // 光有 <img> 标签不算数，SVG 路径写错一样是 404 加一个空框，DOM 上看不出来。
  if (!(await page.locator('#view .hero img').count())) {
    bad('[v25] 「我的」顶部的头像还是文字，没换成图');
  }
  const avBtn = page.locator('#view #kAvEdit');
  if (!(await avBtn.count())) {
    bad('[v25] 头像入口点不了');
  } else {
    await avBtn.click();
    await page.waitForTimeout(600);
    const avTxt = flat(await page.locator('#sheetBody').innerText());
    const avCells = await page.locator('#sheetBody .av-pick').count();
    say('   头像弹层: ' + avCells + ' 个格子 / ' + avTxt.slice(0, 40));
    // v36：从 12 张扩到 40 张（爸爸/妈妈/男孩/女孩四组各 10 张）
    if (avCells !== 40) bad('[v36] 头像格子不是 40 个，是 ' + avCells);
    for (const g of ['爸爸', '妈妈', '男孩', '女孩']) {
      if (avTxt.indexOf(g) < 0) bad('[v25] 头像弹层里没有「' + g + '」那一组');
    }
    const brokenAv = await page.evaluate(() => Array.from(
      document.querySelectorAll('#sheetBody .av-pick img'))
      .filter(i => !i.complete || i.naturalWidth === 0).length);
    const avImgs = await page.locator('#sheetBody .av-pick img').count();
    say('   头像图: ' + avImgs + ' 张，加载失败 ' + brokenAv + ' 张');
    if (avImgs !== 40) bad('[v36] 头像弹层里不是 40 张图，是 ' + avImgs);
    if (brokenAv) bad('[v25] 有 ' + brokenAv + ' 张头像图没加载出来');
    await page.screenshot({ path: path.join(SHOT, 'kid-avatar.png'), fullPage: true });
    await page.evaluate(() => document.querySelector('#sheet').classList.remove('on'));
    await page.waitForTimeout(250);
  }

  // 成长报告：从首页那张能量卡点进去（整卡可点）。不排排行榜是硬规则。
  await kidGo('home');
  await page.locator('#view [data-go="report"]').first().click();
  await page.waitForTimeout(1000);
  const rep = await kidText();
  say('   成长报告: ' + rep.slice(0, 46));
  if (rep.indexOf('成长报告') < 0) bad('[v31] 首页的能量卡点不进成长报告');
  if (rep.indexOf('七种能量') < 0) bad('[v31] 成长报告没有「七种能量」');
  if (rep.indexOf('本月完美日') < 0) bad('[v31] 成长报告没有「本月完美日」');
  if (rep.indexOf('没有排行榜') < 0) bad('[v31] 成长报告没写明「这里没有排行榜」');
  if (/排行榜|排名|第\d+名/.test(rep.replace(/没有排行榜/g, ''))) {
    bad('[v31] 成长报告里出现了排行榜/排名');
  }
  const radar = await page.evaluate(() => document.querySelectorAll(
    '#view svg polygon, #view svg polyline').length);
  say('   雷达/折线: ' + radar + ' 个');
  if (!radar) bad('[v31] 成长报告的雷达图没画出来');
  // 二级页也要有它所属的那一格亮着，不然进去就不知道自己在哪
  const onTab = flat(await page.locator('#tabs button.on').innerText().catch(() => ''));
  say('   二级页高亮的那一格: ' + onTab);
  if (onTab.indexOf('首页') < 0) bad('[v31] 二级页高亮没落在它所属的那一格上');
  await page.screenshot({ path: path.join(SHOT, 'kid-report.png'), fullPage: true });

  // 心愿屋
  await kidGo('wish');
  const wish = await kidText();
  say('   心愿屋: ' + wish.slice(0, 46));
  for (const want of ['心愿屋', '我的心愿', '许愿池']) {
    if (wish.indexOf(want) < 0) bad('[v31] 心愿屋缺少「' + want + '」');
  }
  if (!(await page.locator('#view #kWnew').count())) bad('[v31] 心愿屋没有「我想要……」的入口');
  // v26 多选条件：主条画的是「做到几条」，不是某一条的百分比。
  // v31 起子条件只在下面那排列一次（以前进度块里一遍、按条那排又一遍）。
  const subRows = await page.locator('#view .wsubs .row').count();
  const wprog = flat(await page.locator('#view .wprog').allInnerTexts());
  const wsubs = flat(await page.locator('#view .wsubs').allInnerTexts());
  say('   多选条件: 子行 ' + subRows + ' 行 / ' + wprog.slice(0, 40) +
      ' / ' + wsubs.slice(0, 40));
  if (subRows < 3) bad('[v26] 多选条件没把每条各列一行（只数到 ' + subRows + ' 行）');
  if (wprog.indexOf('要2条') < 0) bad('[v26] 多选条件没写出「要凑够几条」');
  if (wsubs.indexOf('把书桌自己收拾干净') < 0) {
    bad('[v26] 多选里那条自己写的原话没显示出来');
  }
  // 同一排条件列两遍：进度块里一次、按条那排又一次，孩子会以为有八条要做
  if (await page.locator('#view .wprog .wsubs').count()) {
    bad('[v31] 心愿卡把同一排子条件列了两遍（进度块里一遍、按条那排又一遍）');
  }
  // 「自己写一条」系统算不了：孩子端给按钮（已确认 / 等确认时换成状态标签）
  const manualRow = page.locator('#view .wsub').filter({ hasText: '把书桌' }).first();
  const manualHTML = await manualRow.innerHTML().catch(() => '');
  const manualTxt = flat(await manualRow.innerText().catch(() => ''));
  say('   自己写的那条: ' + manualTxt.slice(0, 40));
  if (!/data-wsubmit|data-wself|data-wsend/.test(manualHTML)
      && !/等确认|做到了|靠人判/.test(manualTxt)) {
    bad('[v26] 多选里那条自己写的没标出「这一步该谁按」');
  }
  if (wish.indexOf('我做到了') < 0) bad('[v25] 心愿里没有「我做到了」的入口');
  // v29 按条提交：条件块、按条提交的按钮、是谁确认的
  const submitBtns = await page.locator('#view button[data-wsubmit]').count();
  const payBtn = await page.locator('#view [data-wself]').count();
  say('   按条提交 ' + submitBtns + ' 个 / 星尘自付 ' + payBtn + ' 个');
  if (wish.indexOf('要做到什么') < 0) bad('[v29] 心愿卡没把条件单独提出来');
  if (wish.indexOf('提醒') < 0) bad('[v29] 心愿卡没把提醒事项单列出来');
  if (!submitBtns) bad('[v29] 心愿里没有「按这一条提交」的按钮');
  if (wish.indexOf('妈妈确认') < 0) bad('[v29] 通过的那条没写是谁确认的');
  // 心愿历史：结束的心愿不消失，默认收起，点开看一眼
  if (await page.locator('#view #kHistTg').count()) {
    await page.locator('#view #kHistTg').click();
    await page.waitForTimeout(700);
    const histTxt = flat(await page.locator('#view .hist-body').innerText().catch(() => ''));
    say('   历史心愿: ' + histTxt.slice(0, 60));
    if (!/已达成|被驳回|自己放弃|自己撤了|已结束/.test(histTxt)) {
      bad('[v31] 历史心愿里没标出「怎么结束的」');
    }
  } else if (wish.indexOf('历史心愿') < 0) {
    bad('[v31] 心愿屋没有「历史心愿」');
  }
  // 点开许愿表单看一眼就关掉，不提交 —— 提交会往演示库里加数据，巡检就跑不了第二遍
  await page.locator('#view #kWnew').click();
  await page.waitForTimeout(400);
  const newForm = flat(await page.locator('#sheetBody').innerText());
  if (newForm.indexOf('想要什么') < 0 || newForm.indexOf('挂上去') < 0) {
    bad('[v31] 许愿表单没打开或者缺字段');
  }
  await page.evaluate(() => document.querySelector('#sheet').classList.remove('on'));
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(SHOT, 'kid-wish.png'), fullPage: true });

  // 图鉴 / 我的记录 / 家庭
  await kidGo('atlas');
  const atlas = await kidText();
  say('   图鉴: ' + atlas.slice(0, 46));
  if (atlas.indexOf('已收集') < 0) bad('[v31] 图鉴没写收集进度');
  if (atlas.indexOf('卡不卖') < 0) bad('[v31] 图鉴没说清卡不卖');
  // v38：「手上能用的卡」整段搬去了券包，图鉴里不该再出现 —— 留着的话
  // 「我手上有什么能用的」会在两页各列一份，迟早对不上。
  if (atlas.indexOf('手上能用的卡') >= 0) bad('[v38] 图鉴里还留着「手上能用的卡」');
  const atlasUse = await page.locator('#view button[data-use]').count();
  if (atlasUse) bad('[v38] 图鉴里还挂着「用」按钮（' + atlasUse + ' 个），启用该在券包');
  await page.screenshot({ path: path.join(SHOT, 'kid-atlas.png'), fullPage: true });

  await kidGo('record');
  const rec = await kidText();
  say('   我的记录: ' + rec.slice(0, 46));
  if (rec.indexOf('我的记录') < 0) bad('[v31] 没有「我的记录」页');
  if (rec.indexOf('七项分别是什么') < 0) bad('[v31] 记录页没有「七项分别是什么」');
  const dimRows = await page.locator('#view .dgrid').count();
  say('   七项各自的天格子: ' + dimRows + ' 行');
  if (dimRows !== 7) bad('[v31] 记录页七项不是 7 行，是 ' + dimRows);
  if (rec.indexOf('被扣') < 0) bad('[v31] 记录页没把扣分理由摆出来');
  if (rec.indexOf('刷牙') < 0 && rec.indexOf('桌面') < 0) bad('[v31] 扣分理由没写具体那句话');
  if (rec.indexOf('加分和扣分') < 0) bad('[v31] 记录页没有「加分和扣分」这一段');
  await page.screenshot({ path: path.join(SHOT, 'kid-record.png'), fullPage: true });

  await kidGo('family');
  const fam = await kidText();
  say('   家庭: ' + fam.slice(0, 46));
  if (fam.indexOf('家庭') < 0) bad('[v31] 没有「家庭」页');
  if (fam.indexOf('口人') < 0) bad('[v31] 家庭页没写几口人');
  await page.screenshot({ path: path.join(SHOT, 'kid-family.png'), fullPage: true });

  // 概率只写在宝箱页：别的底栏页一个字都不许有
  for (const v of ['home', 'task', 'coupon', 'mine']) {
    if (/出随机件|随机件概率/.test(kidView[v])) {
      bad('[v25] 「' + v + '」页出现了概率（概率只写在宝箱页）');
    }
  }
  // 一屏九宫格截图之外，再留一份「刚才这一套还认得出来吗」的凭据
  say('   孩子端各屏文字长度: ' + Object.keys(kidView)
    .map(k => k + '=' + kidView[k].length).join(' '));

  // 家长端「最近发生」（v28）：孩子自己做的每一件事都要看得见。
  // 这一屏不在底栏五格里，从总览那张「最近发生」卡的「查看全部」进去。
  await page.evaluate(() => fetch('/api/logout', { method: 'POST' }));
  await login(page, '爸爸');
  await clickSel(page, '#view [data-go="logs"]', '总览 → 查看全部');
  const lg = flat(await page.locator('#view').innerText());
  const logRows = await page.locator('#view .log-item').count();
  say('   家长端日志页: ' + logRows + ' 条');
  if (lg.indexOf('最近发生') < 0) bad('[v28] 家长端没有「最近发生」（交付包里的动态日志）页');
  if (logRows < 5) bad('[v28] 日志页条目太少（' + logRows + ' 条），演示库该有东西');
  // 「券突然多了」的答案：买了还是开出来的，日志里要能一眼看出
  if (lg.indexOf('买了券') < 0) bad('[v28] 日志里看不到「买了券」（券的来源查不出来）');
  if (lg.indexOf('开出') < 0) bad('[v28] 日志里看不到「开出」（宝箱发券查不出来）');
  // v29：每一条都得写清是谁经手的。「爸爸妈妈经手」这种统称等于没写 ——
  // 两个大人各有一套口径时，孩子问「谁扣的」，回答「大人扣的」没用。
  const byTxt = flat((await page.locator('#view .log-item .meta').allInnerTexts()).join(' '));
  say('   日志经手人: ' + (byTxt.match(/妈妈|爸爸|女儿|儿子|系统/g) || []).slice(0, 8).join(' '));
  if (!/妈妈|爸爸/.test(byTxt)) bad('[v29] 日志里没写出具体是谁经手的');
  if (byTxt.indexOf('经手') < 0) bad('[v29] 日志没标出「经手」');
  // 交付包的三维筛选：孩子 / 类型 / 日期各一行，可叠加；「自定义」是虚线描边
  const chipRows = await page.locator('#view .chip-row').count();
  const chips = await page.locator('#view .chip').count();
  const chipDash = await page.locator('#view .chip--dashed').count();
  const logGroups = await page.locator('#view .log-group').count();
  say('   日志页筛选: ' + chipRows + ' 行共 ' + chips + ' 个 · 来源分堆 ' + logGroups + ' 堆');
  if (chipRows !== 3) bad('[v28] 日志筛选不是三维（孩子/类型/日期），是 ' + chipRows + ' 行');
  if (chips < 6) bad('[v28] 日志页筛选按钮太少（' + chips + ' 个）');
  if (!chipDash) bad('[v28] 日期那一行没有虚线描边的「自定义」');
  if (logGroups < 2) bad('[v28] 日志没有按来源分堆，几十条混在一起看不出「谁给的」');
  // 筛选与叠加
  await page.locator('#view .chip[data-lf="group"][data-lv="self"]').first().click();
  await page.waitForTimeout(900);
  const lg2 = flat(await page.locator('#view').innerText());
  say('   只看「孩子自己做的」: 剩 ' + (await page.locator('#view .log-item').count()) + ' 条');
  if (lg2.indexOf('打分') >= 0) bad('[v28] 筛「孩子自己做的」还混进了打分');
  await page.screenshot({ path: path.join(SHOT, 'dad-logs.png'), fullPage: true });
  await page.locator('#view .chip[data-lf="group"][data-lv=""]').first().click();
  await page.waitForTimeout(700);

  // ---------- 家长端 ----------
  await page.evaluate(() => fetch('/api/logout', { method: 'POST' }));
  const dad = await login(page, '爸爸');
  say('');
  say('4. 家长端已登录: ' + dad);
  const pTabs = await tabLabels(page);
  say('   tab: ' + JSON.stringify(pTabs));
  // 换皮后底栏只剩五格：总览 / 审核 / 打分 / 发布 / 我的。
  // 「日志」变成总览里的二级页，「设置」搬进「我的」，「任务」并进「发布」，
  // 三处都还在，只是不再各占一格 —— 断言跟着走，不是把这三条删了。
  for (const want of ['总览', '审核', '打分', '发布', '我的']) {
    if (pTabs.join('|').indexOf(want) < 0) bad('[导航缺项] 家长端少了「' + want + '」');
  }
  for (const forbidden of ['宝箱', '商店']) {
    if (pTabs.join('|').indexOf(forbidden) >= 0) bad('[越权导航] 家长端出现了「' + forbidden + '」');
  }
  // 顶栏没了：切孩子搬到打分页头上那个小胶囊（「我是谁」搬进「我的」的身份卡）
  await tabTo(page, '打分');
  await page.waitForTimeout(900);
  const swBtns = await page.locator('#view .kid-switch button').count();
  const swOn = flat(await page.locator('#view .kid-switch button.on').innerText().catch(() => ''));
  say('   打分页切孩子胶囊: ' + swBtns + ' 个，当前 ' + swOn);
  if (swBtns < 1) bad('[导航] 打分页没有切孩子的地方');

  say('');
  say('5. 家长端各页:');
  const pViews = await walkTabs(page, 'dad');
  say('   ' + pViews.join(' '));

  // 家长端审核页。演示库里留了一条待办，这里只验证渲染与接线，
  // 不点「同意」—— 点了就把这条演示数据花掉，巡检就不可重复跑了。
  await tabTo(page, '审核');
  await page.waitForTimeout(900);
  const rev = flat(await page.locator('#view').innerText());
  // 券那一件：孩子想核销，家长得先看见「现在批了还能不能用」
  const tkOk = await page.locator('#view button[data-td="tk-ok"]').count();
  const tkNo = await page.locator('#view button[data-td="tk-no"]').count();
  const tkBody = await page.locator('#view [data-tdid="tk"]').count();
  say('   券待办: ' + tkBody + ' 条, 同意按钮 ' + tkOk + ', 拒绝按钮 ' + tkNo);
  if (!tkBody) bad('[券核销] 演示库里那条券核销申请没出现在审核页');
  if (tkOk !== tkNo) bad('[券核销] 同意/拒绝按钮数量对不上：' + tkOk + ' vs ' + tkNo);
  if (tkBody && !/现在批了|过不了闸门|券还在他手上/.test(rev)) {
    bad('[券核销] 待办里没写明「此刻点了会发生什么」');
  }
  if (tkNo) {
    await page.locator('#view button[data-td="tk-no"]').first().click();
    await page.waitForTimeout(500);
    const sheetTxt = flat(await page.locator('#sheetBody').innerText().catch(() => ''));
    if (!/不同意|拒绝/.test(sheetTxt)) bad('[券核销] 点拒绝没弹出写理由的弹层');
    if (!(await page.locator('#sheet.on textarea, #sheet.on input').count())) {
      bad('[券核销] 拒绝弹层里没有写理由的地方');
    }
    await page.locator('#sheet').click({ position: { x: 5, y: 5 } });
    await page.waitForTimeout(350);
  }
  await page.screenshot({ path: path.join(SHOT, 'dad-review-ticket.png'), fullPage: true });

  // v29：孩子交上来的那一条。以前「我做到了」是一个整条心愿的按钮，
  // 家长在审核页只看到「他说他做到了」，不知道指的是哪一条 —— 只能去问。
  const claimRows = await page.locator('#view [data-tdid="claim"]').count();
  const claimBtns = await page.locator('#view button[data-td="claim-look"]').count();
  say('   孩子说做到了: ' + claimRows + ' 条待确认');
  if (!claimRows) bad('[v29] 演示库里孩子交的那条没出现在审核页');
  if (!/[女儿子爸]{2}说「/.test(rev)) bad('[v29] 待办里没写清他交的是哪一条');
  if (rev.indexOf('做到了') < 0) bad('[v29] 待办里看不出孩子说的是「做到了」');
  if (rev.indexOf('他说：') < 0) bad('[v29] 待办里没写孩子自己说的那句话');
  if (claimRows !== claimBtns) bad('[v29] 心愿提交的待办数跟「看看」按钮对不上：' + claimRows + ' vs ' + claimBtns);

  // v24：审核页的另外两块 —— 孩子挂起的心愿、零花钱兑换。
  // 以前心愿只藏在「设置 → 心愿单」弹层里，孩子写完那句「等爸爸妈妈定条件」
  // 就再没人回应；零花钱兑换干脆没有流程，孩子点一下系统就扣星尘，
  // 「谁把现金给他」这一步从没发生过。
  const wcfg = await page.locator('#view button[data-td="wcfg"]').count();
  const cashOk = await page.locator('#view button[data-td="cash-ok"]').count();
  const cashNo = await page.locator('#view button[data-td="cash-no"]').count();
  say('   挂着等定条件的心愿 ' + wcfg + ' 条；零花钱 同意 ' + cashOk + ' / 不同意 ' + cashNo);
  if (!wcfg) bad('[v24] 演示库里挂着的心愿没出现在审核页');
  if (rev.indexOf('还没定条件') < 0) bad('[v24] 挂起的心愿没写清「还没定条件」');
  if (cashOk !== cashNo) bad('[v24] 零花钱的同意/不同意按钮对不上：' + cashOk + ' vs ' + cashNo);
  if (cashOk && rev.indexOf('同意就等于发放') < 0) {
    bad('[v24] 零花钱那一条没写清「同意就等于发放」');
  }
  if (rev.indexOf('已发放的零花钱') < 0) bad('[v24] 审核页没有「已发放的零花钱」那一栏');
  // 进行中的心愿：行内只留「达成」一颗，撤心愿收进区块头那颗入口。
  // 撤是低频动作，跟着每一行复制一遍的话，三行叠着最右边缘就出现三颗
  // 一样的「取消」，家长扫列表的落点正好压在上面。
  const wOk = await page.locator('#view button[data-wok]').count();
  const wNo = await page.locator('#view button[data-wx]').count();
  say('   进行中的心愿 ' + wOk + ' 条（每行「达成」' + wOk + ' 颗 · 行内「取消」' + wNo + ' 颗）');
  if (rev.indexOf('进行中的心愿') < 0) bad('[v24] 审核页没有「进行中的心愿」');
  if (!wOk) bad('[v17] 进行中的心愿一条都没列出来');
  if (wNo) bad('[v17] 心愿列表行还留着「取消」按钮，撤心愿该走区块头那颗');
  if (await page.locator('#view #wManage').count() !== 1) {
    bad('[v17] 心愿区块头没有「撤心愿」这一颗入口');
  }
  if (wcfg) {
    await page.locator('#view button[data-td="wcfg"]').first().click();
    await page.waitForTimeout(600);
    const cfgSheet = flat(await page.locator('#sheetBody').innerText().catch(() => ''));
    if (cfgSheet.indexOf('怎么才算够格') < 0) bad('[v24] 点「定条件」没弹出条件表单');
    await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(300);
  }
  if (cashNo) {
    await page.locator('#view button[data-td="cash-no"]').first().click();
    await page.waitForTimeout(500);
    const rejSheet = flat(await page.locator('#sheetBody').innerText().catch(() => ''));
    if (rejSheet.indexOf('不同意这次兑换') < 0) bad('[v24] 点不同意没弹出写理由的弹层');
    if (!(await page.locator('#sheet.on textarea').count())) {
      bad('[v24] 不同意兑换的弹层里没有写理由的地方');
    }
    await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(300);
  }

  // v27：审核页和总览都要能看见「谁在玩、还剩多久」。这件事有时效，
  // 埋在后面等于没有；家长点完同意也得立刻看到那一刻开始计时了，
  // 不然屏幕没变化，会以为自己没点上。
  // 换皮后这块走羊皮纸重点卡，卡片标题就是「谁 · 什么券」，
  // 大数字是 mm:ss 倒计时，配一根进度条 —— 锚点认 data-tk* 这组。
  await tabTo(page, '审核');
  await page.waitForTimeout(900);
  const revRun = await page.locator('#view [data-tkend]').count();
  const revWho = revRun ? flat(await page.locator('#view [data-tkend] .card-title').first().innerText()) : '';
  say('   审核页正在玩: ' + revRun + ' 块 ' + revWho.slice(0, 30));
  if (!revRun) bad('[v27] 审核页没有「正在玩」那一块');
  if (revRun && !/女儿|儿子/.test(revWho)) bad('[v27] 审核页的「正在玩」没写是谁在玩');

  // v24/v17 的两段已经走完，接着看总览。
  await tabTo(page, '总览');
  await page.waitForTimeout(900);
  const home = flat(await page.locator('#view').innerText());
  // 交付包里速览从「一人一张卡」改成「一人一行」：一屏扫完两个孩子，
  // 不必先切两次人。六项细节（券卡碎片、在做几件事）挪进孩子详细页，
  // 这里每行留的是「本周能量 / 星尘 / 今天打没打」。
  const kRows = await page.locator('#view [data-kid]').count();
  const kidRowsN = +(home.match(/全部(\d+)位/) || [])[1] || 0;
  say('   孩子速览: ' + kRows + ' 行（「全部 N 位」写的 ' + kidRowsN + '）');
  if (kRows < 2) bad('[v15] 总览没把所有孩子都列出来，只有 ' + kRows + ' 行');
  if (kidRowsN && kRows !== kidRowsN) {
    bad('[v15] 速览行数与「全部 N 位」对不上：' + kRows + ' vs ' + kidRowsN);
  }
  // 家长身份要写出来。交付包管这个角色叫「领航员」，不再叫「裁判」——
  // 同一个意思换了词，换的是「跟着一起走」而不是「站在旁边判」。
  if (!/领航员|裁判/.test(home)) bad('[v13] 家长总览没标出「领航员 / 裁判」身份');
  for (const need of ['星尘', '本周能量', '今天']) {
    if (home.indexOf(need) < 0) bad('[v15] 速览行缺「' + need + '」这一项');
  }
  if (!/今天还没给|今天的分都记上了/.test(home)) bad('[v15] 总览没标出今天打分没有');
  // 还没打分的写「未打」，不写 0/7 ——「0 分」和「没打分」不是一件事
  if (home.indexOf('未打') >= 0 && /0\/7/.test(home)) {
    bad('[v15] 速览里把没打分写成了 0/7，两件事混成一件');
  }

  const homeRun = await page.locator('#view [data-tkend]').count();
  const homeRunTxt = homeRun ? flat(await page.locator('#view [data-tkend]').first().innerText()) : '';
  say('   总览正在玩: ' + homeRun + ' 块');
  if (!homeRun) bad('[v27] 家长总览没有「正在玩」这一块');
  if (homeRun) {
    if (!/女儿|儿子/.test(homeRunTxt)) bad('[v27] 总览的「正在玩」没写是谁在玩');
    // 倒计时得真的在走。隔一秒读两次，值必须变小 ——
    // 只断言「有个数字」的话，写死一串也过得去。
    const t1 = flat(await page.locator('#view [data-tkleft]').first().innerText());
    await page.waitForTimeout(1100);
    const t2 = flat(await page.locator('#view [data-tkleft]').first().innerText());
    say('   总览倒计时: ' + t1 + ' -> ' + t2);
    if (!/^\d+:\d\d$/.test(t1)) bad('[v27] 总览倒计时不是 mm:ss：' + t1);
    if (t1 === t2) bad('[v27] 总览的倒计时没在走（两次读到的都是 ' + t1 + '）');
    if (!(await page.locator('#view [data-tkbar]').count())) bad('[v27] 总览的「正在玩」没有进度条');
  }
  // 「正在玩」必须排在孩子速览前面：有时效的东西不该埋在下面
  const runPos = await page.evaluate(() => {
    const v = document.querySelector('#view');
    const tk = v.querySelector('[data-tkend]');
    const sec = Array.prototype.slice.call(v.querySelectorAll('.sec-title'))
      .filter(x => x.textContent.indexOf('孩子速览') >= 0)[0];
    if (!tk || !sec) return 'unknown';
    return (tk.compareDocumentPosition(sec) & Node.DOCUMENT_POSITION_FOLLOWING) ? 'before' : 'after';
  });
  say('   正在玩相对孩子速览: ' + runPos);
  if (runPos === 'after') bad('[v27] 「正在玩」被压到孩子速览后面了');
  if (!homeRun) bad('[v27] 总览的「正在玩」没渲染出卡片');

  // 最近发生：首页只放两条，其余的点进日志页
  const feedRows = await page.locator('#view .log-item').count();
  say('   总览最近发生: ' + feedRows + ' 条');
  if (home.indexOf('最近发生') < 0) bad('[v18] 家长总览没有「最近发生」');
  if (!feedRows) bad('[v18] 家长总览的「最近发生」一条都没渲染出来');
  await page.screenshot({ path: path.join(SHOT, 'dad-kids-overview.png'), fullPage: true });

  // v18：两个孩子手上各自还没完的事，每条都得写着是谁的。
  // 交付包把「谁的事」收进审核页那一串待办卡里（首页只留计数），
  // 所以这条断言跟着搬到审核页 —— 抽查的是同一句话：每件事写出是谁的。
  await tabTo(page, '审核');
  await page.waitForTimeout(900);
  const cards = page.locator('#view [data-tdid]');
  const cn = await cards.count();
  let named = 0;
  for (let i = 0; i < cn; i++) {
    if (/女儿|儿子/.test(flat(await cards.nth(i).innerText()))) named++;
  }
  // 「设置改动等你点头」不是哪个孩子的事，本来就不带名字，单独排除
  const setN = await page.locator('#view [data-tdid="set"]').count();
  say('   审核页待办: ' + cn + ' 件，写出是谁的 ' + named + ' 件（其中设置类 ' + setN + ' 件）');
  if (!cn) bad('[v18] 审核页一件待办都没渲染出来');
  if (named !== cn - setN) bad('[v18] 有 ' + (cn - setN - named) + ' 件待办没写清是谁的事');

  // 详细页：从总览点一行孩子进去
  await tabTo(page, '总览');
  await page.waitForTimeout(700);
  await clickSel(page, '#view [data-kid]', '总览 → 孩子速览行');
  const kd = flat(await page.locator('#view').innerText());
  const backBar = await page.locator('#view [data-back]').count();
  say('   孩子详细: 返回按钮 ' + backBar + ' 个');
  if (!backBar) bad('[v15] 详细页没有返回按钮，进去就出不来');
  // 速览上收掉的那几项，全在这一层。缺一项都是家长少一个能问的地方。
  for (const need of ['LV', '星尘', '欠款', '券', '卡', '碎片', '在做的事',
                      '这个周期', '这一周', '拥有']) {
    if (kd.indexOf(need) < 0) bad('[v15] 详细页缺「' + need + '」段');
  }
  await page.screenshot({ path: path.join(SHOT, 'dad-kid-detail.png'), fullPage: true });

  // 记录页：天 × 维度 矩阵
  await page.locator('#view button[data-kh]').last().click();
  await page.waitForTimeout(1100);
  const rows = await page.locator('#view table.mx tbody tr').count();
  const cols = await page.locator('#view table.mx thead th').count();
  const whyHidden = await page.locator('#view tr.mx-why[hidden]').count();
  say('   打分记录: ' + rows + ' 行, ' + cols + ' 列, 收着的「为什么」 ' + whyHidden + ' 行');
  if (cols !== 9) bad('[v15] 记录页列数不对（应为 日期 + 7 维度 + 合计 = 9），是 ' + cols);
  if (rows < 10) bad('[v15] 记录页天数太少：' + rows);
  if (await page.locator('#view .rangepick button').count() !== 3) {
    bad('[v15] 记录页没有范围切换');
  }
  if (!/各维度达成率/.test(await page.locator('#view').innerText())) {
    bad('[v15] 记录页没有各维度达成率');
  }
  // 展开一行，确认「为什么扣」确实能点出来
  const hasWhy = page.locator('#view tr.haswhy').first();
  if (await hasWhy.count()) {
    const visibleBefore = await page.locator('#view tr.mx-why:not([hidden])').count();
    await hasWhy.click();
    await page.waitForTimeout(300);
    const visibleAfter = await page.locator('#view tr.mx-why:not([hidden])').count();
    say('   点一行展开: ' + visibleBefore + ' -> ' + visibleAfter);
    if (visibleAfter <= visibleBefore) bad('[v15] 点日期行没有展开「为什么扣」');
  }
  await page.screenshot({ path: path.join(SHOT, 'dad-score-history.png'), fullPage: true });

  // 家长端「我发出的」活（原任务页）：三个分组 + 撤销的边界。
  // 换皮后它并进「发布」这个 tab 的第二个分段，不再单独占一格。
  await tabTo(page, '发布');
  await page.waitForTimeout(700);
  await page.locator('#view .seg-item[data-pseg="mine"]').first().click();
  await page.waitForTimeout(1100);
  const heads = (await page.locator('#view .sec-title').allInnerTexts()).map(flat);
  say('   发出的活: ' + heads.join(' / '));
  if (heads.indexOf('等人领') < 0) bad('[v15] 任务页没有「等人领」分组');
  if (heads.indexOf('进行中') < 0) bad('[v15] 任务页没有「进行中」分组');
  if (heads.indexOf('等你确认') < 0) bad('[v15] 任务页没有「等你确认」分组');
  const revokeAll = await page.locator('#view button[data-tv]').count();
  const revokeOff = await page.locator('#view button[data-tv][disabled]').count();
  say('   撤销按钮: ' + revokeAll + ' 个，其中禁用 ' + revokeOff + ' 个');
  if (!revokeAll) bad('[v15] 任务页一个撤销按钮都没有');
  if (!revokeOff) bad('[v15] 有人领着的任务居然是能撤的（缺 disabled）');
  const tkTxt = flat(await page.locator('#view').innerText());
  if (tkTxt.indexOf('撤不掉') < 0) bad('[v15] 撤不掉的按钮没写清为什么');
  await page.screenshot({ path: path.join(SHOT, 'dad-tasks.png'), fullPage: true });

  // 上面那三行只查了「等你确认」这个分组标题在不在，查不出按钮是不是真能点。
  // 家长端任务页的「确认」原来点了没反应：bindTaskPage() 直接引用了
  // pTasksHTML() 里的局部量 submitted，函数外根本取不到，一点就 ReferenceError，
  // 确认层弹不出来。所以要真点一次 —— 界面在、按钮在、点了没动静，只有点才露。
  const tcAll = await page.locator('#view button[data-tc]').count();
  say('   「等你确认」的确认按钮: ' + tcAll + ' 个');
  if (!tcAll) bad('[任务页] 演示库里有人交了活，任务页却一颗「确认」都没有');
  await page.locator('#view button[data-tc]').first().click();
  await page.waitForTimeout(600);
  const tcSheet = flat(await page.locator('#sheetBody').innerText().catch(() => ''));
  say('   点「确认」弹出的层: ' + tcSheet.slice(0, 40));
  // 名字必须有：找不到那条任务时 t 会退化成空对象，标题就成了「交了「」」。
  if (!/交了「.+」/.test(tcSheet)) {
    bad('[任务页] 点「确认」没弹出确认层（bindTaskPage 又在引用作用域外的 submitted？）');
  }
  if (tcSheet.indexOf('确认完成') < 0) bad('[任务页] 确认层里没有「确认完成」');
  await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
  await page.waitForTimeout(300);
  if (await page.locator('#sheet.on').count()) bad('[任务页] 确认层点背景关不掉');

  // 家长端打分页（v37）：这一天站在哪一格，页头那颗标签说了算。
  // 未打 / 补卡是点一下即存；打过的（修改）默认只读，先点「修改」，
  // 底部才出现取消 / 保存。超时与锁死那两格一个按钮都没有。
  await tabTo(page, '打分');
  await page.waitForTimeout(900);
  const score = flat(await page.locator('#view').innerText());
  const dimCount = await page.locator('#view .dim-row').count();
  const swNow = flat(await page.locator('#view .kid-switch button.on').innerText().catch(() => ''));
  const dayTag = flat(await page.locator('#view .sband .pill').first().innerText().catch(() => ''));
  const DAY_TAGS = ['未打', '补卡', '修改', '超时', '锁死'];
  say('   打分页: 维度 ' + dimCount + ' 项, 这一屏在给 ' + swNow +
    ' 打分, 状态「' + dayTag + '」');
  if (dimCount !== 7) bad('[打分页] 维度数不是 7，是 ' + dimCount);
  if (!swNow) bad('[打分页] 没标出这一屏在给谁打分');
  if (await page.locator('#view #saveScore').count()) bad('[打分页] 还留着「提交」按钮');
  if (DAY_TAGS.indexOf(dayTag) < 0) {
    bad('[打分页] 没给出当天状态标签，读到的是「' + dayTag + '」');
  }
  if (dayTag === '修改') {
    if (score.indexOf('点下面的「修改」才能改') < 0) {
      bad('[打分页] 打过的那天没提示要先点「修改」');
    }
    if (!(await page.locator('#view #pEdit').count())) bad('[打分页] 修改态没给「修改」按钮');
    if (await page.locator('#view #pSave').count()) {
      bad('[打分页] 还没点「修改」就出现了保存按钮');
    }
    await page.locator('#view #pEdit').click();
    await page.waitForTimeout(800);
    const hasSave = await page.locator('#view #pSave').count();
    const hasCancel = await page.locator('#view #pCancel').count();
    say('   点「修改」之后: 保存 ' + hasSave + ' 个 / 取消 ' + hasCancel + ' 个');
    if (!hasSave || !hasCancel) bad('[打分页] 点了「修改」没出现取消/保存');
    if (flat(await page.locator('#view').innerText()).indexOf('改完按保存才算数') < 0) {
      bad('[打分页] 编辑态没写清「保存才算数」');
    }
    await page.locator('#view #pCancel').click();
    await page.waitForTimeout(800);
    if (!(await page.locator('#view #pEdit').count())) {
      bad('[打分页] 按了取消没退回只读那一屏');
    }
    if (await page.locator('#view #pSave').count()) {
      bad('[打分页] 取消之后保存按钮还留着');
    }
  } else {
    if (await page.locator('#view #pEdit').count()) {
      bad('[打分页] 还没打分的日子不该有「修改」按钮');
    }
    if (await page.locator('#view #pSave').count()) {
      bad('[打分页] 点一下即存的日子不该有保存按钮');
    }
    if (await page.locator('#view #pCancel').count()) {
      bad('[打分页] 还没进编辑态就出现了取消按钮');
    }
  }
  await page.screenshot({ path: path.join(SHOT, 'dad-score.png'), fullPage: true });

  // 月度统计（v16）：打分页同一格里的第二个分段，底部那张日历。
  await page.locator('#view .seg-item[data-seg="month"]').first().click();
  await page.waitForTimeout(1200);
  const mScore = flat(await page.locator('#view').innerText());
  const calHead = (await page.locator('#view .cal-grid .cal-wd').allInnerTexts()).map(flat);
  const calCells = await page.locator('#view .cal-cell').count();
  const calDays = await page.locator('#view button[data-cd]').count();
  say('   月度统计: ' + calCells + ' 格，表头 ' + calHead.join('') + '，可点 ' + calDays + ' 天');
  if (mScore.indexOf('月度统计') < 0) bad('[月度统计] 打分页里没有这一块');
  if (calHead.join('') !== '一二三四五六日') {
    bad('[月度统计] 表头不是「一二三四五六日」：' + calHead.join(''));
  }
  if (!calCells) bad('[月度统计] 没有日历格子');
  // 当月只有到今天为止的日子能点。别写死 20，那是「今天几号」的函数。
  if (calDays < 15) bad('[月度统计] 可点的日子太少：' + calDays);
  const fullN = await page.locator('#view .cal-cell.is-full').count();
  if (!fullN && !(await page.locator('#view .cal-cell.is-part').count())) {
    bad('[月度统计] 演示库有整周打分，日历上却没有一个填了色的格子');
  }
  // 月历五态自洽：小结里那两个数字必须和图上数出来的格子一样多。
  // 两处对不上说明有一边算错了 —— 家长会照着图去问那句小结。
  const scoredN = fullN
    + (await page.locator('#view .cal-cell.is-part').count())
    + (await page.locator('#view .cal-cell.is-zero').count());
  const perfTxt = +(mScore.match(/完美日(\d+)天/) || [])[1];
  const daysTxt = +(mScore.match(/打过分的天(\d+)\//) || [])[1];
  say('   小结自洽: 完美日 ' + perfTxt + ' vs 满格 ' + fullN +
      ' · 打过分 ' + daysTxt + ' vs 非虚线 ' + scoredN);
  if (perfTxt !== undefined && perfTxt !== fullN) {
    bad('[月度统计] 小结的「完美日」和图上满格数对不上：' + perfTxt + ' vs ' + fullN);
  }
  if (daysTxt !== undefined && daysTxt !== scoredN) {
    bad('[月度统计] 小结的「打过分的天」和图上非虚线格数对不上：' + daysTxt + ' vs ' + scoredN);
  }
  // 上/下月
  const calNow = flat(await page.locator('#view .cal-head .month').innerText());
  if (await page.locator('#view .cal-nav button').nth(1).isEnabled()) {
    bad('[月度统计] 已经在当月，「下个月」不该能点');
  }
  // v23：翻月不许把页面顶回最上面。月历在打分页最底部，
  // 翻一次就要重新往下滚一遍的话，等于没法连着看几个月。
  await page.locator('#view .cal-head .month').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await page.locator('#view .cal-nav button').first().click();
  await page.waitForTimeout(1200);
  const scrollAfter = await page.evaluate(() => window.scrollY);
  say('   翻月前后滚动位置: ' + scrollBefore + ' -> ' + scrollAfter);
  if (scrollBefore > 200 && scrollAfter < scrollBefore / 2) {
    bad('[月度统计] 翻月把页面顶回去了（' + scrollBefore + ' -> ' + scrollAfter + '）');
  }
  const calPrev = flat(await page.locator('#view .cal-head .month').innerText());
  say('   切月份: ' + calNow + ' -> ' + calPrev);
  if (calNow === calPrev) bad('[月度统计] 点「上个月」月份没变');
  await page.locator('#view .cal-nav button').nth(1).click();
  await page.waitForTimeout(1200);
  // 点某一天，看当天七项
  let dayBtn = page.locator('#view button.cal-cell.is-full').first();
  if (!(await dayBtn.count())) dayBtn = page.locator('#view button[data-cd]').first();
  await dayBtn.click();
  await page.waitForTimeout(600);
  const dSheet = flat(await page.locator('#sheetBody').innerText().catch(() => ''));
  if (dSheet.indexOf('得分') < 0) bad('[月度统计] 点某天没弹出当天的得分');
  const drRows = await page.locator('#sheet.on .dr-row').count();
  say('   点某一天: 弹出 ' + drRows + ' 项明细');
  if (drRows !== 7) bad('[月度统计] 明细不是七项，是 ' + drRows);
  await page.screenshot({ path: path.join(SHOT, 'dad-cal-day.png') });
  await page.locator('#sheet').click({ position: { x: 5, y: 5 } });
  await page.waitForTimeout(400);

  // 切到另一个孩子，确认打分对象跟着变
  if (await page.locator('#view .kid-switch button').count() > 1) {
    const before = flat(await page.locator('#view .kid-switch button.on').innerText());
    await page.locator('#view .kid-switch button').nth(1).click();
    await page.waitForTimeout(900);
    const after = flat(await page.locator('#view .kid-switch button.on').innerText());
    say('   切孩子打分: ' + before + ' -> ' + after);
    if (before === after) bad('[打分页] 切换孩子后打分对象没变');
  }

  // v17 / v26：心愿这条链在家长端的那一半。
  // 换皮后它从「设置里的弹层」搬成「我的 → 心愿与许愿池」一整屏，
  // 两个孩子各自用头上的胶囊切。挑「有挂起心愿」的那个孩子看，
  // 挂起那一栏才算真被验到。
  await tabTo(page, '我的');
  await page.waitForTimeout(700);
  await clickSel(page, '#view [data-go="wish"]', '我的 → 心愿与许愿池');
  const wishPage = flat(await page.locator('#view').innerText());
  if (wishPage.indexOf('许愿池') < 0) bad('[v17] 心愿页没有「全家许愿池」那一块');
  let pendSeen = 0;
  for (const nm of ['女儿', '儿子']) {
    const btn = page.locator('#view .kid-switch button').filter({ hasText: nm }).first();
    if (!(await btn.count())) { bad('[v17] 心愿页没有切到「' + nm + '」的入口'); continue; }
    await btn.click();
    await page.waitForTimeout(1000);
    const body = flat(await page.locator('#view').innerText());
    const progs = await page.locator('#view .bar').count();
    const wishN = await page.locator('#view [data-wish]').count();
    const cfg = await page.locator('#view button[data-td="wcfg"]').count();
    say('   心愿 · ' + nm + ': 心愿 ' + wishN + ' 条（进度条 ' + progs + ' 条）, 待定条件 ' + cfg + ' 条');
    // 空状态只在一条心愿都没有时出现。有进行中的、只是没人挂起，不算空
    // （这里原先只看「有没有待定条件」，儿子那 4 条进行中的心愿也被判成空）。
    if (!cfg && !wishN && body.indexOf('还没有许下的愿') < 0) {
      bad('[v17] ' + nm + ' 一条心愿都没有时没给出空状态说明');
    }
    if (cfg) {
      pendSeen += cfg;
      if (body.indexOf('挂着等定条件') < 0) bad('[v17] 有挂起心愿却没标出「等你定条件」');
      if (await page.locator('#view button[data-td="wcfg"]').count() !== cfg) {
        bad('[v17] 「定条件」按钮数和挂起心愿数对不上');
      }
    }
    // v26：两个孩子各担一种新条件的展示，在这一层一次看全。
    //  · 女儿：多选条件（勾四条、要凑两条，里面有星尘和自己写的一条）
    //  · 儿子：自己写一条（系统算不了，那句话就是条件本身，没有进度条）
    if (nm === '女儿') {
      if (body.indexOf('多选') < 0) bad('[v26] 女儿的心愿里看不到多选条件');
      if (!/其中做到\d+条就得|其中做到\d+条就算/.test(body)) {
        bad('[v26] 多选条件没写出「要凑够几条」');
      }
      if (body.indexOf('星尘自付') < 0) {
        bad('[v26] 多选条件的条件行里没把勾的那几条写全');
      }
      const multi = page.locator('#view [data-wish]').filter({ hasText: '星尘自付' }).first();
      if (!(await multi.count())) {
        bad('[v26] 女儿那条多选心愿没在列表里');
      } else {
        await multi.click();
        await page.waitForTimeout(1000);
        const det = flat(await page.locator('#view').innerText());
        if (det.indexOf('条件原话') < 0) bad('[v26] 心愿详情没有「条件原话」');
        if (!/做到\d+条÷要\d+条/.test(det)) {
          bad('[v26] 详情里没写「做到几条 ÷ 要几条」：' + det.slice(0, 80));
        }
        if (det.indexOf('星尘自付') < 0) bad('[v26] 详情里没列全勾了的那几条');
        if (det.indexOf('靠人判') < 0) bad('[v26] 自己写的那条没标「靠人判」');
        if (det.indexOf('别忘了') < 0) bad('[v26] 心愿详情底部没有「别忘了」');
        await page.screenshot({ path: path.join(SHOT, 'dad-wish-multi.png'), fullPage: true });
        await page.locator('#view [data-back]').first().click();
        await page.waitForTimeout(900);
      }
    }
    if (nm === '儿子') {
      const self = page.locator('#view [data-wish]').filter({ hasText: '夏洛的网' }).first();
      if (!(await self.count())) {
        bad('[v26] 儿子那条「自己写一条」的心愿没在列表里');
      } else {
        await self.click();
        await page.waitForTimeout(1000);
        const det = flat(await page.locator('#view').innerText());
        if (det.indexOf('读完整本，讲给我听一遍') < 0) {
          bad('[v26] 「自己写一条」那句原话没显示出来');
        }
        if (det.indexOf('靠人判') < 0) bad('[v26] 自己写的那条没标「靠人判」');
        if (await page.locator('#view .bar').count()) {
          bad('[v26] 「自己写一条」不该画进度条（系统算不了它）');
        }
        // v29：孩子按条交上来的那一条，家长在这一屏能确认或说不算
        const cOk = await page.locator('#view button[data-wclaim-ok]').count();
        const cNo = await page.locator('#view button[data-wclaim-no]').count();
        say('   儿子交的那条: 确认 ' + cOk + ' / 不算 ' + cNo);
        if (cOk !== cNo) bad('[v29] 心愿详情的确认/不算按钮对不上：' + cOk + ' vs ' + cNo);
        await page.screenshot({ path: path.join(SHOT, 'dad-wish-self.png'), fullPage: true });
        await page.locator('#view [data-back]').first().click();
        await page.waitForTimeout(900);
      }
    }
  }
  if (!pendSeen) bad('[v17] 演示库里没有挂起的心愿，这条路径没被验到');
  await page.screenshot({ path: path.join(SHOT, 'dad-wish-list.png'), fullPage: true });

  // 家长端快捷弹层：换皮后它们收在「我的 → 设置」那一行里的小清单。
  say('');
  say('6. 家长端快捷弹层:');
  await tabTo(page, '我的');
  await page.waitForTimeout(700);
  await clickSel(page, '#view [data-act="more"]', '我的 → 设置');
  // 先只把入口名字抄下来。别存 ElementHandle —— 每开一次弹层，弹层内的
  // 节点都会重画一遍，上一轮的句柄会变成「已脱离文档」，下一轮读它的
  // innerText 就一直等到超时。
  const labels = (await page.locator('#sheetBody [data-qa]').allInnerTexts())
    .map(t => flat(t).slice(0, 16));
  say('   设置小清单: ' + labels.length + ' 个入口');
  if (labels.length < 8) bad('[快捷入口] 家长端「设置」里的入口太少：' + labels.length);
  // 上面这一次已经把小清单开着了，先关掉：循环里每一轮自己重开，
  // 不然第一轮去点「我的 → 设置」时会被还开着的弹层挡住。
  await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
  await page.waitForTimeout(320);
  for (let i = 0; i < labels.length; i++) {
    const label = labels[i];
    if (!label) continue;
    // 每点一次都要重新开小清单：点开一个入口会把它自己关掉
    await clickSel(page, '#view [data-act="more"]', '我的 → 设置');
    const rows = page.locator('#sheetBody [data-qa]');
    if (i >= await rows.count()) break;
    await rows.nth(i).click();
    await page.waitForTimeout(800);
    const on = await page.locator('#sheet.on').count();
    if (!on) { bad('[未弹出] 设置小清单 ' + label); continue; }
    const body = flat(await page.locator('#sheet.on .sheet-body').innerText());
    say('   [弹层] ' + label + ' -> ' + body.length + ' 字: ' + body.slice(0, 56));
    if (body.length < 4) bad('[空弹层] 设置小清单 ' + label);
    await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(300);
  }

  // ---------- 汇总 ----------
  say('');
  say('=== 报错汇总 ===');
  if (!errors.length) say('  0 条报错');
  else errors.forEach(e => say('  ' + e));
  say('截图目录: ' + SHOT);

  await browser.close();
  process.exit(errors.length ? 1 : 0);
})().catch(e => { console.log('脚本自身失败: ' + e.stack); process.exit(2); });
