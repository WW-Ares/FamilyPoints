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

/* ------------------------------------------------ v1.8：弹窗滚动锁 / 底栏铺到底 */

/* 弹窗开着的时候，手指划在遮罩上不该带着下面那一层一起滚 —— v1.8 需求 5，
   而且是全站弹窗一个毛病（所有弹层都走 #sheet，所以修一次全站受益）。
   合成 touchmove / wheel 各一次，dispatchEvent 返回 false 就是被
   preventDefault 拦下了，这里记成「放行 = 没拦住」。

   拦过头一样是坏：弹窗自己滚不动，等于把一个坏修成了另一个坏。所以顺手在
   弹窗**里面**也试一次 —— 内容够长能滚就必须放行，内容没超屏就必须拦住。
   这两条一起，才把「外面拦死、里面照滚」这半句钉住。 */
async function sheetLock(page, tag) {
  const r = await page.evaluate(() => {
    const fire = (el, t) => el.dispatchEvent(t === 'touchmove'
      ? new TouchEvent('touchmove', { cancelable: true, bubbles: true })
      : new WheelEvent('wheel', { cancelable: true, bubbles: true, deltaY: 60 }));
    const sht = document.getElementById('sheet');
    const body = document.querySelector('#sheetBody');
    if (!sht || !body) return null;
    const scrolls = body.scrollHeight > body.clientHeight + 1;
    return {
      onMask: !!(fire(sht, 'touchmove') || fire(sht, 'wheel')),
      inBody: !!(fire(body, 'touchmove') || fire(body, 'wheel')),
      scrolls: scrolls,
      over: getComputedStyle(sht).overscrollBehaviorY,
      h: Math.round(body.getBoundingClientRect().height),
    };
  });
  if (!r) { bad('[' + tag + '] 弹窗没开着，滚动锁验不了'); return; }
  say('   [弹窗锁] ' + tag + ': 遮罩放行=' + r.onMask + ' 内部放行=' + r.inBody +
      '（内容' + (r.scrolls ? '可滚' : '不滚') + '，高 ' + r.h + 'px）overscroll=' + r.over);
  if (r.onMask) {
    bad('[v1.8] ' + tag + '：遮罩上的滑动没拦住，会带着下面那一层一起滚');
  }
  if (r.scrolls && !r.inBody) bad('[v1.8] ' + tag + '：弹窗里能滚的内容被一并拦死了');
  if (!r.scrolls && r.inBody) {
    bad('[v1.8] ' + tag + '：这条弹窗内容没超屏，在里面划动却放行了（会带动下面那层）');
  }
  if (!/contain|none/.test(r.over)) {
    bad('[v1.8] ' + tag + '：弹窗没设 overscroll-behavior，iOS 上手势会传给下面那层');
  }
}

/* v1.8 需求 7：底栏自己上层底色铺到屏幕底。
   原来 #tabs 是透明的，里面那颗胶囊离屏幕底还差一截（padding-bottom 里那
   34px 安全区 + 12px），真机量到胶囊下沿离屏幕底 47px 空在那里，就是
   「底下空了一片没铺满」。现在底色归壳子自己画，一直铺到屏幕底、只留上面
   两个圆角；胶囊那层皮去掉，导航项位置一点不动。
   所以查的是：壳子有底色、没有上边框、上面有圆角下面没有、下沿压在屏幕底、
   胶囊自己不再画一层。 */
async function barToBottom(page, tag) {
  const r = await page.evaluate(() => {
    const t = document.getElementById('tabs');
    // 不能用 offsetParent 判在不在：#tabs 是 position:fixed，offsetParent 恒为 null
    if (!t || t.getBoundingClientRect().height < 1) return null;
    const cs = getComputedStyle(t), b = t.getBoundingClientRect();
    const pill = t.querySelector('.nav-pill, .tabbar-pill');
    return { bg: cs.backgroundColor, bt: cs.borderTopWidth,
      rTL: cs.borderTopLeftRadius, rBL: cs.borderBottomLeftRadius,
      bottom: Math.round(b.bottom), vh: window.innerHeight,
      pillBg: pill ? getComputedStyle(pill).backgroundColor : '' };
  });
  if (!r) { bad('[' + tag + '] 底栏不在，铺没铺到底验不了'); return; }
  say('   [底栏] ' + tag + ': 底色 ' + r.bg + ' / 上边 ' + r.bt + ' / 圆角上 ' + r.rTL +
      ' 下 ' + r.rBL + ' / 下沿 ' + r.bottom + ' of ' + r.vh + ' / 胶囊 ' + (r.pillBg || '无'));
  if (r.bg === 'rgba(0, 0, 0, 0)') bad('[v1.8] ' + tag + '：底栏是透明的，底下还空着一截');
  if (r.bt !== '0px') bad('[v1.8] ' + tag + '：底栏上面还压着一道 ' + r.bt + ' 的线');
  if (parseFloat(r.rTL) < 8) bad('[v1.8] ' + tag + '：底栏上面两个圆角只有 ' + r.rTL);
  if (parseFloat(r.rBL) > 1) bad('[v1.8] ' + tag + '：底栏底下不该有圆角（' + r.rBL + '）');
  if (Math.abs(r.bottom - r.vh) > 1) {
    bad('[v1.8] ' + tag + '：底栏下沿在 ' + r.bottom + '，屏幕底是 ' + r.vh + '，中间还空着');
  }
  if (r.pillBg && r.pillBg !== 'rgba(0, 0, 0, 0)') {
    bad('[v1.8] ' + tag + '：胶囊自己还带一层底色（' + r.pillBg + '），两层皮会显出接缝');
  }
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
  /* ---------- 先查三条「Chrome 里量不出来」的静态规矩 ----------
     这三条都只在 iOS 真机上现，本机 Chrome 一样都验不了：
       · env(safe-area-inset-*) 在 Chrome 里恒为 0，安全区那 34px 根本不存在；
       · auto-zoom 是 WKWebView 自己的行为，Chrome 聚焦输入框不放大；
       · 状态栏那一整条是 iOS 拿 theme-color 画的，Chrome 没这条带子。
     所以只能对源码本身查。三条都是拿真机截图按像素量出来的，别再改回去。 */
  (function staticRules() {
    const WEB = path.join(__dirname, '..', 'web');
    const read = f => fs.readFileSync(path.join(WEB, f), 'utf8');
    // 同一个选择器可能出现多次（横屏那条在 @media 里），每一条都要查
    const blocks = (css, sel) => {
      const out = [];
      for (let i = css.indexOf(sel + ' {', 0); i >= 0; i = css.indexOf(sel + ' {', i + 1)) {
        out.push(css.slice(i, css.indexOf('}', i) + 1));
      }
      return out;
    };

    // ① 底栏高度里不许含安全区
    for (const [f, sel] of [['parent.css', 'body.grown #tabs'],
                            ['child.css', 'body.kid #tabs']]) {
      const bs = blocks(read(f), sel);
      if (!bs.length) { bad('[底栏] ' + f + ' 里找不到 ' + sel); continue; }
      bs.forEach((b, i) => {
        if (/safe-area-inset-bottom/.test(b)) {
          bad('[底栏] ' + f + ' 的 ' + sel + '（第 ' + (i + 1) + ' 条）又含安全区了 → ' +
            'iOS 上会比安卓高 34px，货架被拉长、胶囊浮在离屏幕底 47px 的地方');
        }
      });
    }

    // ② theme-color 三处同值，且必须等于页面顶部那档 --bg-top
    const g = (s, re) => (s.match(re) || [])[1];
    const top = g(read('parent-tokens.css'), /--bg-top:\s*(#[0-9A-Fa-f]{6})/);
    const meta = g(read('index.html'), /name="theme-color" content="(#[0-9A-Fa-f]{6})"/);
    const run = g(read('app.js'), /setAttribute\('content', '(#[0-9A-Fa-f]{6})'\)/);
    const man = g(read('site.webmanifest'), /"theme_color":\s*"(#[0-9A-Fa-f]{6})"/);
    say('   [theme-color] --bg-top ' + top + ' / meta ' + meta + ' / 启动时 ' + run +
      ' / manifest ' + man);
    if (!top || top !== meta || meta !== run || meta !== man) {
      bad('[theme-color] 四处不一致（--bg-top ' + top + ' / meta ' + meta + ' / 启动时 ' +
        run + ' / manifest ' + man + '）：iOS 拿这个值画状态栏那 59px，' +
        '不一致就是顶部横着一条跟页面对不上的色带');
    }

    // ③ iOS 输入框字号兜底：聚焦时算出来的字号 < 16px，WKWebView 会把整页放大
    if (!/input[\s\S]{0,300}?textarea\s*\{\s*font-size:\s*16px\s*!important/.test(read('style.css'))) {
      bad('[iOS] style.css 里那条「输入框字号不低于 16px」的兜底没了 —— ' +
        '搜索框一聚焦就会把整页放大，键盘收起也不还原');
    }
  })();

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
     任务大厅 / 券商店 / 成长报告 / 心愿屋 / 图鉴 / 家庭
     变成压在底栏之上的二级页，靠 hash 进、靠返回键退。
     （「我的记录」原来也在这一串里，v13 整屏撤了：任务记录挪去任务页底部，
     月度成绩并进成长报告底部的月历。）

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
  await barToBottom(page, '孩子端底栏');
  /* v40：「有事就说」那两条从「我的」搬走 —— 申请加时挪到券包（它延长的就是
     下面那张券），「遇到困难」挪到首页（写作业的时候开的就是这一屏）。
     原来两块叠在「我的」最下面，要翻两屏才找得到，等于把唯一的正经通道埋起来。 */
  if (kidView.home.indexOf('遇到困难') < 0) bad('[v41] 首页没有「遇到困难」');
  if (kidView.coupon.indexOf('想多玩一会儿') < 0) bad('[v41] 券包没有「想多玩一会儿」');
  if (kidView.mine.indexOf('想多玩一会儿') >= 0 || kidView.mine.indexOf('遇到困难') >= 0) {
    bad('[v41] 「我的」里还留着那两条入口');
  }
  await kidGo('home');
  if (!(await page.locator('#view #kAskHelp').count())) bad('[v40] 首页的「说一声」按钮不在');
  await kidGo('coupon');
  if (!(await page.locator('#view #kAskOt').count())) bad('[v40] 券包的「申请加时」按钮不在');

  /* v40：二级页返回要回「从哪进的」，不能写死一个目标。
     原来成长报告的返回写死 data-go="home"，于是「我的 → 成长报告 → 返回」
     掉回首页。这里两条路各走一遍：从我的进去退回我的，从首页进去退回首页。
     必须真点入口进去 —— kidGo 直接改 location.hash，来路是空的。 */
  for (const [from, mark] of [['mine', '头像与皮肤'], ['home', '本周获得']]) {
    await kidGo(from);
    await clickSel(page, '#view [data-go="report"]', from + ' → 成长报告');
    const inRep = await kidText();
    if (inRep.indexOf('成长报告') < 0) bad('[v40] 从「' + from + '」点不进成长报告');
    await clickSel(page, '#view .appbar-back', '成长报告 返回');
    const backTxt = await kidText();
    if (backTxt.indexOf(mark) < 0) {
      bad('[v40] 从「' + from + '」进成长报告，返回没回到「' + from + '」：' + backTxt.slice(0, 40));
    }
  }

  // 首页：今天几分、多少星尘、这一周的七分、要做的事
  await kidGo('home');
  const kHome = kidView.home;
  for (const want of ['要做的事', '星尘']) {
    if (kHome.indexOf(want) < 0) bad('[v39] 首页缺少「' + want + '」');
  }
  /* v1.8：七分卡抬头从「这一周的七分」换成一句账 —— 本周获得 X 能量，丢失 N 能量。
     抬头这两个数跟矩阵同一份数算出来，不另起一套，免得出现「图上有 20 格、
     标题写 21 分」，所以这里把格子和标题对一遍。
     行尾单位也从「天」改成「分」：一格就是一分，写「天」会让人以为按天算。
     右上角那两个图例字（灰色 = 还没到 / 橙框 = 今天）一并撤了。 */
  /* 核对不拿七行行尾相加 —— 那还是同一套数在自说自话。这里数图上**亮了几格**，
     格子和抬头两条路各算一遍，对不上就是有一边算错了。 */
  const k7 = await page.evaluate(() => {
    const t = document.querySelector('#view .k7-title');
    const days = Array.from(document.querySelectorAll('#view .k7-row:not(.k7-cols) .k7-day'));
    return {
      title: t ? t.innerText.replace(/\s+/g, '') : '',
      legend: !!document.querySelector('#view .k7-legend'),
      units: days.map(d => d.innerText.replace(/\s+/g, '')),
      lit: document.querySelectorAll('#view .k7-c.is-on').length,
    };
  });
  say('   七分卡抬头: ' + (k7.title || '（没有）') + ' | 图上亮 ' + k7.lit +
      ' 格 | 行尾 ' + k7.units.join(' '));
  if (!/^本周获得\d+能量，丢失\d+能量$/.test(k7.title)) {
    bad('[v1.8] 七分卡抬头不是「本周获得 X 能量，丢失 N 能量」：' + k7.title);
  }
  if (k7.legend) bad('[v1.8] 七分卡右上角那两个图例字没撤掉');
  if (k7.units.length !== 7) bad('[v1.8] 七分卡不是 7 行，是 ' + k7.units.length);
  if (k7.units.some(u => !/分$/.test(u))) {
    bad('[v1.8] 七分卡行尾单位不是「分」：' + k7.units.join(' '));
  }
  const gotTxt = +(k7.title.match(/本周获得(\d+)能量/) || [])[1];
  if (k7.title && gotTxt !== k7.lit) {
    bad('[v1.8] 抬头「获得 ' + gotTxt + '」和图上亮起的格子数（' + k7.lit + '）对不上');
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
  /* v13：任务页底部摆「任务记录」—— 最近 3 条 + 一个「展开全部」，回溯近一个月。
     原来那儿只有一行小灰字「看看我的全部记录 ›」，跳去的是「我的记录」，
     那页讲「哪一项这几天怎么走的」，跟任务没关系：孩子想问「我那件活后来怎么了」
     反而没地方去。这里要真点一次「展开全部」—— 上一版的教训就是
     「界面在、按钮在、点了没动静」，只看文字不看反应是查不出来的。 */
  const histRows = await page.locator('#view .ktrec').count();
  say('   任务记录（页内）: ' + histRows + ' 行');
  if (taskTxt.indexOf('任务记录') < 0) bad('[v13] 任务页底部没有「任务记录」那段');
  if (!histRows) bad('[v13] 任务记录一段没内容');
  if (histRows > 3) bad('[v13] 任务记录页内摆了 ' + histRows + ' 行，默认该只摆 3 条');
  if (taskTxt.indexOf('看看我的全部记录') >= 0) {
    bad('[v13] 任务页还留着「看看我的全部记录」那行小字');
  }
  const moreBtn = page.locator('#view #kHistMore');
  if (!(await moreBtn.count())) {
    bad('[v13] 任务页没有「展开全部」按钮（演示库里近一个月有 7 条记录）');
  } else {
    const moreLabel = flat(await moreBtn.first().innerText());
    await moreBtn.first().click();
    await page.waitForTimeout(800);
    const sheetTxt = flat(await page.locator('#sheetBody').innerText());
    const sheetRows = await page.locator('#sheetBody .ktrec').count();
    say('   展开全部: ' + moreLabel + ' -> ' + sheetRows + ' 行 / ' + sheetTxt.slice(0, 30));
    if (sheetRows <= histRows) {
      bad('[v13] 点了「展开全部」，展开出来还是 ' + sheetRows + ' 行，不比页内的多');
    }
    if (sheetTxt.indexOf('近一个月') < 0) bad('[v13] 展开列表没说回溯范围是近一个月');
    // 放下和退回也要列出来：只报成功的记录等于没记
    if (!/已放弃|被退回/.test(sheetTxt)) {
      bad('[v13] 展开列表里看不到「已放弃 / 被退回」，旧状态被筛掉了');
    }
    await page.evaluate(() => document.querySelector('#sheet').classList.remove('on'));
    await page.waitForTimeout(250);
  }
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
  /* v1.7：七档的图从雪碧图换成图库那套 bx_*（和家长「给它们换张图」里
     能挑的是同一批），所以这里认的是 icons/<token>.svg 的地址。
     七张必须各不相同 —— 全家长得一个样，这一档和那一档就分不出来了。 */
  const srcs = await page.evaluate(() => Array.from(
    document.querySelectorAll('#view .btcol img')).map(u => u.getAttribute('src')));
  say('   七档图: ' + srcs.join(' '));
  if (srcs.length !== 7) bad('[v1.7] 七档的图不是 7 张，是 ' + srcs.length);
  if (srcs.some(s => !/^icons\/bx_/.test(s || ''))) {
    bad('[v1.7] 七档有哪一列没用图库那批宝箱图：' + srcs.join(' '));
  }
  if (new Set(srcs).size !== srcs.length) bad('[v1.7] 七档宝箱的图有重复：' + srcs.join(' '));
  for (const nm of ['木箱', '铜箱', '银箱', '金箱', '钻石箱', '王者箱', '完美箱']) {
    if (chest.indexOf(nm) < 0) bad('[v31] 宝箱页没出现「' + nm + '」');
  }
  /* v1.7：列里的「X 券 + N 卡」两行搬走了，概率那句紫色小字也撤了 ——
     它们进了新建的「查看宝箱详情」那一屏。这儿留七份数字谁也记不住，
     那儿每一档有整行位置慢慢说。所以这里反着查：写了就是没搬干净。 */
  const colTxt = await page.evaluate(() => Array.from(
    document.querySelectorAll('#view .btcol')).map(c => c.innerText.replace(/\s+/g, ' ')));
  say('   七档内容: ' + colTxt.join(' | '));
  if (colTxt.filter(t => /券|张卡/.test(t)).length) bad('[v1.7] 七列里还写着「券 / 卡」那两行');
  if (chest.indexOf('随机掉稀有道具') >= 0) bad('[v1.7] 宝箱页没撤掉概率那句小字');
  if (chest.indexOf('箱子里有什么，点开那一刻才抽') >= 0) {
    bad('[v39] 宝箱页还留着上一条卡尾文案');
  }
  /* 一条到底的总进度：七列下面那条横线。
     原来每列各自一条短进度，讲的是同一个进度切成七段，反而看不出离下一档多远。

     v1.8：这条线原来是「能量 ÷ 49」一条通铺直线 —— 7 分就窜进第二格、15 分跑到
     第三格，跟上面七个箱子对不上。现在按「每档 7 分」逐格填，所以这里量的不是
     百分比（现在写成 calc()，parseFloat 读出来是 NaN），是**条头压在第几格、
     格里走了几分之几**，拿七列的真实位置对一遍：
       i = floor(能量 ÷ 7) − 1   站在第几格（0 起，0–7 分时是 −1 = 还没进第一格）
       r = 能量 − 7 × (i + 1)    这一格里填了几分之几 */
  const barGeo = await page.evaluate(() => {
    const bar = document.querySelector('#view .chest-bar');
    const cols = Array.from(document.querySelectorAll('#view .btcol'));
    if (!bar || cols.length !== 7) return null;
    const f = bar.querySelector('.chest-bar-f');
    const r = cols.map(c => c.getBoundingClientRect());
    const fr = f.getBoundingClientRect();
    return { track: bar.getBoundingClientRect().width, fill: fr.width,
             colW: r[0].width, pitch: r[1].left - r[0].left, base: r[0].left,
             head: fr.right,
             e: Number(bar.getAttribute('aria-valuenow')),
             max: Number(bar.getAttribute('aria-valuemax')) };
  });
  if (!barGeo) bad('[v1.7] 七档下面没有那条总进度线，或者七列不是 7 个');
  else {
    const e = barGeo.e, max = barGeo.max;
    const i = Math.floor(e / 7) - 1;
    const r = e - 7 * (i + 1);
    const want = e >= max ? barGeo.base + barGeo.track - 1        // 整条填满
      : i < 0 ? barGeo.base + 1                                   // 空的，条头贴左沿
        : barGeo.base + i * barGeo.pitch + (r / 7) * barGeo.colW;
    const off = barGeo.head - want;
    say('   总进度线: 能量 ' + e + '/' + max + '，条头 ' + Math.round(barGeo.head) +
      'px，第 ' + (i + 1) + ' 格走 ' + r + '/7（该在 ' + Math.round(want) +
      'px，差 ' + off.toFixed(1) + 'px）');
    if (!(Number.isFinite(off)) || Math.abs(off) > 2) {
      bad('[v1.8] 进度条条头没落在第 ' + (i + 1) + ' 格里（差 ' + off.toFixed(1) + 'px）');
    }
    if (e < 8 && barGeo.fill > 2) {
      bad('[v1.8] 不到 8 分条子就该是空的，现在填了 ' + Math.round(barGeo.fill) + 'px');
    }
    if (e > 7 && e < max && !(barGeo.fill > 4)) {
      bad('[v1.8] 总进度线没有填起来（' + Math.round(barGeo.fill) + 'px）');
    }
    if (e >= max && Math.abs(barGeo.fill - barGeo.track) > 3) {
      bad('[v1.8] 满档该整条填满，现在只填了 ' + Math.round(barGeo.fill) + '/' + Math.round(barGeo.track));
    }
  }
  if (await page.locator('#view .chest-bar.chest-slots').count()) {
    bad('[v1.7] 还留着旧的那条七格分段进度');
  }
  const buyBoxes = await page.locator('#view button[data-box]').count();
  say('   星尘直接买: ' + buyBoxes + ' 档');
  if (buyBoxes !== 3) bad('[v31] 星尘直接买不是三档，是 ' + buyBoxes);
  if (await page.locator('#view button[data-buy]').count()) bad('[v31] 宝箱栏还在卖箱子');
  /* v1.7：这三格改成竖排（箱图 / 名 / 价），跟设计稿一致。
     原来是横排「图 + 名/价」，价格那一行只剩七十来像素，「105 星尘」的
     「星尘」被折成上下两行 —— 所以这里量的是「有没有折行 / 有没有撑爆」，
     光查文字在不在是查不出这个的。 */
  const buy = await page.evaluate(() => Array.from(
    document.querySelectorAll('#view .card--buy')).map(el => {
      const p = el.querySelector('.cb-p');
      return { txt: p ? p.innerText.replace(/\s+/g, ' ') : '',
               lines: p ? p.getClientRects().length : 0,
               over: el.scrollWidth - el.clientWidth,
               ph: el.getBoundingClientRect().height };
    }));
  say('   直接买三格: ' + buy.map(b => b.txt + '(' + Math.round(b.ph) + 'px)').join(' | '));
  if (buy.some(b => !/星尘$/.test(b.txt))) bad('[v1.7] 直购格的价钱没写成「N 星尘」');
  if (buy.some(b => b.lines > 1)) bad('[v1.7] 直购格的价钱折成了两行');
  if (buy.some(b => b.over > 1)) bad('[v1.7] 直购格撑爆了 ' + Math.max(...buy.map(b => b.over)) + 'px');
  if (buy.length && new Set(buy.map(b => Math.round(b.ph))).size !== 1) {
    bad('[v1.7] 直购三格高矮不一：' + buy.map(b => Math.round(b.ph)).join('/'));
  }

  /* v38：结算只发一只箱子，箱子里有什么点开那一刻才抽。
     演示库给女儿留了一只没点开的箱，这里把它走完整条路：
     提醒条 → 点箱子 → 四拍动画 → 结果屏 → 提醒条消失。
     提醒条只是提醒，开箱入口在 hero 卡上那只箱子本身（原来那「点我打开」
     按钮撤了：提醒在上、箱子在下，孩子得先看懂「上面那条」指的是什么）。 */
  const alert = page.locator('#view .chest-pod');
  const fig = page.locator('#view button.box-figure');
  if (!(await alert.count())) {
    bad('[v38] 宝箱页没有「有箱子可以开」的提醒条（演示库留了一只待开箱）');
  } else if (!(await fig.count())) {
    bad('[宝箱] 有待开箱，但 hero 卡上那只箱子不是开箱键（应为 button.box-figure）');
  } else {
    if (await page.locator('#view button.chest-pod').count()) {
      bad('[宝箱] 提醒条又成了按钮：开箱入口只该有 hero 卡上那只箱子一个');
    }
    say('   待开箱提醒: ' + flat(await alert.innerText()).slice(0, 50));
    await fig.click();
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
      bad('[v38] 箱子已经开过了，提醒条还挂着');
    }
  }
  await page.screenshot({ path: path.join(SHOT, 'kid-chest.png'), fullPage: true });

  /* v1.7：七列右上角那条「查看宝箱详情 ›」—— 每一档必定给什么、还有多大机会
     多掉一件，都在这一屏展开写。原来这些塞在七列底下，46px 宽的列装不下
     「70% 出什么」这半句话，于是只写了个百分比，等于没说。
     二级页要点进来、内容齐、并且能退回宝箱页（来路是宝箱页，不是首页）。 */
  const linkCnt = await page.locator('#view .card-link[data-go="boxinfo"]').count();
  if (linkCnt !== 1) bad('[v1.7] 七档右上没有「查看宝箱详情」那条链（' + linkCnt + ' 个）');
  else {
    await clickSel(page, '#view .card-link[data-go="boxinfo"]', '宝箱 → 宝箱详情');
    await page.waitForTimeout(700);
    const info = flat(await page.locator('#view').innerText());
    say('   宝箱详情: ' + info.slice(0, 90));
    if (info.indexOf('必定拿到') < 0) bad('[v1.7] 详情页没有「必定拿到」那一列');
    if (info.indexOf('还有机会多掉一件') < 0) bad('[v1.7] 详情页没有随机件那一列');
    for (const nm of ['木箱', '钻石箱', '完美箱']) {
      if (info.indexOf(nm) < 0) bad('[v1.7] 详情页少了「' + nm + '」');
    }
    // 木铜银没有随机件，那一格要明写「无随机件」——留白会被读成「忘了填」
    const infoRows = await page.locator('#view .bxif-r').count();
    const noneCnt = await page.locator('#view .bxif-none').count();
    const rateCells = (await page.locator('#view .bxif-rate').allInnerTexts()).map(flat);
    say('   详情页: ' + infoRows + ' 行；无随机件 ' + noneCnt + ' 档；概率 ' + rateCells.join(' '));
    if (infoRows !== 7) bad('[v1.7] 详情页不是七行，是 ' + infoRows);
    if (noneCnt + rateCells.length !== 7) bad('[v1.7] 随机件那一列有空档');
    if (rateCells.map(x => x.replace('概率', '')).join('') !== '10%20%40%70%') {
      bad('[v1.7] 随机件概率不是 10/20/40/70：' + rateCells.join(' '));
    }
    if (rateCells.some(x => x.indexOf('概率') < 0)) {
      bad('[v1.7] 概率胶囊没写「概率」两个字：' + rateCells.join(' '));
    }
    /* v1.7 文案照设计稿那张总表逐字对：券在前、卡在后（「娱乐券 8 张」
       不是「8 张娱乐券」），每张卡各占一行（不是拿「·」串成一行 ——
       串起来读着像「给三张」，其实是一行一件）。
       这几条都得看原样的空白：flat() 会把所有空白抹平，一旦抹平，
       「各占一行」和「用 / 分隔」这两条就永远成立，等于没查。 */
    const sq = s => String(s || '').replace(/\s+/g, ' ').trim();
    const mustTxt = (await page.locator('#view .bxif-must').allInnerTexts()).map(sq);
    say('   必得列: ' + mustTxt.join(' | '));
    if (/\d+ 张娱乐券/.test(mustTxt.join(' '))) {
      bad('[v1.7] 必得列还写着「N 张娱乐券」，设计稿是「娱乐券 N 张」');
    }
    if (mustTxt.filter(x => x.indexOf('娱乐券') < 0).length) {
      bad('[v1.7] 必得列有哪一档没写娱乐券');
    }
    const pk = (await page.locator('#view .bxif-must').allInnerTexts())[6] || '';
    if (pk.split('\n').filter(x => /卡 \d+ 张/.test(sq(x))).length !== 3) {
      bad('[v1.7] 完美箱那三张卡没各占一行：' + JSON.stringify(pk));
    }
    /* v1.8：这句从「另有 10% 机会出钻石级卡」改成「有10%概率出钻石级卡」。
       原来那句把「概率」说成「机会」，还说成是「另有」一件东西，
       读起来像多送一件，其实它就是随机件那一栏的中奖率。 */
    const poolRaw = (await page.locator('#view .bxif-pool').allInnerTexts()).map(sq);
    const poolTxt = poolRaw.join(' ');
    say('   随机列: ' + poolTxt.slice(0, 100));
    if (poolTxt.indexOf(' / ') < 0) bad('[v1.7] 随机件那一列没用「 / 」分隔');
    if (poolTxt.indexOf('有10%概率出钻石级卡') < 0) {
      bad('[v1.8] 完美箱少那一句「有10%概率出钻石级卡」：' + JSON.stringify(poolRaw.slice(-2)));
    }
    if (poolTxt.indexOf('另有 10% 机会') >= 0) {
      bad('[v1.8] 完美箱还留着旧文案「另有 10% 机会出钻石级卡」');
    }
    // 详情页的箱图跟着家长换的那张走，默认就是设计稿那七只扁平箱
    const iSrcs = await page.evaluate(() => Array.from(
      document.querySelectorAll('#view .bxif-tier img')).map(u => u.getAttribute('src')));
    say('   详情页图: ' + iSrcs.join(' '));
    if (iSrcs.length !== 7) bad('[v1.7] 详情页的箱图不是 7 张，是 ' + iSrcs.length);
    if (iSrcs.join() !== srcs.join()) {
      bad('[v1.7] 详情页的箱图和宝箱页那七张对不上：' + iSrcs.join(' '));
    }
    /* 老那七只（带圆底那版）留在图库当备选 —— 家长在「给它们换张图」里
       还挑得到，不然「老的留着」这句话只落在仓库里，落不到界面上。 */
    const libBox = await page.evaluate(() => (window.ICONS || [])
      .filter(i => i.t.indexOf('bx') === 0).map(i => i.t));
    say('   图库里的箱子: ' + libBox.join(' '));
    if (libBox.filter(t => t.indexOf('bxold_') === 0).length !== 7) {
      bad('[v1.7] 图库里找不到旧那七只宝箱图：' + libBox.join(' '));
    }
    const backTo = await page.locator('#view .appbar-back').getAttribute('data-go');
    if (backTo !== 'chest') bad('[v1.7] 详情页返回不去宝箱页，去的是「' + backTo + '」');
    await page.screenshot({ path: path.join(SHOT, 'kid-boxinfo.png'), fullPage: true });
    await clickSel(page, '#view .appbar-back', '宝箱详情 → 返回');
    await page.waitForTimeout(500);
    if (!(await page.locator('#view .btcol').count())) {
      bad('[v1.7] 详情页返回以后没回到宝箱页');
    }
  }

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
  for (const want of ['心愿屋', '图鉴', '成长报告', '家庭', '头像与皮肤']) {
    if (mine.indexOf(want) < 0) bad('[v31] 「我的」里没有「' + want + '」入口');
  }
  /* v1.7：「我的」四行走的顺序是 心愿屋 → 成长报告 → 家庭 → 图鉴。
     图鉴原来是第二位：它回答的是「我收集到什么」，而来这一页的人多半是
     来看自己这个月过得怎么样（成长报告）和家人（家庭）。顺序改了以后
     这里按次序断言一遍 —— 只查「有没有」查不出排错队的那个。 */
  // 按行的 data-go 查顺序，不用正文 indexOf：正文里别处也会提到这几个词，
  // 拿第一次出现的位置排序，排的是「它最早在哪儿提到」而不是「它排在第几行」。
  const mineGo = await page.evaluate(() => Array.from(
    document.querySelectorAll('#view .row[data-go]')).map(r => r.dataset.go));
  say('   「我的」四行: ' + mineGo.slice(0, 4).join(' → '));
  if (mineGo.slice(0, 4).join() !== 'wish,report,family,atlas') {
    bad('[v1.7] 「我的」四行顺序不是 心愿屋→成长报告→家庭→图鉴，是 ' +
        mineGo.slice(0, 4).join('→'));
  }
  if (mine.indexOf('升级进度') < 0) bad('[v31] 「我的」里没有升级进度');
  if (!/Lv\.\d/.test(mine)) bad('[v31] 「我的」里没显示等级');
  /* v38：三宫格第二格从「券在手 · 张」改成「特权道具」，数的是一共多少件
     （券 + 卡）。点它、或者点它上面那个数字，都该去券包。这两格原来只是
     一块不能点的文字。
     第三格「本月完美日」原来点去「我的记录」。那一屏后来整屏撤了 ——
     它讲的是「哪一项这几天怎么走的」，跟「我这个月过得怎么样」不是一回事，
     内容并进了成长报告底部那张月历。所以这一格现在点去成长报告。 */
  if (mine.indexOf('特权道具') < 0) bad('[v38] 「我的」第二格没改成「特权道具」');
  if (mine.indexOf('券在手') >= 0) bad('[v38] 「我的」里还留着「券在手」');
  if (mine.indexOf('我的记录') >= 0) bad('[v13] 「我的」里还留着「我的记录」入口');
  const tapPriv = page.locator('#view .k-tap[data-go="coupon"]');
  const tapPerf = page.locator('#view .k-tap[data-go="report"]');
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
    // 小结标题跟着月份写（9 月小结），不能按「本月小结」找
    if (recTxt.indexOf('月小结') < 0) bad('[v13] 点「本月完美日」没跳到成长报告');
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
    // v1.8：40 张头像铺下来这条弹窗必定超出屏。它代表的是「内容能滚」那一档
    // —— 外面要拦死、里面要放行，两条一起才算修好（见 sheetLock 那条注释）。
    await sheetLock(page, '孩子端换头像');
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

  /* 「我的记录」整屏撤了。它讲的是「哪一项这几天怎么走的」，而孩子真正会问的是
     「我这个月过得怎么样」和「我那件活后来怎么了」—— 前者落在成长报告底部那张
     月历，后者落在任务页底部的任务记录（见下面任务页那一段）。
     所以这里改成验月历：三格小结在、点一格要看得到七项，还得交代这个分怎么来的。 */
  await kidGo('report');
  const cal = await kidText();
  say('   成长报告底部: ' + cal.slice(0, 46));
  // v1.6：月历标题从「9 月打分日历」改成能翻月的「9 月」，小结跟着走成
  // 「9 月小结」。两个标题都随月份变，所以按「月小结」找，另外单独验翻月按钮在。
  for (const want of ['月小结']) {
    if (cal.indexOf(want) < 0) bad('[v13] 成长报告底部缺少「' + want + '」');
  }
  if (!(await page.locator('#view .kcal-mv').count())) {
    bad('[v13] 月历没有翻月的箭头');
  }
  /* v1.8：真机上「‹」和「›」一个圆一个椭圆。根因是这两颗一个是 <button>、
     一个是 <span>，iOS 给 button 套原生外观 + 自带 padding: 1px 6px 撑宽；
     span 老实听 CSS。本机 Chrome 两颗天然一样大，光量几何查不出来，
     所以查的是那两行针对 iOS 的复位到底在不在，几何顺手比一遍。 */
  for (const a of await page.evaluate(() => Array.from(
      document.querySelectorAll('#view .kcal-mv')).map(el => {
        const cs = getComputedStyle(el), r = el.getBoundingClientRect();
        return { tag: (el.tagName || '').toLowerCase(),
          w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
          pad: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].join(' '),
          app: cs.appearance || '' };
      }))) {
    say('   月历箭头: ' + a.tag + ' ' + a.w + '×' + a.h + ' pad="' + a.pad + '" appearance=' + a.app);
    if (a.pad !== '0px 0px 0px 0px') {
      bad('[v1.8] 月历箭头（' + a.tag + '）还带着浏览器自带的 padding：' + a.pad);
    }
    if (!/^none/.test(a.app)) {
      bad('[v1.8] 月历箭头（' + a.tag + '）没关掉原生外观：' + a.app);
    }
    if (Math.abs(a.w - a.h) > 0.6) {
      bad('[v1.8] 月历箭头（' + a.tag + '）不是正圆：' + a.w + '×' + a.h);
    }
  }
  if (cal.indexOf('不是一件事') < 0) bad('[v13] 月历没说清「0 分」和「没打分」不是一回事');
  const kpiCells = await page.locator('#view .kkpi').count();
  say('   本月小结: ' + kpiCells + ' 格');
  if (kpiCells !== 3) bad('[v13] 本月小结不是 3 格，是 ' + kpiCells);
  // 可点的只有打过分的天；未来的日子在 HTML 里是 span，点不开
  const dayBtns = page.locator(
    '#view .kcal-cell[data-kcd].is-full, #view .kcal-cell[data-kcd].is-part,' +
    ' #view .kcal-cell[data-kcd].is-zero');
  const nDays = await dayBtns.count();
  say('   月历可点的天: ' + nDays);
  if (nDays < 5) bad('[v13] 月历里能点的天太少，是 ' + nDays + '（演示库这月打过分十几天）');
  if (nDays) {
    await dayBtns.first().click();
    await page.waitForTimeout(600);
    const ds = flat(await page.locator('#sheetBody').innerText());
    const dRows = await page.locator('#sheetBody .kcal-d').count();
    say('   点一格: ' + dRows + ' 项 / ' + ds.slice(0, 36));
    if (dRows !== 7) bad('[v13] 单日明细不是 7 项，是 ' + dRows);
    if (ds.indexOf('这天拿到') < 0) bad('[v13] 单日明细没写这天拿到几分');
    if (!/这天七项都拿到了|扣的是|备注/.test(ds)) {
      bad('[v13] 单日明细没交代这个分是怎么来的：' + ds.slice(0, 60));
    }
    await page.evaluate(() => document.querySelector('#sheet').classList.remove('on'));
    await page.waitForTimeout(250);
  }
  await page.screenshot({ path: path.join(SHOT, 'kid-report-month.png'), fullPage: true });

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
  await barToBottom(page, '家长端底栏');
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

  /* v40：发布页顶部胶囊从两格变三格 —— 写任务 / 写校准 / 我发出的 N。
     「记一次校准」原来躲在「我的 → 更多」那层弹窗里，比发布深两层；
     「发一个任务」原本也挂在「我的 → 更多」，它能做的两件事（派给某个孩子 +
     给任务配图）现在并进「写任务」，所以那一条整个撤掉。 */
  await tabTo(page, '发布');
  await page.waitForTimeout(700);
  const pubSeg = (await page.locator('#view .seg-item').allInnerTexts()).map(flat);
  say('   发布胶囊: ' + pubSeg.join(' / '));
  if (pubSeg.length !== 3) bad('[v40] 发布胶囊不是 3 格，是 ' + pubSeg.length);
  if (pubSeg[1] !== '写校准') bad('[v40] 发布胶囊第二格不是「写校准」，是「' + pubSeg[1] + '」');
  if (!/^我发出的\s*\d+$/.test(pubSeg[2] || '')) {
    bad('[v40] 第三格没带件数写成「我发出的 N」，是「' + pubSeg[2] + '」');
  }
  await clickSel(page, '#view .seg-item[data-pseg="calib"]', '发布 → 写校准');
  const calibTxt = flat(await page.locator('#view').innerText());
  if (calibTxt.indexOf('怎么处理') < 0) bad('[v40] 「写校准」那一屏没有「怎么处理」');
  // 选孩子从下拉改成按钮（v42）：跟同一屏别的选择题一个样子，一眼看见有谁。
  if (!(await page.locator('#view .chip[data-ckid]').count())) {
    bad('[v42] 「写校准」没有选孩子的按钮');
  }
  if (await page.locator('#view #cKid').count()) bad('[v42] 「写校准」还留着选孩子的下拉');
  if (!(await page.locator('#view .chip[data-ce="fine"]').count())) {
    bad('[v40] 「写校准」少了罚款那条处理方式');
  }
  /* v1.7：修复类型从下拉改成按钮 + 「自己写一条」。下拉要点开、再滚、再点，
     而这里总共才四五项；更要紧的是预设盖不住所有情况 ——
     今天是抹桌子，明天可能是给妹妹道个歉，与其逼家长挑个近似的，
     不如让他写。所以：预设是按钮；点「自己写一条」长出一个输入框；
     空着不许提交（没有完成标准的任务最后一定变成「你到底做没做」）。 */
  const ctChips = (await page.locator('#view .chip[data-ct]').allInnerTexts()).map(flat);
  say('   修复类型: ' + ctChips.join(' / '));
  if (ctChips.length < 5) bad('[v1.7] 修复类型按钮少于 5 颗：' + ctChips.join(' / '));
  if (ctChips.filter(t => t.indexOf('自己写') >= 0).length !== 1) {
    bad('[v1.7] 修复类型里没有「自己写一条」：' + ctChips.join(' / '));
  }
  if (await page.locator('#view #cTpl').count()) bad('[v1.7] 修复类型还留着下拉');
  if (!(await page.locator('#view #cTplCustom[hidden]').count())) {
    bad('[v1.7] 自定义那一格没藏起来（一进来就空着提示，等于一直在问）');
  }
  await clickSel(page, '#view .chip[data-ct="custom"]', '写校准 → 自己写一条');
  if (!(await page.locator('#view #cTplCustom:not([hidden])').count())) {
    bad('[v1.7] 点了「自己写一条」没长出输入框');
  }
  if (await page.locator('#view .chip[data-ct="custom"].on').count() !== 1) {
    bad('[v1.7] 「自己写一条」没选中');
  }
  /* v1.8：这一屏按「写任务」的版式重排 —— 两张卡、每行左边挂一个标签。
     那句「校准是让他承担后果…」原来吊在整屏最下面，现在挪到「哪件事」输入框
     正下面（那才是它解释的那一格）。所以量的是**结构**：两张卡、没有旧版
     .field 行、小字跟「哪件事」同卡且在其下方 —— 光查文字还在不在，
     版式退回去了照样过。 */
  const cg = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('#view .card--lg.pc'));
    const why = document.querySelector('#view #cWhy');
    const cap = document.querySelector('#view p.caption');
    const tpl = document.querySelector('#view #cTplBox');
    const c0 = cards[0] || null;
    const rb = el => (el ? el.getBoundingClientRect() : null);
    const w = rb(why), c = rb(cap);
    return {
      cards: cards.length,
      fields: document.querySelectorAll('#view .field').length,
      labels: Array.from(document.querySelectorAll('#view .prow .plab'))
        .map(l => l.innerText.replace(/\s+/g, '')).slice(0, 5),
      whyInCard0: !!(c0 && why && c0.contains(why)),
      capInCard0: !!(c0 && cap && c0.contains(cap)),
      capBelowWhy: !!(w && c && c.top >= w.bottom - 1),
      tplIsRow: !!(tpl && tpl.classList.contains('prow')),
    };
  });
  say('   写校准版式: ' + cg.cards + ' 张卡 / 标签 ' + cg.labels.join('、') +
      ' / 小字在「哪件事」下面 ' + (cg.capBelowWhy ? '是' : '否'));
  if (cg.cards !== 2) bad('[v1.8] 写校准不是两张卡，是 ' + cg.cards + ' 张');
  if (cg.fields) bad('[v1.8] 写校准还留着 ' + cg.fields + ' 个旧版 .field 行');
  if (!cg.whyInCard0 || !cg.capInCard0) bad('[v1.8] 「哪件事」或那句小字不在第一张卡里');
  if (!cg.capBelowWhy) bad('[v1.8] 小字说明没跟在「哪件事」输入框下面');
  if (!cg.tplIsRow) bad('[v1.8] 「修复类型」那一行不是 .prow（版式跟写任务不一致）');
  /* 写任务：「给谁」原来分两层（先选「派给一个孩子」，再在这一层里选哪个孩子），
     多点一次、多占一排。现在一层：挂大厅 + 每个孩子各一颗按钮，点谁就是派给谁。 */
  await clickSel(page, '#view .seg-item[data-pseg="new"]', '发布 → 写任务');
  if (!(await page.locator('#view #pIcon').count())) bad('[v40] 「写任务」没有配图那一格');
  const toChips = (await page.locator('#view .chip[data-to]').allInnerTexts()).map(flat);
  say('   给谁那排按钮: ' + toChips.join(' / '));
  if (toChips.length < 3) bad('[v1.6] 「给谁」按钮少于 3 颗（挂大厅 + 2 个孩子）：' + toChips.length);
  if (toChips[0] !== '挂大厅') bad('[v1.6] 「给谁」第一颗不是「挂大厅」，是「' + toChips[0] + '」');
  if (await page.locator('#view #pKid').count()) bad('[v1.6] 「给谁」还留着下拉');
  const kidChips = toChips.slice(1);
  /* 四句静态小注：有些只对某一种选择成立，就让它跟着按钮走；四条上限那种
     一次说得完的，写死一句反而清楚，不用拆。差别在于「换了之后会不会变成错话」。 */
  const cardTxt0 = flat(await page.evaluate(() => Array.from(
    document.querySelectorAll('#view .pc')).map(c => c.innerText).join(' ᛁ ')));
  /* v1.7：数量、配图、接取、时限四行后面的说明小字全撤了。理由写在别处那一版：
     四句都是「一次说得完」的事，写在那里只会把一屏拉长；真要说清楚的那句
     「写成能核对的样子」留在标题卡上，它是在教人怎么写标题，不是给控件做注脚。
     所以这里反过来查：四条里任何一条还在，就是没删干净。 */
  for (const s of ['星尘一周合计不超20·箱只到银·卡不发稀有', '大厅里先看到的就是它']) {
    if (cardTxt0.indexOf(s) >= 0) bad('[v1.7] 卡里还留着该撤的小注：' + s);
  }
  if (cardTxt0.indexOf('写成能核对的样子') < 0) bad('[v1.6] 卡里少了标题那句提示');
  /* v1.7：数量和配图搬到同一行。并起来这一屏少一行，按钮不用滚那么远。
     断言看的是两个控件的前后位置差，不是「有没有」—— 分两行时它也照样在。
     另外量一下「＋」和「配图」之间剩多少空：贴着的时候读起来是「＋配图」
     一个词，两件事混成一件。 */
  const pair = await page.evaluate(() => {
    const a = document.querySelector('#view #pAmtBox'), b = document.querySelector('#view #pIconBox');
    if (!a || !b) return null;
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    const lab = b.querySelector('.plab');
    return { sameRow: Math.abs(ra.top - rb.top) < 6, ay: ra.top, by: rb.top,
             aw: ra.width, bw: rb.width,
             gap: lab ? lab.getBoundingClientRect().left - ra.right : -1,
             over: Math.max(a.scrollWidth - a.clientWidth, b.scrollWidth - b.clientWidth) };
  });
  if (!pair) bad('[v1.7] 页面上找不到「数量 / 配图」两组');
  else {
    say('   数量与配图: ' + (pair.sameRow ? '同一行' : '还在两行') +
      '（数量 ' + Math.round(pair.aw) + 'px / 配图 ' + Math.round(pair.bw) +
      'px，中间留 ' + Math.round(pair.gap) + 'px）');
    if (!pair.sameRow) bad('[v1.7] 数量与配图没排到同一行');
    if (pair.gap < 10) {
      bad('[v1.7] 「＋」和「配图」只隔 ' + Math.round(pair.gap) + 'px，读起来是一个词');
    }
    if (pair.over > 1) bad('[v1.7] 数量 / 配图这一行挤爆了 ' + pair.over + 'px');
  }
  if (cardTxt0.indexOf('给谁') < 0) bad('[v1.6] 卡里找不到「给谁」那一行');
  // 「给谁」那一行不该带小注：选谁就是派给谁，六个字说得清的事不用再注一遍
  const toRowTxt = flat(await page.locator('#view .chip[data-to="hall"]')
    .evaluate(el => el.closest('.prow') ? el.closest('.prow').innerText : ''));
  say('   给谁那一行: ' + toRowTxt);
  if (/接不走|谁先点|直接派/.test(toRowTxt)) bad('[v1.6] 「给谁」那行还挂着小注：' + toRowTxt);
  /* v1.7：接取那句小注撤了 —— 「单人 / 多人」这两个词自己说得清，
     底下再挂一句「谁先点谁拿」是把同一件事说两遍。这里只测按钮真换了
     选中态：按键有没有反应比那句注脚重要。 */
  await page.locator('#view .chip[data-s="2"]').click();
  await page.waitForTimeout(300);
  if (!(await page.locator('#view .chip[data-s="2"].on').count())) {
    bad('[v1.7] 点了「多人接取」没选中它');
  }
  if (await page.locator('#view .chip[data-s="1"].on').count()) {
    bad('[v1.7] 选了多人，还高亮着「单人接取」');
  }
  await page.locator('#view .chip[data-s="1"]').click();
  await page.waitForTimeout(200);
  if (!(await page.locator('#view .chip[data-s="1"].on').count())) {
    bad('[v1.7] 点回「单人接取」没选中它');
  }
  // 点孩子的名字：直接派给他，同时「接取 / 时限」这两问没有意义，要收起来
  const footTip0 = flat(await page.locator('#view #pFootTip').innerText());
  const hallDisp0 = await page.locator('#view #pHallOnly').evaluate(el => el.style.display);
  await page.locator('#view .chip[data-to]').nth(1).click();
  await page.waitForTimeout(500);
  const hallDisp1 = await page.locator('#view #pHallOnly').evaluate(el => el.style.display);
  const footTip1 = flat(await page.locator('#view #pFootTip').innerText());
  say('   派给孩子后: 接取/时限 display ' + (hallDisp0 || '(空)') + ' → ' + hallDisp1 +
    '；底部「' + footTip0 + '」→「' + footTip1 + '」');
  if (hallDisp1 !== 'none') bad('[v1.6] 派给孩子之后，「接取 / 时限」没有收起来');
  if (footTip1 === footTip0) bad('[v1.6] 换了「给谁」，底部那句没跟着换');
  if (footTip1.indexOf('任务大厅') >= 0) bad('[v1.6] 派给孩子了，底部还在说进大厅');
  if (await page.locator('#view [data-to="hall"].on').count()) {
    bad('[v1.6] 选了某个孩子，还高亮着「挂大厅」');
  }
  const kidOn = flat(await page.locator('#view .chip[data-to].on').first().innerText());
  const kidOnCnt = await page.locator('#view .chip[data-to].on').count();
  say('   选中的孩子: ' + kidOn + '（高亮 ' + kidOnCnt + ' 个）');
  if (kidOn !== kidChips[0] || kidOnCnt !== 1) {
    bad('[v1.6] 点第一个孩子没选中它（选中的是「' + kidOn + '」，高亮 ' + kidOnCnt + ' 个）');
  }

  /* 配图那一格：这不是「在不在」的问题，是「点得开吗」的问题。
     v1.5 报上来的坏就是点了没反应 —— 面板的开合按钮当时是快照绑定：
     进这一屏时绑一次，而 #view 这个容器不重画（只换里面的 innerHTML），
     所以第二次进来，新画出来的那颗按钮身上一个监听都没有。
     所以这里要真点、并且点两次。

     v1.8：这一格从「在表单里就地撑开」改成**底部弹窗** —— 它长在「数量 + 配图」
     的右半栏里，一展开就被卡片右边缘切掉、还被上面那行压住，就是报上来的
     「显示不正常」。面板的 DOM 因此搬进了 #sheetBody（#view 里那个 #ipb-pIcon
     还在，但一直是 hidden），下面这些选择器也跟着换过去。 */
  await clickSel(page, '#view button[data-ip="pIcon"]', '写任务 → 配一张图');
  if (!(await page.locator('#sheet.on').count())) {
    bad('[v1.8] 点「配一张图」没弹出选图面板');
  }
  if (!(await page.locator('#sheetBody .ip-chips .chip').count())) {
    bad('[v1.8] 弹窗里没有配图面板（分组按钮一个都没有）');
  }
  if (!(await page.locator('#sheetBody #ipg-pIcon').count())) {
    bad('[v1.8] 弹窗里没有那一格格子容器 #ipg-pIcon');
  }
  await sheetLock(page, '配图');
  const ipCells = await page.locator('#sheetBody .ip-cell').count();
  const ipChips = (await page.locator('#sheetBody .ip-chips .chip').allInnerTexts()).map(flat);
  const ipOn = flat(await page.locator('#sheetBody .ip-chips .chip.on').first().innerText());
  say('   配图面板: ' + ipCells + ' 个格子；分组 ' + ipChips.slice(0, 4).join(' / ') + '…；停在「' + ipOn + '」');
  if (ipCells < 6) bad('[v42] 配图面板里格子太少：' + ipCells);
  if (ipOn !== '任务') bad('[v42] 配图面板没停在「任务」那一组，停在「' + ipOn + '」');
  // 任务这一组就是这一版新画的 17 张：挑一张，看它落没落进隐藏字段
  const questCells = await page.locator('#sheetBody .ip-cell[data-v^="quest_"]').count();
  say('   任务图标候选: ' + questCells + ' 张');
  if (questCells < 12) bad('[v42] 配图面板里任务图标只有 ' + questCells + ' 张');
  await page.locator('#sheetBody .ip-cell[data-v="quest_scroll"]').click();
  await page.waitForTimeout(400);
  const ipVal = await page.locator('#view #pIcon').inputValue();
  if (ipVal !== 'quest_scroll') bad('[v42] 挑了悬赏令，隐藏字段里是「' + ipVal + '」');
  // 挑完就得自己收起来。不收的话，下面「再点一次」连按钮都够不着 ——
  // 弹窗铺满整屏，按钮被盖住，Playwright 点不动。
  if (await page.locator('#sheet.on').count()) bad('[v1.8] 挑完图弹窗没自己关掉');
  // 第二次点开：老毛病就坏在这一下
  await clickSel(page, '#view button[data-ip="pIcon"]', '再点一次配一张图');
  if (!(await page.locator('#sheet.on').count())) {
    bad('[v42] 配图面板第二次点不开了（快照绑定的老毛病）');
  }
  // 搜索框也是点开之后才生成的，同样要真敲一次。
  /* 搜索一律跨组（v1.9 修的）：家长停在默认的「任务」那一组里搜「足球」，
     task_sport 明明在库里，原来被「先按组筛」挡掉，面板报「找到 0 张」——
     报上来的「搜索没效果」就是这一条。所以这里两条都要：组内那张搜得到，
     组外那张也得搜得到。 */
  await page.locator('#sheetBody #ipq-pIcon').fill('钥匙');
  await page.waitForTimeout(600);
  let ipHits = await page.evaluate(() => Array.from(
    document.querySelectorAll('#sheetBody .ip-cell'))
    .map(c => c.dataset.v || '').filter(Boolean));
  say('   搜「钥匙」之后命中: ' + (ipHits.join(' ') || '（空）'));
  if (ipHits.indexOf('quest_key') < 0) {
    bad('[v42] 配图面板搜「钥匙」没搜出 quest_key，命中 ' + JSON.stringify(ipHits));
  }
  await page.locator('#sheetBody #ipq-pIcon').fill('足球');
  await page.waitForTimeout(600);
  ipHits = await page.evaluate(() => Array.from(
    document.querySelectorAll('#sheetBody .ip-cell'))
    .map(c => c.dataset.v || '').filter(Boolean));
  say('   搜「足球」之后命中: ' + (ipHits.join(' ') || '（空）'));
  if (ipHits.indexOf('task_sport') < 0) {
    bad('[v1.9] 配图搜索没跨组：搜「足球」搜不到「日常」组里的 task_sport，命中 ' +
      JSON.stringify(ipHits.slice(0, 8)));
  }
  await clickSel(page, '#sheetBody button[data-ipc="pIcon"]', '配图 → 重置');
  const ipBack = await page.locator('#sheetBody .ip-cell').count();
  say('   重置之后格子: ' + ipBack + ' 个');
  if (ipBack < 18) bad('[v42] 点了「重置」没回到整组：' + ipBack);
  /* 分类那排是横滑的（22 个组铺 1100 多 px），而弹层那道滚动锁原来只看纵向：
     .sheet-body 不溢（默认的「任务」组就十几张，一屏放得下）就把落在这排上的
     touchmove 一并 preventDefault，分类左右划不动 —— 报上来的「不能左右滑动」。
     合成事件滚不动是真的，所以断言按「有没有被 preventDefault」判，不看滚没滚。
     这一条必须在面板内容矮的时候测，纵向一旦溢出，老代码也拦不到它。 */
  const chipScroll = await page.evaluate(() => {
    const box = document.querySelector('#sheetBody .ip-chips');
    const chip = box && box.querySelector('.chip');
    if (!box || !chip) return null;
    const ev = new TouchEvent('touchmove', { cancelable: true, bubbles: true });
    chip.dispatchEvent(ev);
    return { over: box.scrollWidth > box.clientWidth + 1, prevented: ev.defaultPrevented };
  });
  if (!chipScroll) bad('[v1.9] 配图弹窗里找不到分类那排 chips');
  else {
    say('   分类横向溢出: ' + chipScroll.over + '；touchmove 被拦: ' + chipScroll.prevented);
    if (chipScroll.over && chipScroll.prevented) {
      bad('[v1.9] 分类横滑被弹层的滚动锁拦掉了（落点不在纵向可滚的内容上）');
    }
  }
  // 点遮罩收起来：这一格没有「完成」按钮，家长就是点外面关的
  await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
  await page.waitForTimeout(400);
  if (await page.locator('#sheet.on').count()) bad('[v1.8] 点了弹窗外面，弹窗没关掉');

  /* 三个时限按钮都得在，「不限时」这一档是新加的：后端原来只有「有就用、
     没有就用默认 48 小时」两路，选了不限时会被默认值顶回来。 */
  const dlChips = (await page.locator('#view .chip[data-dl]').allInnerTexts()).map(flat);
  say('   时限按钮: ' + dlChips.join(' / '));
  if (dlChips.length !== 3) bad('[v1.6] 时限只有 ' + dlChips.length + ' 档（要有 3 档）：' + dlChips.join('/'));
  if (dlChips.indexOf('不限时') < 0) bad('[v1.6] 时限少了「不限时」那一档');

  // 真发一个任务出去，核对它落到的是刚点的那个人。
  // 光看按钮高亮不算数：点下去到底把谁传给了后端，只有真发一次才知道。
  /* 奖励换成娱乐券再发：直接派给某个孩子的任务，发出那一刻就占本周任务星尘
     额度；挂大厅的等有人领了才占。演示库走到这一步，女儿那 20 的额度往往
     已经用掉大半，发星尘会撞上「本周任务星尘已达上限」——那是规则在起作用，
     不是派活坏了，但它会把这条断言变成假报错。券不走那条额度，正好只测
     「派给了谁」这一件事。 */
  await page.locator('#view .chip[data-r="ticket"]').click();
  await page.waitForTimeout(200);
  const ttl = 'e2e 派活 ' + Date.now();
  await page.locator('#view #pT').fill(ttl);
  await page.locator('#view #pS').fill('e2e 自己发的，看它落到谁手上');
  /* 后端拒了也要看得出它为什么拒。只报「找不到」排查不到根上 ——
     额度顶住、参数改名、孩子被人停用，页面上的表现一模一样。 */
  let postTxt = '';
  const p = page.waitForResponse(r => r.url().indexOf('/api/tasks') >= 0 &&
    (r.request().method() || '') === 'POST', { timeout: 8000 }).catch(() => null);
  await page.locator('#view #pSend').click();
  const pres = await p;
  if (pres) {
    postTxt = pres.status() + ' ';
    try { postTxt += JSON.stringify(await pres.json()); } catch (e) { postTxt += '(no body)'; }
  } else { postTxt = '(没等到 POST /api/tasks)'; }
  await page.waitForTimeout(1600);
  const sent = await page.evaluate(async t => {
    const r = await fetch('/api/tasks/hall', { headers: { 'Accept': 'application/json' } });
    const d = await r.json();
    const all = [].concat(d.doing || [], d.hall || []);
    const x = all.filter(v => v.title === t)[0];
    return x ? { who: x.who || '', status: x.status || '' } : null;
  }, ttl);
  say('   真发一个任务: ' + (sent ? (sent.who || '（没名字）') + ' / ' + sent.status : '没找到'));
  say('   后端回的: ' + postTxt);
  if (!sent) bad('[v42] 派出去的任务在大厅清单里找不到（后端回的是 ' + postTxt + '）');
  else if (sent.who !== kidChips[0]) {
    bad('[v1.6] 派给「' + kidChips[0] + '」的任务落到了「' + sent.who + '」');
  }

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
  const calNow = flat(await page.locator('#view .cal-bar .month').innerText());
  /* v1.7：翻月从两个小描边按钮换成孩子端那一对圆块。到头的那一边不是
     「被禁用的按钮」而是一块灰的 —— 灰着摆在那儿说的是「前面没有了」，
     禁用只是一团看不懂的浅。所以这里查的是它到底还是不是一颗按钮。 */
  const mvBtnN = await page.locator('#view .cal-head button.cal-mv').count();
  const mvOffN = await page.locator('#view .cal-head .cal-mv.is-off').count();
  say('   翻月: 可点 ' + mvBtnN + ' 颗 / 到头灰着 ' + mvOffN + ' 颗');
  /* 这个壳原来叫 .cal-nav，跟 style.css 里「一颗 34×34 的方块按钮」撞了名，
     左箭头底下就垫出一块奶色方块来。改完名要真查一遍：壳上不能有底色，
     底下的方块没了，箭头才是干净的一颗圆。 */
  const headBox = await page.evaluate(() => {
    const el = document.querySelector('#view .cal-head');
    if (!el) return null;
    const g = getComputedStyle(el);
    return { bg: g.backgroundColor, w: el.getBoundingClientRect().width,
             old: document.querySelectorAll('#view .cal-nav').length };
  });
  if (!headBox) bad('[v1.7] 月度统计里找不到翻月那一段');
  else {
    say('   翻月壳: ' + Math.round(headBox.w) + 'px 宽，底色 ' + headBox.bg);
    if (headBox.bg !== 'rgba(0, 0, 0, 0)') {
      bad('[v1.7] 翻月那个壳自己带底色（' + headBox.bg + '），箭头底下会垫出一块方块');
    }
    if (headBox.w < 120) bad('[v1.7] 翻月那个壳只有 ' + Math.round(headBox.w) + 'px 宽，被挤住了');
    if (headBox.old) bad('[v1.7] 还有 .cal-nav 这个老壳名字在页面上（撞名没清干净）');
  }
  if (mvOffN !== 1) bad('[v1.7] 到了当月，「下个月」没变成灰块（灰块 ' + mvOffN + ' 颗）');
  if (mvBtnN !== 1) bad('[v1.7] 到了当月，翻月按钮不是 1 颗可点（' + mvBtnN + ' 颗）');
  /* v1.8：真机上「‹」是椭圆、「›」是正圆。根因是这两颗一个是 <button>、
     一个是 <span>（到当月那一档的右箭头是块灰的 span），iOS 给 button 套
     原生外观 + 自带 padding: 1px 6px，宽度被顶到 36px；span 老实听 CSS，28px。
     本机 Chrome 两颗天然都是 28×28，光量几何查不出来 —— 所以查的是那两行
     针对 iOS 的复位到底在不在，几何顺手比一遍。 */
  for (const a of await page.evaluate(() => Array.from(
      document.querySelectorAll('#view .cal-head .cal-mv')).map(el => {
        const cs = getComputedStyle(el), r = el.getBoundingClientRect();
        return { tag: (el.tagName || '').toLowerCase(),
          w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
          pad: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].join(' '),
          app: cs.appearance || '' };
      }))) {
    say('   翻月箭头: ' + a.tag + ' ' + a.w + '×' + a.h + ' pad="' + a.pad +
        '" appearance=' + a.app);
    if (a.pad !== '0px 0px 0px 0px') {
      bad('[v1.8] 翻月箭头（' + a.tag + '）还带着浏览器自带的 padding：' + a.pad);
    }
    if (!/^none/.test(a.app)) {
      bad('[v1.8] 翻月箭头（' + a.tag + '）没关掉原生外观：' + a.app);
    }
    if (Math.abs(a.w - a.h) > 0.6) {
      bad('[v1.8] 翻月箭头（' + a.tag + '）不是正圆：' + a.w + '×' + a.h);
    }
  }
  // v23：翻月不许把页面顶回最上面。月历在打分页最底部，
  // 翻一次就要重新往下滚一遍的话，等于没法连着看几个月。
  await page.locator('#view .cal-bar .month').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await page.locator('#view .cal-head button.cal-mv').first().click();
  await page.waitForTimeout(1200);
  const scrollAfter = await page.evaluate(() => window.scrollY);
  say('   翻月前后滚动位置: ' + scrollBefore + ' -> ' + scrollAfter);
  if (scrollBefore > 200 && scrollAfter < scrollBefore / 2) {
    bad('[月度统计] 翻月把页面顶回去了（' + scrollBefore + ' -> ' + scrollAfter + '）');
  }
  const calPrev = flat(await page.locator('#view .cal-bar .month').innerText());
  say('   切月份: ' + calNow + ' -> ' + calPrev);
  if (calNow === calPrev) bad('[月度统计] 点「上个月」月份没变');
  // 回当月。停在当月时右箭头是灰块（不是按钮），翻走之后它才变回按钮，
  // 所以这里按「第二颗」取。
  await page.locator('#view .cal-head button.cal-mv').nth(1).click();
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

  await tabTo(page, '我的');
  await page.waitForTimeout(900);
  /* v40：「我的」页最底下两行 —— 软件名与版本号一行、项目地址一行，都居中。
     它们原来挂在设置弹层最底下，而设置又套在「更多」弹层里：出问题要找
     「跑的是哪一版」时，得先记得它在哪儿。 */
  const meFoot = flat(await page.locator('#view .p-about').innerText().catch(() => ''));
  say('   「我的」页脚: ' + meFoot.slice(0, 40));
  if (!/家庭积分\s*v\d/.test(meFoot)) bad('[v40] 「我的」页底没有软件名与版本号');
  if (meFoot.indexOf('github.com/WW-Ares/FamilyPoints') < 0) {
    bad('[v40] 「我的」页底没有项目地址');
  }

  /* v40：设置从弹层改成独立页，13 组收成 7 组并分两级 ——
     先列七件事（带项数），点进去才看见这一组的项。
     一级 >>> 二级 >>> 返回一级 >>> 返回「我的」，四步每一步都要落在正确的地方。 */
  await clickSel(page, '#view [data-go="settings"]', '我的 → 设置');
  const setTxt = await flat(await page.locator('#view').innerText());
  const grpRows = await page.locator('#view [data-setgrp]').count();
  say('   设置页一级: ' + grpRows + ' 组 | ' + setTxt.slice(0, 46));
  if (grpRows !== 7) bad('[v40] 设置页一级不是 7 组，是 ' + grpRows);
  for (const want of ['每天的七分', '周期与假期', '任务与心愿', '奖励与道具',
    '校准与钱', '红线与运维', '通知与推送']) {
    if (setTxt.indexOf(want) < 0) bad('[v40] 设置页一级缺组「' + want + '」');
  }
  // 每条红线都该还在，只是不再单独占一组
  if (!(await page.locator('#view [data-setgrp="红线与运维"]').count())) {
    bad('[v40] 找不到「红线与运维」这一组');
  }
  await clickSel(page, '#view [data-setgrp="校准与钱"]', '设置 → 校准与钱');
  const subTxt = flat(await page.locator('#view').innerText());
  const subItems = await page.locator('#view .item').count();
  say('   设置页二级「校准与钱」: ' + subItems + ' 项');
  if (subItems < 10) bad('[v40] 「校准与钱」这一组的项太少：' + subItems);
  if (subTxt.indexOf('补差通道') >= 0) bad('[v40] 设置里还留着「补差通道」那条墓碑');
  await clickSel(page, '#view #pSetBack', '设置二级 返回');
  if ((await page.locator('#view [data-setgrp]').count()) !== 7) {
    bad('[v40] 二级页返回没回到设置页一级');
  }
  await clickSel(page, '#view [data-back]', '设置 返回');
  const backMe = flat(await page.locator('#view').innerText());
  if (backMe.indexOf('退出登录') < 0) bad('[v40] 设置页返回没回到「我的」');

  /* v41：「更多」整行撤掉。它和设置页撞车 —— 设置里本来就有「通知与推送」
     与「周期与假期」两组，而假期日历、推送设备、备份、家人账号、改密码又各
     在另一处，同一件事两个入口，改一处另一处必漂。现在：
       · 通知与推送 / 假期日历 → 收进设置页对应那一组（组里给一个按钮）
       · 备份与导出 / 家人账号 / 改我的密码 → 「我的」页各自一行 */
  say('');
  say('6. 家长端「我的」页入口:');
  await tabTo(page, '我的');
  await page.waitForTimeout(700);
  const meRows = flat(await page.locator('#view').innerText());
  if (meRows.indexOf('更多') >= 0) bad('[v41] 「我的」页还留着「更多」');
  for (const want of ['我的记录', '家人账号', '改我的密码', '备份与导出', '设置']) {
    if (meRows.indexOf(want) < 0) bad('[v41] 「我的」页缺入口「' + want + '」');
  }
  // 「我的记录」是跳页不是弹层（走动态日志页，前面已经验过），这里只验三个开弹层的。
  for (const [act, name] of [['members', '家人账号'], ['chpw', '改我的密码'],
    ['ops', '备份与导出']]) {
    await clickSel(page, '#view [data-act="' + act + '"]', '我的 → ' + name);
    await page.waitForTimeout(700);
    const on = await page.locator('#sheet.on').count();
    if (!on) { bad('[未弹出] 我的 → ' + name); continue; }
    const body = flat(await page.locator('#sheet.on .sheet-body').innerText());
    say('   [弹层] ' + name + ' -> ' + body.length + ' 字: ' + body.slice(0, 56));
    if (body.length < 4) bad('[空弹层] 我的 → ' + name);
    await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(300);
  }

  // 设置页里那两个「不是数字、得单独开一屏」的入口。原先它们挂在「更多」
  // 里，跟这两个分组说的是同一件事。
  await clickSel(page, '#view [data-go="settings"]', '我的 → 设置');
  for (const [grp, qa, name] of [['通知与推送', 'push', '家人的手机与推送'],
    ['周期与假期', 'holiday', '假期日历']]) {
    await clickSel(page, '#view [data-setgrp="' + grp + '"]', '设置 → ' + grp);
    await clickSel(page, '#view [data-grpqa="' + qa + '"]', grp + ' → ' + name);
    await page.waitForTimeout(700);
    const on = await page.locator('#sheet.on').count();
    if (!on) { bad('[未弹出] 设置 → ' + name); continue; }
    const body = flat(await page.locator('#sheet.on .sheet-body').innerText());
    say('   [弹层] ' + name + ' -> ' + body.length + ' 字: ' + body.slice(0, 56));
    if (body.length < 4) bad('[空弹层] 设置 → ' + name);
    await sheetLock(page, '设置 → ' + name);
    await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
    await page.waitForTimeout(300);
    await clickSel(page, '#view #pSetBack', grp + ' 二级 返回');
  }

  /* v41：整套图标重画。宝箱七档从「六档共用 rw_box、第七档 rw_box_open」
     换成各自一档一张；家长唯一能看见全套图的地方就是这个「给它们换张图」。
     数三组、数七档，并确认七档互不重样、图真的加载出来了 ——
     原来的坏法是「库里存了新 token，icons/ 里没有对应文件」，
     界面上只看得到一片空白，没有任何报错。 */
  say('');
  say('7. 「给它们换张图」:');
  // 刚从两组二级页退回设置一级，那颗按钮就在这一屏上，不用再绕一趟「我的」。
  await clickSel(page, '#view #iconBtn', '设置 → 给它们换张图');
  await page.waitForTimeout(1000);
  const iconBody = flat(await page.locator('#sheet.on .sheet-body').innerText());
  await sheetLock(page, '给它们换张图');
  for (const grp of ['七个维度', '宝箱七档', '券与卡']) {
    if (iconBody.indexOf(grp) < 0) bad('[v41] 换图弹层缺一组「' + grp + '」');
  }
  const cellSrc = sel => page.evaluate(s => Array.from(
    document.querySelectorAll('#sheet.on ' + s + ' img.gly'))
    .map(i => i.getAttribute('src')), sel);
  const boxSrc = await cellSrc('[data-ip^="ic-b-"]');
  say('   宝箱七档: ' + boxSrc.length + ' 张 -> ' + boxSrc.join(' '));
  if (boxSrc.length !== 7) bad('[v41] 宝箱七档不是 7 张，是 ' + boxSrc.length);
  if (new Set(boxSrc).size !== boxSrc.length) bad('[v41] 宝箱七档里有重复的图');
  const dimSrc = await cellSrc('[data-ip^="ic-d-"]');
  say('   七个维度: ' + dimSrc.length + ' 张，去重后 ' + new Set(dimSrc).size + ' 张');
  if (dimSrc.length !== 7) bad('[v41] 七个维度不是 7 张，是 ' + dimSrc.length);
  if (new Set(dimSrc).size !== dimSrc.length) bad('[v41] 七个维度里有重复的图');
  const broken = await page.evaluate(() => Array.from(
    document.querySelectorAll('#sheet.on img.gly'))
    .filter(i => i.complete && i.naturalWidth === 0).length);
  say('   没加载出来的图: ' + broken + ' 张');
  if (broken) bad('[v41] 换图弹层里有 ' + broken + ' 张图没加载出来');

  /* v1.9：点「换」从「在列表里就地撑开」改成独立弹窗。就地撑开那个面板最多
     120 张候选图（1100 多 px），夹在 7 维度 / 7 档宝箱 / 券卡中间，列表被顶得
     找不着北。这里真点一次，查的是「开成了什么形状」。 */
  await page.locator('#sheetBody button[data-ip]').first().click();
  await page.waitForTimeout(600);
  const pop = await page.evaluate(() => {
    const b = document.querySelector('#sheetBody');
    return {
      chips: b.querySelectorAll('.ip-chips .chip').length,
      back: !!b.querySelector('.ip-back'),
      inline: Array.from(b.querySelectorAll('.ip-box')).filter(x => !x.hidden).length,
    };
  });
  say('   点「换」之后：分类 ' + pop.chips + ' 个 / 退回按钮 ' + pop.back +
    ' / 就地撑开 ' + pop.inline + ' 个');
  if (!pop.chips || !pop.back) bad('[v1.9] 点「换」没开成配图弹窗：' + JSON.stringify(pop));
  if (pop.inline) bad('[v1.9] 还有在列表里就地撑开的面板 ' + pop.inline + ' 个');

  /* 分类那排横滑到右边，点一下会弹回最左边 —— 重画是整块 innerHTML 换掉，
     滚动位置跟着一起没了，家长得从头再划一遍。这里直接量 scrollLeft。 */
  await page.evaluate(() => { document.querySelector('#sheetBody .ip-chips').scrollLeft = 400; });
  const nChip = await page.locator('#sheetBody .ip-chips .chip').count();
  await page.locator('#sheetBody .ip-chips .chip').nth(nChip - 1).click();
  await page.waitForTimeout(400);
  const chipX = await page.evaluate(() =>
    document.querySelector('#sheetBody .ip-chips').scrollLeft);
  say('   分类滑到 400 再点最右一个：scrollLeft=' + chipX);
  if (chipX < 5) bad('[v1.9] 点了分类之后那排又弹回最左边了');

  // 退回一级列表：挑完图弹窗自己会退，这条按钮是给「看了不想改」留的
  await page.locator('#sheetBody .ip-back').click();
  await page.waitForTimeout(1200);
  if (!(await page.locator('#sheetBody .sec-h h2').count())) {
    bad('[v1.9] 点「回到列表」没退回一级列表');
  }

  await page.locator('#sheet').click({ position: { x: 4, y: 4 } });
  await page.waitForTimeout(300);

  // ---------- 汇总 ----------
  say('');
  say('=== 报错汇总 ===');
  if (!errors.length) say('  0 条报错');
  else errors.forEach(e => say('  ' + e));
  say('截图目录: ' + SHOT);

  await browser.close();
  process.exit(errors.length ? 1 : 0);
})().catch(e => { console.log('脚本自身失败: ' + e.stack); process.exit(2); });
