'use strict';
/* ============================================================================
   孩子端 UI 层 ·「糖果冒险」
   ----------------------------------------------------------------------------
   为什么要单独一份，而不是接着往 app.js 里塞：

   1. 孩子端和家长端是两套视觉（糖果冒险 / 深绿商务），也是两套导航
      （底栏 5 格 / 顶栏 + 6 格）。混在一个文件里，改哪边都得先分辨这段
      到底给谁用，改错一次就是「家长页面上冒出一个橙色按钮」。
   2. 这里只画界面。数据一律走原来那些接口，动作一律走原来那些弹层，
      所以后端一行没动 —— 「换皮」就该只是换皮。

   三件事必须知道：

   · 底栏 5 格：首页 / 任务 / 宝箱 / 券包 / 我的。
     成长报告在首页的能量卡上（整卡可点）；心愿屋在「我的」里；
     任务大厅是任务页的分段器第二段；券商店是券包页的分段器第二段。
     二级页压在 Tab 之上，底栏高亮着它所属的那一格。

   · 刷新后还在当前页、返回键能退回上一屏：靠 hash（#report 这种）。
     不用 pushState 直接换 path，是因为服务端只认那几个静态文件，
     多一条路径就要多一条路由 —— 一个家庭内网服务没必要为此改后端。

   · 颜色、圆角、投影全在 child-tokens.css / child.css，且都挂在 body.kid 下。
     这里不写死任何色值，除了那种「只在这一处出现、且是图形的一部分」的
     （比如雷达图里那条虚线的灰）。
   ============================================================================ */

/* ============================================================ 图标出口 */
/* 43 个图标做成雪碧图（candy-icons.js），颜色靠 currentColor 走，
   所以同一个图标在橙卡上是白的、在蓝任务卡里是蓝的。
   唯一的渲染出口，别就地拼 <svg>：认不出来的名字要能安静地什么都不画，
   而不是在页面上留一段 <use href="#undefined">。 */
let K_SPRITE_ON = false;
function kSprite() {
  if (K_SPRITE_ON || typeof CANDY_SPRITE === 'undefined') return;
  document.body.insertAdjacentHTML('afterbegin', CANDY_SPRITE);
  K_SPRITE_ON = true;
}
function ic(name, size, color) {
  const px = size || 16;
  if (!name || (typeof CANDY_ICONS !== 'undefined' && CANDY_ICONS.indexOf(name) < 0)) return '';
  /* 尺寸写成 calc(px * var(--u))，跟着手机流体缩放一起走（--u 在 style.css 的 :root）。
     390 宽处 --u 正好 1px，所以还是原尺寸；改成 style 而不是 width/height 属性，
     是因为属性压不过 CSS 里那些 `.ico { width: 22px }`，写了也是白写。 */
  return '<svg class="ico" style="width:calc(' + px + ' * var(--u));height:calc(' + px + ' * var(--u))' +
    (color ? ';color:' + color : '') + '" viewBox="0 0 24 24" ' +
    'aria-hidden="true"><use href="#' + name + '"/></svg>';
}

/* ============================================================ 小工具 */
/* 拉一份可选的接口，失败就当没有 —— 首页上七八个数据源，任何一个抖一下
   都不该让整页变成「没能显示出来」。主要数据（周期、宝箱）仍然用 api() 直接抛。 */
async function kg(path) {
  try { return await api('GET', path); } catch (e) { return null; }
}
const K_TIER_ICON = ['i-chest-wood', 'i-chest-bronze', 'i-chest-silver', 'i-chest-gold',
  'i-chest-diamond', 'i-chest-king', 'i-chest-perfect'];
function kBoxIcon(tier) { return K_TIER_ICON[(+tier || 1) - 1] || 'i-chest-wood'; }
/* 箱子叫什么。名字只有一个来源：接口给的 tier 对象里就带着「木箱 / 铜箱 / 银箱」，
   这里补的是「只有档位号」那一处（周期记录那格）。两头都加「箱」就会拼出
   「铜箱箱」—— v31 首屏自检就是这么抓到的。 */
function kBoxName(t) {
  if (t == null || t === '') return '';
  if (typeof t === 'number') return (BOX_NAME[t - 1] || '') + '箱';
  const n = String(t.name || '');
  if (!n) return '';
  return /箱$/.test(n) ? n : n + '箱';
}
function kLvPill(lv) {
  if (!lv || !lv.level) return '';
  return '<span class="pill pill--purple" style="padding:3px 9px">Lv.' + lv.level +
    (lv.title ? ' · ' + esc(lv.title) : '') + '</span>';
}
/* 奖励胶囊。奖励可能是星尘、能量或者一样东西，图标跟着类型走，
   不然「1 张券」前面挂一颗星尘，孩子会以为发的是星尘。 */
function kReward(text, type) {
  if (!text) return '';
  const ico = (type && type !== 'stardust') ? 'i-box' : 'i-stardust';
  return '<span class="reward">' + ic(ico, 11,
    (type && type !== 'stardust') ? '#B87A0C' : '#FFB020') + esc(text) + '</span>';
}
/* 任务三态点：1 亮=待做，2 亮=在做，3 亮=交上去，全绿=已完成。
   待做和在做是两回事，但都属于「孩子手上还没交的活」，点上必须分开亮。 */
function kDots(state) {
  const n = state === 'submitted' ? 3 : (state === 'claimed' ? 2 : (state === 'pending' ? 1 : 0));
  let h = '<span class="dots">';
  for (let i = 0; i < 3; i++) {
    h += '<i class="' + (state === 'confirmed' ? 'is-done' : (i < n ? 'is-on' : '')) + '"></i>';
  }
  return h + '</span>';
}
/* 本周能量折成七格：每格一档（7 分），正在攒的那一格画半格 */
function kSlots(energy, tiers, plain) {
  const per = tiers && tiers.length ? tiers[0].threshold : 7;
  let h = '<div class="chest-slots' + (plain ? ' on-plain' : '') + '">';
  for (let i = 0; i < 7; i++) {
    const low = i * per, mid = low + per / 2;
    const cls = energy >= low + per ? 'is-full' : (energy >= mid ? 'is-half' : '');
    h += '<i' + (cls ? ' class="' + cls + '"' : '') + '></i>';
  }
  return h + '</div>';
}
const K_TASK_STATE = { claimed: '在做', submitted: '等确认', pending: '待做' };
/* 七维度的颜色，跟 web/icons/dim_*.svg 里那个圆底是同一个值（tools/build_icons.py 生成）。
   首页七分矩阵拿它画拿到的那一格：颜色本身就是「哪一项」，不用再把名字写一遍。 */
const DIM_COLOR = {
  heart: '#EC7B72', study: '#6FA8DC', vigor: '#F5A75D', bond: '#EFA8B8',
  craft: '#C9905F', clean: '#7FC4C9', order: '#B58BD9',
};
/* 别人的活只报一句状态，大厅页看别人手上的那份要用。
   这里必须跟着 K_TASK_STATE 走：写死「在做」会把家长派的待做也念成在做。 */
function kTaskTag(status) {
  return '（' + (K_TASK_STATE[status] || status || '') + '）';
}
/* 截止时间只写日子。「2026-09-22 23:57:42 前交上去」在窄卡片里要折成两行，
   孩子一眼要抓的是哪一天，时分秒是给我们自己看的。 */
function kDeadline(s) {
  const m = String(s == null ? '' : s).match(/^(\d{4})-(\d\d)-(\d\d)/);
  return m ? (m[2] + '-' + m[3]) : String(s == null ? '' : s);
}
/* 首页那三条动态的小符号。按「这条是谁做的」分色，跟全站的颜色语汇对齐：
   金=到手的（星尘、宝箱）、橙=自己按的（买券买卡、兑零花钱）、蓝=任务、
   粉=心愿、紫=校准。符号比文字先被看见，一眼就知道这条是进账还是被记了一笔。 */
const K_FEED_SRC = {
  given:       { icon: 'i-stardust', fg: 'var(--gold-deep)',   bg: 'var(--gold-pale)' },
  box:         { icon: 'i-box',      fg: 'var(--gold-deep)',   bg: 'var(--gold-pale)' },
  self:        { icon: 'i-coupon',   fg: 'var(--orange-deep)', bg: 'var(--warn-bg)' },
  task:        { icon: 'i-task',     fg: 'var(--blue-deep)',   bg: 'var(--blue-bg)' },
  wish:        { icon: 'i-wishstar', fg: 'var(--pink-deep)',   bg: 'var(--pink-bg)' },
  calibration: { icon: 'i-info',     fg: 'var(--purple-deep)', bg: 'var(--purple-bg)' },
};
/* 胶囊里放不下 `2026-09-21 19:40:03`，而这三条要回答的是「多久之前」。
   认不出格式就原样返回：宁可难看，不要瞎猜一个时间。 */
function kAgo(ts) {
  const s = String(ts == null ? '' : ts);
  const m = s.match(/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/);
  if (!m) return s;
  const then = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  if (isNaN(then.getTime())) return s;
  const mins = Math.floor((Date.now() - then.getTime()) / 60000);
  const day = m[1] + '-' + m[2] + '-' + m[3];
  if (mins < 1) return '刚刚';
  if (mins < 60) return mins + ' 分钟前';
  if (day === todayStr()) return Math.floor(mins / 60) + ' 小时前';
  if (mins < 60 * 36) return '昨天';
  return m[2] + '-' + m[3];
}

/* ============================================================ 导航 */
/* 每一屏归哪一个底栏格。二级页也写在这儿：底栏高亮靠它，
   「返回上一屏」找不到路时也退回它所属的 Tab。 */
const K_TAB_OF = {
  home: 'home', report: 'home',
  task: 'task', hall: 'task',
  chest: 'chest',
  coupon: 'coupon', shop: 'coupon',
  mine: 'mine', wish: 'mine', atlas: 'mine', family: 'mine',
};
const K_TABS = [
  ['home', 'i-home', '首页'], ['task', 'i-task', '任务'], ['chest', 'i-chest-nav', '宝箱'],
  ['coupon', 'i-coupon', '券包'], ['mine', 'i-me', '我的'],
];
function kValid(v) { return !!K_TAB_OF[v]; }

function kHash(v, push) {
  if (location.hash === '#' + v) return;
  try {
    if (push === false) history.replaceState({ v: v }, '', '#' + v);
    else history.pushState({ v: v }, '', '#' + v);
  } catch (e) { /* file:// 之类下面没有 history，能跑就行 */ }
}
/* 唯一的换屏入口。所有 data-go / 底栏 / 返回都走它 ——
   换屏时不重画底栏的话，二级页进去以后高亮还停在上一个 Tab 上。 */
function kGo(v) {
  if (!kValid(v) || v === S.view) { if (v === S.view) kRedraw(v, true); return; }
  // 记一句「从哪来」。二级页（报告 / 心愿屋 / 图鉴 / 家庭）的返回要看它：
  // 原来返回按钮写死 data-go="home" / "mine"，于是从「我的」进成长报告，
  // 点返回掉回首页；心愿屋从首页也能进，返回的却是「我的」。
  if (!S.from) S.from = {};
  S.from[v] = S.view;
  S.view = v;
  kHash(v);
  // render() 会把滚动位置还回去，换屏要先清成 0，不然新的一屏停在上一屏的位置
  if (typeof scrollTop0 === 'function') scrollTop0();
  renderTabs();
  render();
}
/* 这一屏的返回目标：有来路就回来路，没有（比如刷新后直接落在这一屏，
   或者这一屏就是个 Tab）退回它所属的底栏格。 */
function kBack(v) {
  const f = (S.from || {})[v];
  if (f && kValid(f) && f !== v) return f;
  return K_TAB_OF[v] || 'home';
}
function kRedraw(v, same) {
  // 已经在当前屏时点同一格：只把内容重画一遍，不产生新的历史记录
  if (same) render();
}

/* ============================================================ 外壳 */
function kShell(opt, body) {
  opt = opt || {};
  let head = '';
  if (opt.back || opt.title) {
    head = '<div class="appbar">' +
      (opt.back ? '<button class="appbar-back" type="button" data-go="' + opt.back + '">' +
        ic('i-back', 16, 'var(--ink)') + '</button>' : '') +
      '<span class="appbar-grow">' +
      '<div class="appbar-title">' + esc(opt.title || '') + '</div>' +
      (opt.sub ? '<div class="appbar-sub">' + esc(opt.sub) + '</div>' : '') +
      '</span>' +
      (opt.right ? '<span class="appbar-right">' + opt.right + '</span>' : '') +
      '</div>';
  }
  return '<div class="screen">' + head +
    '<div class="content' + (head ? '' : ' lead') + '">' + body + '</div></div>';
}

/* 「有事就说」的两个入口。刻意不做成道具卡：偷玩的根因是「正规通道比偷玩更麻烦」，
   把入口埋进两层菜单，等于亲手把它变回更麻烦的那一条。
   两条各贴着它要用的那个地方：申请加时在券包（紧挨着要用的那张券），
   「这题我不会」在首页（正在写作业的时候开的就是这一屏）。
   原来两块都堆在「我的」最下面，等于要翻两屏才找得到。
   按钮 id 不变，CHILD.bind 按 id 绑，不用跟着搬。 */
function kAskCard(kind) {
  const ot = kind === 'ot';
  return '<div class="card card--tight"><div class="hb"><div>' +
    '<div class="row-title">' + (ot ? '想多玩一会儿' : '这题我不会') + '</div>' +
    '<div class="row-sub">' + (ot ? '不用攒卡，也不用先表现好'
      : '说清楚卡在哪一步，核实后 +1 星尘') + '</div></div>' +
    '<button class="btn btn--sm' + (ot ? '' : ' line') + '" id="' +
    (ot ? 'kAskOt' : 'kAskHelp') + '">' + (ot ? '申请加时' : '说一声') +
    '</button></div></div>';
}

/* ============================================================ 七分矩阵（首页） */
/* 「这一周的七分」：七行维度 × 七列这一周。格子四态 —— 拿到是实心的维度色，
   那天过去了没拿到是浅棕，今天在格子外面套一圈橙框，还没到的日子是最浅的米色。
   数据整份来自 /api/score/cycle：界面不自己猜「今天算不算」，只拿 day 跟今天比一次。 */
function kWeekCard(wk, todayS) {
  const days = (wk && wk.days) || [];
  const dims = (wk && wk.dims) || [];
  if (!days.length || !dims.length) return '';
  const WD = ['日', '一', '二', '三', '四', '五', '六'];
  const maps = days.map(d => {
    const m = {};
    (d.dims || []).forEach(r => { m[r.code] = r.value; });
    return m;
  });
  const scoredDays = days.filter(d => d.scored).length;
  const cntOf = code => days.reduce((a, d, i) => a + (maps[i][code] === 1 ? 1 : 0), 0);

  let h = '<div class="k7"><div class="k7-head">' +
    '<span class="h g7">' + ic('i-star', 15, '#FFC93C') +
    '<span class="k7-title">这一周的七分</span></span>' +
    '<span class="k7-legend">灰色 = 还没到，橙框 = 今天</span></div>';

  // 列头：星期几。今天那一格是橙的，跟下面格子上的橙框对上。
  h += '<div class="k7-row k7-cols"><span class="k7-ic"></span>' +
    '<span class="k7-nm"></span><span class="k7-cells">' + days.map(d =>
      '<span class="k7-wd' + (d.day === todayS ? ' is-today' : '') + '">' +
      WD[new Date(d.day + 'T00:00:00').getDay()] + '</span>').join('') +
    '</span><span class="k7-day"></span></div>';

  dims.forEach(dim => {
    const cells = days.map((d, i) => {
      const got = maps[i][dim.code] === 1;
      const cls = 'k7-c ' + (got ? 'is-on' : (d.day > todayS ? 'is-future' : 'is-off')) +
        (d.day === todayS ? ' is-today' : '');
      const c = got ? DIM_COLOR[dim.code] : '';
      return '<span class="' + cls + '"' + (c ? ' style="background:' + c + '"' : '') + '></span>';
    }).join('');
    const n = cntOf(dim.code);
    // 天数三档：拿满（跟已打分的天数持平）橙、拿到一些褐、一天没有灰。
    // 只分「有没有」两档的话，5 天和 1 天在边上长得一样。
    const dcls = n ? (n >= scoredDays ? ' is-hot' : ' is-mid') : '';
    h += '<div class="k7-row"><span class="k7-ic">' + glyph(dim.icon, 'dim', 20) + '</span>' +
      '<span class="k7-nm">' + esc(dim.name) + '</span>' +
      '<span class="k7-cells">' + cells + '</span>' +
      '<span class="k7-day' + dcls + '">' + num(n) + ' 天</span></div>';
  });

  // 结论条：一句说谁最好，一句说谁还空着。两句都是这一周现算的，不落库 ——
  // 孩子哪天补了分，这两句得跟着变。
  let l1, l2 = '';
  if (!scoredDays) {
    l1 = '这一周刚开始，拿到的分都会记在这';
  } else {
    const best = dims.filter(d => cntOf(d.code) === scoredDays).map(d => d.name);
    const zero = dims.filter(d => !cntOf(d.code)).map(d => d.name);
    l1 = best.length ? (best.join('、') + '最好，' + num(scoredDays) + '天都拿到了')
      : '还没有哪一项天天都拿到';
    if (zero.length) l2 = zero.join('、') + '一次都没拿到，明天试试看？';
  }
  h += '<div class="k7-concl">' + ic('i-star', 16, '#FFB020') +
    '<span class="k7-cg"><span class="k7-c1">' + esc(l1) + '</span>' +
    (l2 ? '<span class="k7-c2">' + esc(l2) + '</span>' : '') + '</span>' +
    '<span class="k7-go" data-go="report">看成长报告' + ic('i-chevron', 9, '#E87229') +
    '</span></div>';
  return h + '</div>';
}

/* ============================================================ 首页 */
async function kScreenHome() {
  const mid = S.me.id;
  const cyc = await api('GET', '/api/cycle?member_id=' + mid);
  const dv = await kg('/api/score/day?member_id=' + mid + '&day=' + todayStr());
  const tks = await kg('/api/tickets/mine?member_id=' + mid);
  const hl = await kg('/api/tasks/hall');
  const ws = await kg('/api/wishes');
  const fd = await kg('/api/feed?limit=8&recent=4');
  const wk = await kg('/api/score/cycle?member_id=' + mid + '&day=' + todayStr());

  const lv = cyc.level;
  const sd = S.data.overview ? S.data.overview.stardust : 0;
  // 周期第几天：七分卡的列头和角色条副标共用这一份，别各自数一遍。
  const wkDays = (wk && wk.days) || [];
  const dayNo = wkDays.findIndex(d => d.day === todayStr()) + 1;

  let h = '';

  // ① 角色条
  const todayTxt = (dv && dv.scored ? '今天能量 ' + num(dv.score) + '/' + num(dv.full)
    : '今天还没打分') + (dayNo > 0 ? ' · 第 ' + num(dayNo) + ' 天' : '');
  h += '<div class="h g12">' +
    '<span style="flex:0 0 44px">' + avatarHTML(S.me, 44) + '</span>' +
    '<div class="grow v g5">' +
    '<div class="h g8"><span style="font-size:20px;font-weight:700">' + esc(S.me.name) + '</span>' +
    kLvPill(lv) + '</div>' +
    '<div class="k7-sub">' + esc(todayTxt) + '</div>' +
    '</div>' +
    '<span class="pill pill--gold" style="gap:6px;padding:6px 11px">' +
    ic('i-stardust', 13, '#fff') +
    '<span class="num" style="font-size:12.5px">' + num(sd) + '</span></span>' +
    '</div>';

  if (S.data.holiday) {
    h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') +
      '现在是' + esc(S.data.holiday.name) + '，维度换成了假期版</div>';
  }

  // ② 这一周的七分。原位置上是一张「本周能量」卡，撤掉了：宝箱页第一行就在报
  //    同一个数，首页再摆一张，同一根进度条在两处各说各话。这一周拿到了什么，
  //    改成按七个维度摊开来看。
  h += kWeekCard(wk, todayStr());

  // ③ 正在玩
  const playing = (tks && tks.playing || [])[0];
  if (playing) {
    h += '<div class="hero hero--purple" data-tkend="' + esc(playing.end_at) +
      '" data-tkfmt="mmss" data-tktotal="' + num(playing.total_minutes || 0) + '">' +
      '<div class="hb"><span class="h g6">' +
      '<i style="width:8px;height:8px;border-radius:50%;background:#fff;' +
      'box-shadow:0 0 0 4px rgba(255,255,255,.22);display:block"></i>' +
      '<span class="on-hero-90" style="font-size:11.5px;font-weight:700">正在玩</span></span>' +
      '<span class="on-hero-70" style="font-size:10px">' +
      (playing.note ? esc(playing.note) : '爸爸妈妈同意的') + '</span></div>' +
      '<div class="hb" style="margin-top:4px"><span class="num tk-big" data-tkleft>' +
      esc(tkClock(tkLeftMs(playing.end_at))) + '</span>' +
      '<span class="h g6">' + ic('i-clock', 14, 'rgba(255,255,255,.82)') +
      '<span class="on-hero-90" style="font-size:10.5px">到 ' +
      esc(String(playing.end_at).slice(11, 16)) + ' 结束</span></span></div>' +
      '<div class="bar bar--onhero" style="margin-top:12px"><i data-tkbar style="width:0%"></i></div>' +
      '</div>';
  }

  // ④ 要做的事
  // 家长直接派下来的活是 pending（待做），大厅里领的才是 claimed（在做）。
  // 两种都是孩子手上还没交的活，只认 claimed 会把派下来的那条整个藏掉 ——
  // 首页照「全部 N 件」算的时候又把它数进去，于是「全部 1 件」底下写着「手上没有活」。
  const mine = (hl && hl.doing || []).filter(t => t.assignee_id === mid);
  const doing = mine.filter(t => t.status !== 'submitted');
  const waits = mine.filter(t => t.status === 'submitted');
  const all = doing.concat(waits).slice(0, 3);
  h += '<div class="sect-head"><span class="sect-title">' + ic('i-task', 16, 'var(--blue-deep)') +
    '要做的事</span><span class="sect-note" data-go="task" style="cursor:pointer">全部 ' +
    num(mine.length) + ' 件 ›</span></div>';
  if (!all.length) {
    h += '<div class="card"><div class="empty">手上没有活，去任务大厅看看</div></div>';
  } else {
    all.forEach(t => {
      h += '<div class="task-card"><div class="task-row">' +
        '<span class="task-ico">' + glyph(t.icon, 'task', 20) + '</span>' +
        '<div class="grow"><div class="task-name">' + esc(t.title) + '</div>' +
        '<div class="h g6 mt6">' + kDots(t.status) +
        '<span class="t-2" style="font-size:10px">' +
        (t.status === 'submitted' ? '交上去了 · 等爸爸妈妈点头'
          : ((K_TASK_STATE[t.status] || '在做') +
             (t.deadline ? ' · ' + esc(kDeadline(t.deadline)) + ' 前交上去' : ' · 做完点提交'))) +
        '</span></div></div>' +
        kReward(t.reward_text, t.reward_type) + '</div></div>';
    });
  }
  const fresh = (hl && hl.hall || []).filter(x => x.can_claim);
  if (fresh.length) {
    h += '<div class="row" data-go="hall" style="cursor:pointer">' +
      '<span class="icon-box" style="background:var(--blue-bg)">' + ic('i-task', 19, 'var(--blue-deep)') + '</span>' +
      '<div class="row-grow"><div class="row-title">大厅还有 ' + num(fresh.length) + ' 件能接</div>' +
      '<div class="row-sub">接了就进「我的任务」</div></div>' +
      ic('i-chevron', 16, 'var(--ink-line)') + '</div>';
  }

  // ⑤ 这题我不会。放在心愿上面：孩子开首页多半正写着作业，这一条要先被看见。
  h += kAskCard('help');

  // ⑥ 心愿
  const act = (ws && ws.items || []).filter(x => x.status === 'active');
  const w = act[0];
  if (w) {
    const p = w.progress || {};
    const pc = p.known && p.percent != null ? Math.max(0, Math.min(100, p.percent)) : 0;
    h += '<div class="row" data-go="wish" style="cursor:pointer">' +
      '<span class="icon-box" style="background:var(--pink-bg)">' + ic('i-wishstar', 20, 'var(--pink-deep)') + '</span>' +
      '<div class="row-grow"><div class="row-title">' + esc(w.title) + '</div>' +
      (p.known && !p.manual
        ? '<div class="h g8 mt6"><span class="bar" style="flex:1"><i style="width:' + pc + '%"></i></span>' +
          '<span class="num t-2" style="font-size:10.5px">' + esc(p.text || '') + '</span></div>'
        : '<div class="row-sub">' + esc(p.where || '等爸爸妈妈定条件') + '</div>') +
      '</div>' + ic('i-chevron', 16, 'var(--ink-line)') + '</div>';
  } else {
    h += '<div class="row" data-go="wish" style="cursor:pointer">' +
      '<span class="icon-box" style="background:var(--pink-bg)">' + ic('i-wishstar', 20, 'var(--pink-deep)') + '</span>' +
      '<div class="row-grow"><div class="row-title">想要点什么？</div>' +
      '<div class="row-sub">写下来挂到心愿屋，爸爸妈妈给你定条件</div></div>' +
      ic('i-chevron', 16, 'var(--ink-line)') + '</div>';
  }

  // ⑦ 最近发生。接口本来就只回自己那一份（member_id 从会话里来），不用在这儿筛。
  //    原来是整块只报最新那一条的灰字：看得到「刚发生了什么」，看不到「这几天
  //    都在发生什么」。改成三条胶囊，每条前面挂一个来源小符号。
  const rec = (fd && fd.recent || []).slice(0, 3);
  if (rec.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-clock', 16, 'var(--purple)') + '最近发生</span>' +
      '<span class="sect-note">和我有关的</span></div>' +
      '<div class="card card--tight kfeed">' + rec.map(x => {
        const s = K_FEED_SRC[x.kind] || K_FEED_SRC.given;
        return '<div class="kfeed-row" style="background:' + s.bg + '">' +
          '<span class="kfeed-ic">' + ic(s.icon, 16, s.fg) + '</span>' +
          '<span class="kfeed-tx">' + esc(x.text) + '</span>' +
          '<span class="kfeed-ts">' + esc(kAgo(x.ts)) + '</span></div>';
      }).join('') + '</div>';
  }
  return kShell({}, h);
}

/* ============================================================ 任务（我的任务） */
async function kScreenTask() {
  const mid = S.me.id;
  const hl = await api('GET', '/api/tasks/hall');
  const act = await kg('/api/activity?group=given&days=1&limit=60');
  const hs = await kg('/api/tasks/mine?days=30');
  const mine = (hl.doing || []).filter(t => t.assignee_id === mid);
  const doing = mine.filter(t => t.status !== 'submitted');   // 待做 + 在做，两种都是手上的活
  const waits = mine.filter(t => t.status === 'submitted');
  const fresh = (hl.hall || []).filter(x => x.can_claim);
  const doneToday = ((act && act.items) || []).filter(x => String(x.kind || '').indexOf('task_') === 0);

  let h = '<div class="seg">' +
    '<button class="seg-item is-on">我的任务</button>' +
    '<button class="seg-item" data-go="hall">任务大厅' +
    (fresh.length ? ' · ' + fresh.length : '') + '</button></div>';

  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-clock', 16, 'var(--purple)') + '在做</span>' +
    '<span class="sect-note">' + num(doing.length) + ' 件 · 做完点「交上去」</span></div>';
  if (!doing.length) h += '<div class="card"><div class="empty">手上没有要做的活</div></div>';
  doing.forEach(t => {
    h += '<div class="task-card"><div class="task-row">' +
      '<span class="task-ico">' + glyph(t.icon, 'task', 20) + '</span>' +
      '<span class="task-name">' + esc(t.title) + '</span>' +
      kReward(t.reward_text, t.reward_type) + '</div>' +
      (t.std ? '<div class="task-sub" style="margin:0">' + esc(t.std) + '</div>' : '') +
      '<div class="hb"><span class="h g7">' + kDots(t.status) +
      '<span class="t-2" style="font-size:10.5px">' + (K_TASK_STATE[t.status] || '在做') +
      (t.deadline ? ' · ' + esc(kDeadline(t.deadline)) + ' 前交上去' : ' · 今天之内') + '</span></span>' +
      '<span class="h g6">' +
      '<button class="btn btn--sm" data-tdone="' + t.id + '">交上去</button>' +
      // 「不做了」只给大厅里领来的那份：引擎里 task_abandon 只认 claimed，
      // 家长直接派下来的活不能推掉。按钮跟着引擎走，免得点了报错。
      (t.status === 'claimed'
        ? '<button class="btn btn--sm line" data-tgive="' + t.id + '">不做了</button>' : '') +
      '</span></div></div>';
  });

  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-check', 16, 'var(--orange)') + '等爸爸妈妈确认</span>' +
    '<span class="sect-note">' + num(waits.length) + ' 件 · 点头就发奖励</span></div>';
  if (!waits.length) h += '<div class="card"><div class="empty">没有在等确认的</div></div>';
  waits.forEach(t => {
    h += '<div class="task-card"><div class="task-row">' +
      '<span class="task-ico" style="background:var(--purple-bg)">' + glyph(t.icon, 'task', 20) + '</span>' +
      '<span class="task-name">' + esc(t.title) + '</span>' +
      kReward(t.reward_text, t.reward_type) + '</div>' +
      '<span class="h g7">' + kDots('submitted') +
      '<span class="t-2" style="font-size:10.5px">已经交上去 · 等爸爸妈妈点头' +
      (t.deadline ? '，最晚 ' + esc(kDeadline(t.deadline)) : '') + '</span></span></div>';
  });

  if (doneToday.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-check', 16, '#7BC49A') + '今天已完成</span>' +
      '<span class="sect-note">' + num(doneToday.length) + ' 件 · 奖励已到账</span></div>';
    doneToday.slice(0, 6).forEach(x => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:var(--ok-bg)">' + ic('i-check', 18, '#3E9E68') + '</span>' +
        '<div class="row-grow"><div class="row-title">' + esc(x.text) + '</div>' +
        '<div class="row-sub">' + esc(String(x.ts || '').slice(5, 16)) +
        (x.by ? ' · ' + esc(x.by) + '确认了' : '') + '</div></div>' +
        (x.impact ? '<span class="num" style="font-size:11px;color:var(--gold-deep)">' +
          esc(x.impact) + '</span>' : '') + '</div>';
    });
  }

  // 任务记录。原来这儿只有一行小灰字「看看我的全部记录 ›」，点了跳到「我的记录」，
  // 那页讲的是「哪一项这几天怎么走的」，跟任务没关系 —— 想看「我那件活后来怎么了」
  // 反而没地方去。改成把最近三条直接摆在这儿，想看全部再展开半屏列表。
  const hist = (hs && hs.items) || [];
  if (hist.length) {
    const show = hist.slice(0, 3);
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-clock', 16, 'var(--blue-deep)') + '任务记录</span>' +
      '<span class="sect-note">最近 ' + num(show.length) + ' 条 · 近一个月</span></div>' +
      '<div class="card">' + show.map(kTaskHistRow).join('') + '</div>';
    if (hist.length > show.length) {
      h += '<button class="btn wide line" id="kHistMore">展开全部 ' + num(hist.length) +
        ' 条 ›</button>';
    }
  }
  return kShell({}, h);
}

/* 任务记录的一行。状态一个不藏：在做、等确认、已完成、被退回、已放弃、已撤回
   都在这儿，颜色分得开。孩子要的是「我那些活后来怎么了」，只报成功的记录
   等于没记 —— 放下的那件也是他做过的决定。 */
const K_TASK_HIST = {
  pending:   { t: '待做',   bg: 'var(--blue-bg)',   fg: 'var(--blue-deep)',   ic: 'i-task' },
  claimed:   { t: '在做',   bg: 'var(--blue-bg)',   fg: 'var(--blue-deep)',   ic: 'i-task' },
  submitted: { t: '等确认', bg: 'var(--purple-bg)', fg: 'var(--purple-deep)', ic: 'i-check' },
  confirmed: { t: '已完成', bg: 'var(--ok-bg)',     fg: 'var(--ok)',          ic: 'i-check' },
  returned:  { t: '被退回', bg: 'var(--warn-bg)',   fg: 'var(--warn)',        ic: 'i-back' },
  abandoned: { t: '已放弃', bg: 'var(--line)',      fg: 'var(--ink-3)',       ic: 'i-back' },
  archived:  { t: '已撤回', bg: 'var(--line)',      fg: 'var(--ink-3)',       ic: 'i-back' },
};
function kTaskHistRow(t) {
  const st = K_TASK_HIST[t.status] || K_TASK_HIST.pending;
  const when = t.touched_at || t.created_at || '';
  return '<div class="ktrec">' +
    '<span class="icon-box" style="background:' + st.bg + '">' + ic(st.ic, 17, st.fg) + '</span>' +
    '<div class="row-grow"><div class="row-title">' + esc(t.title) +
    (t.kind === 'repair' ? '<span class="kt-repair">修复</span>' : '') + '</div>' +
    '<div class="row-sub">' + esc(kAgo(when)) +
    (t.hall_id ? ' · 大厅领的' : ' · 派下来的') + '</div></div>' +
    '<span class="kts" style="background:' + st.bg + ';color:' + st.fg + '">' + st.t + '</span></div>';
}

/* 任务记录全部。sheet 本来就是半屏，正好。最多回溯近一个月 ——
   再往前的翻起来没意义，也没人在乎三个月前放下的那件事。 */
async function kTaskHistSheet() {
  const d = await kg('/api/tasks/mine?days=30');
  const items = (d && d.items) || [];
  sheet('<h3>任务记录</h3>' +
    '<p class="muted">近一个月经你手的活，做完的、放下的都在。新的排最上面。</p>' +
    (items.length
      ? '<div class="card">' + items.map(kTaskHistRow).join('') + '</div>'
      : '<p class="muted">这一个月还没有经你手的活。</p>'),
    function () {});
}

/* ============================================================ 任务大厅 */
async function kScreenHall() {
  const mid = S.me.id;
  const d = await api('GET', '/api/tasks/hall');
  const fresh = (d.hall || []).filter(x => x.can_claim);
  // 这个数得和「我的任务」里那份「在做」列表同源：待做 + 在做，不含交了等确认的。
  // 两边不同源的话，大厅头上一句「你在做 1 件」，点进去一看是 0 件，孩子会以为丢了。
  const mineDoing = (d.doing || []).filter(t => t.assignee_id === mid && t.status !== 'submitted');

  let h = '<div class="seg">' +
    '<button class="seg-item" data-go="task">我的任务</button>' +
    '<button class="seg-item is-on">任务大厅' + (fresh.length ? ' · ' + fresh.length : '') +
    '</button></div>';

  h += '<div class="card card--tight"><div class="h g10">' +
    ic('i-stardust', 18, 'var(--stardust)') +
    '<div class="grow v g5">' +
    '<div class="hb"><span style="font-size:11.5px;font-weight:600">大厅里现在有 ' +
    num(fresh.length) + ' 件能接</span>' +
    '<span class="num" style="font-size:11.5px;color:var(--orange)">你在做 ' +
    num(mineDoing.length) + ' 件</span></div>' +
    '<div class="t-3" style="font-size:10px">接了就进「我的任务」，做完交上去等爸爸妈妈点头</div>' +
    '</div></div></div>';

  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-task', 16, 'var(--blue-deep)') + '可以接的任务</span>' +
    '<span class="sect-note">满员就没了</span></div>';
  if (!fresh.length) h += '<div class="card"><div class="empty">大厅里暂时没有新的</div></div>';
  fresh.forEach(x => {
    const who = (x.claims || []).filter(c => c.status !== 'abandoned');
    const slots = +x.slots;
    const slotPill = (slots === 1)
      ? '<span class="pill pill--purple" style="padding:4px 9px;font-weight:500">单人 · 只有 1 个</span>'
      : '<span class="pill pill--blue" style="padding:4px 9px;font-weight:500">每人一份' +
        (who.length ? ' · ' + who.length + ' 人在做' : '') + '</span>';
    h += '<div class="task-card"><div class="task-row">' +
      '<span class="task-ico" style="background:var(--blue-bg)">' + glyph(x.icon, 'task', 20) + '</span>' +
      '<div class="grow v" style="gap:4px"><div class="task-name">' + esc(x.title) + '</div>' +
      (x.std ? '<div class="t-2" style="font-size:10.5px">' + esc(x.std) + '</div>' : '') + '</div>' +
      kReward(x.reward_text, x.reward_type) + '</div>' +
      '<div class="hb"><span class="h g6">' + slotPill +
      (x.deadline ? '<span class="t-3" style="font-size:10.5px">' + esc(x.deadline) + ' 前可接</span>'
        : (who.length ? '<span class="t-3" style="font-size:10.5px">' +
          esc(who.map(c => c.who).join('、')) + '在做</span>' : '')) +
      '</span><button class="btn btn--sm" data-tclaim="' + x.id + '">接过来</button></div></div>';
  });

  // 别人手上的。先到先得被领走之后母记录就满了、不再出现在 hall 里，
  // 所以这一层不能只从 hall 取，得把「进行中」里别人的那几份也捡回来，
  // 否则最该被看见的那种（已经被人抢走了）恰好是唯一看不见的。
  const rows = [];
  (d.hall || []).filter(x => !x.can_claim && !x.mine).forEach(x => {
    const who = (x.claims || []).filter(c => c.status !== 'abandoned');
    rows.push({
      title: x.title, icon: x.icon, full: x.full,
      tag: +x.slots === 1 ? '单人' : '每人一份',
      who: who.map(c => esc(c.who) + kTaskTag(c.status))
        .join('、') || '还留得下位置',
    });
  });
  (d.doing || []).filter(t => t.assignee_id !== mid).forEach(t => rows.push({
    title: t.title, icon: t.icon, full: false, tag: t.hall_id ? '大厅' : '派下来的',
    who: esc(t.who || '') + kTaskTag(t.status),
  }));
  if (rows.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-me', 16, 'var(--purple)') + '已经被人接了</span>' +
      '<span class="sect-note">等着看谁先做完</span></div>';
    rows.forEach(x => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:var(--purple-bg)">' + glyph(x.icon, 'task', 19) + '</span>' +
        '<div class="row-grow"><div class="row-title">' + esc(x.title) +
        (x.full ? ' <span class="pill pill--gray" style="padding:2px 7px">满了</span>' : '') + '</div>' +
        '<div class="row-sub">' + x.who + '</div></div></div>';
    });
  }
  if ((d.done || []).length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-check', 16, 'var(--ink-3)') + '已经结束了</span>' +
      '<span class="sect-note">' + num(d.done.length) + ' 件</span></div>';
    d.done.forEach(x => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:#F4EFE7">' + glyph(x.icon, 'task', 19) + '</span>' +
        '<div class="row-grow"><div class="row-title">' + esc(x.title) + '</div>' +
        '<div class="row-sub">' + (x.done ? num(x.done) + ' 人交成功' : '没人交') +
        (x.quit ? ' · ' + num(x.quit) + ' 次被放回' : '') + '</div></div></div>';
    });
  }

  h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') +
    '接过来的任务会出现在「我的任务」里；中途不想做了随时可以放回去，不扣分</div>';
  return kShell({}, h);
}

/* ============================================================ 宝箱 */
async function kScreenChest() {
  const mid = S.me.id;
  const d = await api('GET', '/api/boxes?member_id=' + mid);
  const shop = await kg('/api/shop?member_id=' + mid);

  const c = d.cycle || {};
  const tiers = d.tiers || [];
  const top = tiers.length ? tiers[tiers.length - 1].threshold : 49;
  const energy = +c.energy || 0;
  const cur = c.tier, nt = c.next_tier;
  const lockName = kBoxName(cur) || '还没有箱子';
  // 保底说的是「手上这只箱子」会给什么，不是下一档。状态行已经报了还差多少分，
  // 保底行再报下一档的话，同一张卡上两行在讲两件不同的事。
  const curT = (cur ? tiers.filter(t => t.tier === cur.tier)[0] : null)
    || (nt ? tiers.filter(t => t.threshold === nt.threshold)[0] : null);
  const guar = curT
    ? (num(curT.tickets) + ' 张娱乐券' + (curT.card_count ? ' + ' + num(curT.card_count) + ' 张卡' : ''))
    : '';
  // 状态行的三种样子：手上真有箱待开 / 这周已经领过 / 还锁着。
  // 「有没有箱」排在「结没结算」前面 —— 结算完但还没开掉的那只，说的是「可以开啦」。
  const pend = (d.pending || []);
  const p0 = pend[0];
  const settled = !!(c.status && c.status !== 'open');
  const stLock = !p0 && !settled;
  const stName = p0 ? '可以开啦' : (settled ? '本周已领' : '已锁定');
  const stSub = p0 ? '点我开箱，看看有什么'
    : (settled ? '下周六结算再发'
      : (nt ? '还差 ' + num(nt.need) + ' 分到' + kBoxName(nt) : '这一周刚开始，慢慢来'));

  let h = '<div class="appbar">' +
    '<span class="appbar-grow appbar-title">我的宝箱</span>' +
    '<span class="h g5"><span class="t-2" style="font-size:10.5px">本周能量</span>' +
    '<span class="num" style="font-size:16px;color:var(--orange)">' +
    num(energy) + '/' + num(top) + '</span></span></div>';

  // 有箱待开：胶囊摆在最上面。箱子里有什么是点开那一刻才抽的（v38），
  // 所以它只报「有一只，点我」—— 先把结果写在上面就没悬念了。
  // 点它时要知道这是「还没开」还是「开了没挑完」：后一种再往开箱接口走会被后端拒
  // （那箱已经算开过了）。整行先存着，点击时取回来。
  S.pendBoxes = pend;
  if (p0) {
    const openable = p0.state !== 'unpicked';
    const pt = tiers.filter(t => t.tier === p0.tier)[0] || {};
    h += '<button class="chest-pod" data-openbox="' + p0.box_id + '" data-tier="' + p0.tier +
      '" data-state="' + esc(p0.state || '') + '">' +
      ic(kBoxIcon(p0.tier), 28) +
      '<span class="chest-pod-g">' +
      '<span class="chest-pod-t">' + (openable
        ? '叮！你有 ' + num(pend.length) + ' 个宝箱可以打开'
        : '还有 ' + num(p0.need) + ' 张卡没挑完') + '</span>' +
      '<span class="chest-pod-s">' + (openable
        ? esc(p0.name) + (pt.threshold ? ' · 上周攒到 ' + num(pt.threshold) + ' 分' : '')
        : '挑完它才算真的到手') + '</span></span>' +
      '<span class="chest-pod-go">点我打开</span></button>';
  }

  h += '<div class="hero" style="padding:15px">' +
    '<div class="hb">' +
    '<span class="pill pill--white" style="gap:6px;padding:5px 11px">' +
    (stLock ? ic('i-lock', 11, '#fff') : '') +
    '<span style="font-size:13px;font-weight:700">' +
    esc(stName + ' · ' + lockName) + '</span></span>' +
    '<span style="font-size:12px;font-weight:700">' + esc(stSub) + '</span></div>' +
    '<div class="box-figure">' +
    ic(kBoxIcon(cur ? cur.tier : (nt ? nt.tier : 1)), 118) +
    ic('i-star', 16, 'rgba(255,255,255,.50)') +
    ic('i-star', 12, 'rgba(255,255,255,.40)') +
    ic('i-star', 10, 'rgba(255,255,255,.34)') +
    ic('i-star', 14, 'rgba(255,255,255,.44)') +
    '</div>' +
    kSlots(energy, tiers).replace('class="chest-slots"', 'class="chest-slots" style="margin:12px 0"') +
    (guar ? '<div class="h g8">' + ic('i-star', 12, '#FFE9A8') +
      '<span style="font-size:12px;font-weight:700">' +
      esc(kBoxName(curT)) + '保底 · ' + esc(guar) + '</span></div>' : '') +
    '</div>';

  // 七档宝箱：七列并排，一列一档。列里从上到下 = 箱图标、档名、门槛分、两行内容。
  // 原来这里是「一条横向阶梯 + 卡下七行明细」，同一件事写了两遍 ——
  // 阶梯只说它叫什么，明细才说它给什么，孩子得把上下两处对起来才看得懂。
  h += '<div class="card"><div class="hb" style="margin-bottom:12px">' +
    '<span class="card-title">七档宝箱</span>' +
    '<span class="card-note">能量到了自己往上爬</span></div>' +
    '<div class="btcols">' + tiers.map(t => kTierCol(t, cur)).join('') + '</div>' +
    '<hr class="rule">' +
    '<div class="btnote">随机掉稀有道具：金箱 10% · 钻石箱 20% · 王者箱 40% · ' +
    '完美箱 70%（其他宝箱没有随机道具）</div></div>';

  // 星尘直接买
  const boxes = (shop && shop.boxes) || [];
  if (boxes.length) {
    const left = Math.max(0, (shop.box_limit || 0) - (shop.box_used || 0));
    h += '<div class="card"><div class="hb" style="margin-bottom:12px">' +
      '<span class="card-title">星尘直接买</span>' +
      '<span class="card-note">每周期最多 1 次 · 还能买 ' + num(left) + ' 个</span></div>' +
      '<div class="grid3" style="gap:8px">' + boxes.map(b => {
        const can = left > 0 && d.stardust >= b.price;
        return '<button class="card--buy" data-box="' + b.tier + '" data-p="' + b.price + '"' +
          (can ? '' : ' disabled') + '>' +
          ic(kBoxIcon(b.tier), 22) +
          '<span class="v" style="gap:3px;align-items:flex-start">' +
          '<span style="font-size:10.5px;font-weight:700">' + esc(kBoxName(b)) + '</span>' +
          '<span class="h" style="gap:2px">' + ic('i-stardust', 9, 'var(--stardust)') +
          '<span class="num" style="font-size:11px;color:var(--orange)">' + num(b.price) +
          '</span><span class="t-3" style="font-size:9px">星尘</span></span></span></button>';
      }).join('') + '</div>' +
      '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:11px">' +
      '买来的箱不含随机件，开不出传说与钻石级卡；木铜银与完美箱不卖。' +
      '付完星尘当场开，同样有开箱动画</div></div>';
  }

  // 这里原来还有一段「最近开出来的」列表，每条挂一个「重抽」按钮。撤了：
  // 开箱那一刻结果屏上已经有重抽入口，宝箱页再留一份历史，这一页的重心就从
  // 「还有什么能开」变成「以前开过什么」，而孩子来这一页是看前者。
  return kShell({}, h);
}

/* 七档各给什么，一列一档（v39）。从上到下：箱图标、档名、门槛分、两行内容。
   木铜银没有卡，那一行就不画 —— 写「+0 卡」比不写更像在敷衍。
   随机件的概率不在这七列里，挪到卡片最后那一句统一说，免得七列各自带一串百分比。 */
const BTIER_COLOR = {
  1: '#A9754A', 2: '#B07B4A', 3: '#7C8794', 4: '#B57A1F',
  5: '#2E8CA5', 6: '#7B4FB0', 7: '#D6537F',
};
function kTierCol(t, curTier) {
  const cards = (t.cards || []).reduce((a, x) => a + (+x.count || 0), 0) || (+t.card_count || 0);
  const c = BTIER_COLOR[t.tier] || 'var(--ink)';
  const now = !!(curTier && curTier.tier === t.tier);
  return '<div class="btcol' + (now ? ' is-now' : '') + '">' +
    ic(kBoxIcon(t.tier), 28) +
    '<div class="btcol-n" style="color:' + c + '">' + esc(t.name) + '</div>' +
    '<div class="btcol-s" style="color:' + c + '">' + num(t.threshold) + '</div>' +
    '<div class="btcol-d">' + num(t.tickets) + ' 券</div>' +
    (cards ? '<div class="btcol-d">+' + num(cards) + ' 卡</div>' : '') +
    '</div>';
}

/* 开箱结果里的一行。接口给的 given 有五六种形状，全在这里收口 ——
   开箱、重抽、自选三处都画同一份东西，各写一遍迟早少一样。 */
function kGivenLine(g) {
  if (!g) return '';
  if (g.type === 'ticket') return '娱乐券 ×' + num(g.qty);
  if (g.type === 'stardust') return '星尘 +' + num(g.qty);
  if (g.type === 'card') {
    return (RAR[g.rarity] || '') + '卡「' + esc(g.name) + '」' +
      (g.picked ? ' · 你自己挑的' : '') +
      (g.fragment ? '（超出上限，拆成 ' + num(g.fragment) + ' 碎片）' : '');
  }
  if (g.type === 'diamond') return '钻石级「' + esc(g.name) + '」';
  if (g.type === 'random') return '随机件：' + esc(g.label || g.name || '');
  return esc(g.name || '');
}

/* ============================================================ 开箱这一套（v38） */
/* 结算只发箱子，箱子里有什么是点开那一刻才抽的。所以开箱是一段有过程的动作，
   不是一次静默发货：四拍动画，然后铺结果。直购箱付完星尘当场开，走同一段。
   两条路的差别只在「开头有没有那四拍」，结果屏是同一张 —— 各写一份的话，
   打出来的箱和买来的箱迟早有一边少显示一样东西。 */

/* 四拍：搬过来 → 晃一晃 → 发光 → 开。总长压在 2.2 秒上下。
   再长就不像「打开了」，像在下载。返回 Promise，动画走完才 resolve。 */
function kPlayOpen(tier) {
  return new Promise(resolve => {
    sheet('<div class="box-stage is-in" id="kStage">' +
      '<span class="box-stage-in" id="kStageIn">' + ic(kBoxIcon(tier), 96) + '</span>' +
      '<span class="box-stage-tip" id="kStageTip">把箱子搬过来</span></div>');
    const st = $('#kStage'), tip = $('#kStageTip');
    const beat = (cls, text, ms) => new Promise(r => {
      if (st) st.className = 'box-stage ' + cls;
      if (tip) tip.textContent = text;
      setTimeout(r, ms);
    });
    (async () => {
      await beat('is-in', '把箱子搬过来', 500);
      await beat('is-shake', '晃一晃，里面有东西在响', 560);
      await beat('is-glow', '有亮光从缝里冒出来', 560);
      await beat('is-burst', '开！', 460);
      resolve();
    })();
  });
}

/* 「点我打开」走这条。抽什么是接口那一刻定的（在后端），动画跟它并行跑 ——
   孩子看到的是箱子在动，不是转圈等接口。 */
async function kOpenBoxFlow(boxId, tier, row) {
  // 开了、自选还没挑完的那只：箱子里别的东西早就到手了，这一屏只补「接着挑」。
  // 再往 /open 走会被后端拒（那一箱已经算开过了），孩子只会看到一句看不懂的报错。
  if (row && row.state === 'unpicked') {
    kOpenResult({ box_id: boxId, name: row.name,
                  need_pick: { qty: row.need || 1, options: row.options || [] } });
    return;
  }
  try {
    const [r] = await Promise.all([
      api('POST', '/api/boxes/' + boxId + '/open', {}),
      kPlayOpen(+tier || 1),
    ]);
    kOpenResult(r);
  } catch (e) { closeSheet(); err(e); await render(); }
}

/* 直购箱那边（app.js 的 confirmBuyBox）付完星尘接这一段。
   app.js 先加载、这里的名字还不存在，所以它用 typeof 兜了一下。 */
async function kOpenBoxAnimThenShow(r) {
  await kPlayOpen((r && r.tier) || 1);
  kOpenResult(r);
}

/* 开箱结果。有自选件就把候选摆在这一屏底下，挑完才算真的到手 ——
   再跳一层「挑卡」页的话，孩子很可能在半路退出去，那几张就悬着。 */
function kOpenResult(r) {
  const given = (r.given || []).map(kGivenLine).filter(Boolean);
  const need = (r.need_pick && (r.need_pick.options || []).length) ? r.need_pick : null;
  // resume：这一箱早就开过了，东西也已经在手上，只是那几张自选还悬着。
  // 再写「开出来了」是在骗他 —— 什么都没重开。
  const head = r.resume ? '接着把这只箱挑完'
    : (esc(r.name || '宝箱') + ' 开出来了');
  let h = '<h3>' + head + '</h3><div class="hr"></div>';
  if (given.length) {
    h += given.map(x => '<div class="kv"><span class="k">·</span>' +
      '<span class="v" style="text-align:right">' + x + '</span></div>').join('');
  }
  if (r.note) h += '<div class="notice" style="margin-top:10px">' + esc(r.note) + '</div>';

  if (!need) {
    h += '<button class="btn wide" id="kOk" style="margin-top:14px">知道了</button>';
    sheet(h, box => {
      // 关掉之后要重画一遍宝箱页：那只箱子已经开过了，提醒卡不能还挂着。
      $('#kOk', box).addEventListener('click', async () => { closeSheet(); await render(); });
    });
    return;
  }

  const qty = Math.max(1, +need.qty || 1);
  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-cards', 16, 'var(--purple-deep)') + '挑 ' + num(qty) + ' 张带走</span>' +
    '<span class="sect-note">点一下选中，再点一下取消</span></div>' +
    '<div class="grid2">' + need.options.map(o =>
      '<button type="button" class="pick-card" data-pick="' + esc(o.code) + '">' +
      '<span class="icon-box" style="background:var(--purple-bg);margin:0 auto">' +
      glyph(o.icon, 'card', 22) + '</span>' +
      '<span class="pick-name">' + esc(o.name) + '</span>' +
      '<span class="pick-desc">' + esc(o.desc || '') + '</span></button>').join('') + '</div>' +
    '<button class="btn wide" id="kPickGo" disabled style="margin-top:14px"></button>' +
    '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:8px">' +
    '挑完就不能改了。这一箱里别的东西已经在你手上了。</div>';

  sheet(h, box => {
    const cells = $$('.pick-card', box);
    const go = $('#kPickGo', box);
    let sel = [];
    const sync = () => {
      cells.forEach(c => c.classList.toggle('on', sel.indexOf(c.dataset.pick) >= 0));
      const left = qty - sel.length;
      go.disabled = left > 0;
      go.textContent = left > 0 ? ('还差 ' + num(left) + ' 张，选好了才能按') : '就这 ' + num(qty) + ' 张';
    };
    cells.forEach(c => c.addEventListener('click', () => {
      const code = c.dataset.pick;
      const at = sel.indexOf(code);
      if (at >= 0) sel.splice(at, 1);
      else if (sel.length < qty) sel.push(code);
      else return;                 // 挑满了再点别的没反应，不把先选的挤掉
      sync();
    }));
    go.addEventListener('click', async () => {
      if (go.disabled || sel.length !== qty) return;
      go.disabled = true;
      try {
        const res = await api('POST', '/api/boxes/' + r.box_id + '/pick', { codes: sel });
        const lines = (res.given || []).map(kGivenLine).filter(Boolean);
        sheet('<h3>收好了</h3><div class="hr"></div>' +
          lines.map(x => '<div class="kv"><span class="k">·</span>' +
            '<span class="v" style="text-align:right">' + x + '</span></div>').join('') +
          '<button class="btn wide" id="kOk" style="margin-top:14px">知道了</button>',
          b => {
            $('#kOk', b).addEventListener('click', async () => {
              closeSheet(); await render();
            });
          });
      } catch (e) { err(e); go.disabled = false; sync(); }
    });
    sync();
  });
}

/* ============================================================ 券包 · 我的券 */
async function kScreenCoupon() {
  const mid = S.me.id;
  const hold = await api('GET', '/api/holdings?member_id=' + mid);
  const st = await kg('/api/tickets/state?member_id=' + mid);
  const tks = await kg('/api/tickets/mine?member_id=' + mid);
  const shop = await kg('/api/shop?member_id=' + mid);
  const cash = await kg('/api/cash?member_id=' + mid);

  const owned = {};
  (hold.tickets || []).forEach(t => { owned[t.code] = t; });
  const cat = (shop && shop.tickets) || (hold.tickets || []);
  const total = (hold.tickets || []).reduce((a, t) => a + (+t.qty || 0), 0);
  const debt = st ? (+st.debt || 0) : 0;

  let h = '<div class="seg">' +
    '<button class="seg-item is-on">我的券</button>' +
    '<button class="seg-item" data-go="shop">券商店</button></div>';

  // 券的状态：等审核 / 上次没同意 / 正在玩。这些是「眼下正在发生」的事，
  // 摆在这一页最上面 —— 埋在清单下面，等于没有。
  const playing = (tks && tks.playing || [])[0];
  const items = (tks && tks.items) || [];
  const pend = items.filter(x => x.status === 'pending')[0];
  const rjs = items.filter(x => x.status === 'rejected');
  const lastReject = rjs[rjs.length - 1];
  const ejs = items.filter(x => x.status === 'expired');
  const lastExpire = ejs[ejs.length - 1];
  if (playing) {
    h += '<div class="card tk-run" data-tkend="' + esc(playing.end_at) + '" data-tktotal="' +
      num(playing.total_minutes || 0) + '">' +
      '<div class="hb"><span class="h g6">' + ic('i-clock', 15, 'var(--purple-deep)') +
      '<span style="font-size:11.5px;font-weight:700;color:var(--purple-deep)">正在玩</span></span>' +
      '<span class="num tk-big" data-tkleft>' +
      esc(tkLeftText(tkLeftMs(playing.end_at))) + '</span></div>' +
      '<div class="bar bar--purple" style="margin-top:9px"><i data-tkbar style="width:0%"></i></div>' +
      '<div class="t-2 mt8" style="font-size:10.5px">' + esc(playing.item || '') +
      (playing.qty ? ' ×' + num(playing.qty) : '') +
      '　到 ' + esc(String(playing.end_at).slice(11, 16)) + ' 结束</div></div>';
  }
  if (pend) {
    h += '<div class="card tk-pend" data-tkexp="' + esc(pend.expire_at) + '">' +
      '<div class="hb"><span class="row-title">等爸爸妈妈点一下</span>' +
      '<span class="pill pill--gray">' + esc(miniLeft(pend.expire_at)) + '</span></div>' +
      '<div class="t-2 mt6" style="font-size:10.5px">' + esc(pend.item || '') +
      (pend.qty ? ' ×' + num(pend.qty) : '') +
      (pend.minutes ? '　' + num(pend.minutes) + ' 分钟' : '') + '</div>' +
      '<div class="t-3 mt6" style="font-size:10px">他们的手机上会响一下。过了这个时间这条会自己作废，可以重新提。</div></div>';
  }
  if (lastReject) {
    h += '<div class="card tk-judge">' +
      '<div class="hb"><span class="row-title">上次没同意</span>' +
      '<span class="t-3" style="font-size:10px">' +
      esc(String(lastReject.ts || '').slice(11, 16)) + ' 提的</span></div>' +
      '<div class="tk-no" style="margin-top:7px">' +
      esc(lastReject.reject_note || '（没写理由）') + '</div></div>';
  } else if (lastExpire) {
    h += '<div class="card"><div class="t-2" style="font-size:10.5px">' +
      esc(String(lastExpire.ts || '').slice(11, 16)) + ' 提的那条 ' + esc(lastExpire.item || '') +
      ' 等太久作废了。想玩重新提一条。</div></div>';
  }

  if (debt > 0) {
    h += '<div class="tip">' + ic('i-clock', 15, '#D18A3C') +
      '欠 ' + num(debt) + ' 分钟 · 下次发的券先拿一部分去还</div>';
  }
  if (hold.debt > 0) {
    h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') +
      '还欠 ' + num(hold.debt) + ' 星尘，下次结算时先扣</div>';
  }

  // 今天的额度快照
  if (st) {
    h += '<div class="card"><div class="hb" style="margin-bottom:12px">' +
      '<span class="card-title">今天还能玩多少</span>' +
      '<span class="card-note">' + esc(st.curfew) + ' 收工</span></div>' +
      '<div class="grid3" style="text-align:center">' +
      '<div class="v g3"><span class="num" style="font-size:17px;color:var(--purple-deep)">' +
      num(st.max_qty_now) + ' 张</span><span class="t-2" style="font-size:10px">现在能要</span></div>' +
      '<div class="v g3"><span class="num" style="font-size:17px;color:var(--purple-deep)">' +
      num(st.round_cap) + ' 张</span><span class="t-2" style="font-size:10px">一轮最多</span></div>' +
      '<div class="v g3"><span class="num" style="font-size:17px;color:var(--ink-3)">' +
      num(st.used_total) + ' 张</span><span class="t-2" style="font-size:10px">今天已用</span></div>' +
      '</div>' +
      '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:12px">' +
      '一轮最多 ' + num(st.round_cap) + ' 张，' + num(st.renew_within_minutes) +
      ' 分钟内可以接着续；一轮结束（用满，或者没接着续）要休息 ' +
      num(st.cooldown_minutes) + ' 分钟' +
      (st.cooldown_left > 0 ? '（还要等 ' + num(st.cooldown_left) + ' 分钟）' : '') +
      '；到点会自动结束，不用自己点' +
      (st.weekend_double ? '。今天一张券算 ' + num(st.minutes) + ' 分钟，因为是周末' : '') +
      '</div></div>';
  }

  // 想多玩一会儿：它延长的就是下面那张券，贴着摆。位置在清单标题上面，
  // 免得被一长串券挤到屏幕外头，等于把唯一的正经通道又埋回去。
  h += kAskCard('ot');

  // 手上的券：六种都摆出来，×0 的置灰 —— 「豁免券用完了」和「从来没有过」
  // 对孩子是两件不同的事，摆着不动比整张卡消失诚实。
  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-coupon', 16, 'var(--pink-deep)') + '我手上的券</span>' +
    '<span class="sect-note">共 ' + num(total) + ' 张 · ' + num((hold.tickets || []).length) +
    ' 种</span></div>';
  if (!cat.length) {
    h += '<div class="card"><div class="empty">还没有券，去券商店看看</div></div>';
  } else {
    h += '<div class="grid2">' + cat.map(t => {
      const o = owned[t.code];
      const qty = o ? (+o.qty || 0) : 0;
      const isFun = t.code === 'ticket_fun';
      const ok = !isFun || (st && st.max_qty_now > 0);
      const typ = isFun ? (st && st.minutes ? num(st.minutes) + ' 分钟 / 张' : '娱乐时间')
        : (t.desc || '');
      return '<div class="coupon-card' + (qty ? '' : ' is-empty') + '">' +
        '<div class="hb"><span class="h g6">' + glyph(t.icon, 'ticket', 26) +
        '<span class="coupon-name">' + esc(t.name) + '</span></span>' +
        '<span class="cnt">×' + num(qty) + '</span></div>' +
        '<span class="coupon-desc">' + esc(typ) + '</span>' +
        (qty
          ? '<button class="btn btn--sm' + (ok ? '' : ' is-disabled') + '" data-tk="' + esc(t.code) +
            '" data-tkname="' + esc(t.name) + '" data-tkq="' + num(qty) + '"' +
            (ok ? '' : ' disabled') + '>' + (ok ? '去用' : '现在不行') + '</button>'
          : '<span class="coupon-desc t-3">用完了</span>') +
        '</div>';
    }).join('') + '</div>';
    if (st && st.max_qty_now <= 0) {
      h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') + esc(gateReason(st) || '现在还用不了') + '</div>';
    }
  }

  // 我手上的卡（v38：整段从「图鉴」搬过来）。图鉴只剩「收集到什么」这一层，
  // 能用的东西都摆在这一边、跟券挨着 —— 「我手上现在有什么能用的」应该
  // 一眼看全，而不是先去图鉴翻一层再找。
  const cards = (hold.cards || []);
  const cardQty = cards.reduce((a, c) => a + (+c.qty || 0), 0);
  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-cards', 16, 'var(--purple-deep)') + '我手上的卡</span>' +
    '<span class="sect-note">共 ' + num(cardQty) + ' 张 · ' + num(cards.length) +
    ' 种</span></div>';
  if (!cards.length) {
    h += '<div class="card"><div class="empty">还没有卡，开宝箱能开出来</div></div>';
  } else {
    cards.forEach(c => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:var(--purple-bg)">' + glyph(c.icon, 'card', 20) + '</span>' +
        '<div class="row-grow"><div class="row-title"><span class="rar-' + esc(c.rarity) + '">' +
        esc(c.name) + '</span> ×' + num(c.qty) + '</div>' +
        '<div class="row-sub">' + esc(c.desc) + ' · ' +
        (c.expires_at ? esc(c.expires_at) + ' 到期' +
          (c.days_left !== null && c.days_left <= 14 ? '（还剩 ' + num(c.days_left) + ' 天）' : '')
          : '永久') + '</div></div>' +
        '<button class="btn btn--sm" data-use="' + esc(c.effect) + '" data-hid="' +
        c.holding_id + '">用</button></div>';
    });
  }

  const exp = (hold.expiring || []);
  if (exp.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-clock', 16, 'var(--orange)') + '快到期的</span>' +
      '<span class="sect-note">续一次就再算 90 天</span></div>';
    exp.forEach(e => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:#FFF6E0">' + ic('i-coupon', 19, 'var(--gold-deep)') + '</span>' +
        '<div class="row-grow"><div class="row-title">' + esc(e.name) + '</div>' +
        '<div class="row-sub">' + esc(e.expires_at) + ' 到期，到期会折半转成星尘</div></div>' +
        '<button class="btn btn--sm line" data-renew="' + e.holding_id +
        '" data-cost="' + num(e.renew_cost) + '">续 ' +
        num(e.renew_cost) + '</button></div>';
    });
  }
  h += '<div class="footnote">' + ic('i-lock', 12, 'var(--ink-line)') +
    '用券要先过这一页上面的额度，再过爸爸妈妈那一关</div>';
  return kShell({}, h);
}

/* ============================================================ 券包 · 券商店 */
async function kScreenShop() {
  const mid = S.me.id;
  const d = await api('GET', '/api/shop?member_id=' + mid);
  const cash = await kg('/api/cash?member_id=' + mid);
  // /api/levels 回来的是 { tiers, level } 两层，等级在 .level 里
  const lvRes = await kg('/api/levels?member_id=' + mid);
  const lv = lvRes && lvRes.level;
  const tst = await kg('/api/tickets/state?member_id=' + mid);

  let h = '<div class="seg">' +
    '<button class="seg-item" data-go="coupon">我的券</button>' +
    '<button class="seg-item is-on">券商店</button></div>';

  h += '<div class="h g10" style="padding:0 2px">' +
    '<span class="h g6">' + ic('i-stardust', 14, 'var(--stardust)') +
    '<span class="num" style="font-size:16px">' + num(d.stardust) + '</span>' +
    '<span class="t-3" style="font-size:10.5px">可用星尘</span></span>' +
    (lv ? '<span class="pill pill--purple" style="padding:4px 10px">' +
      'Lv.' + lv.level + (lv.title ? ' · ' + esc(lv.title) : '') + '</span>' : '') +
    '</div>';

  if (tst && tst.armed && tst.armed.length) {
    h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') + '装填中：' +
      tst.armed.map(a => esc(a.name) + '（' + esc(a.desc) + '）').join('；') + '</div>';
  }
  if (tst && tst.flags && tst.flags.length) {
    h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') + '今天还在生效：' +
      tst.flags.map(f => esc(f.name) + ' — ' + esc(f.text)).join('；') + '</div>';
  }

  // 换零花钱：提一条申请，爸爸妈妈发钱，拿到手自己确认一下
  if (cash) {
    h += '<div class="row">' +
      '<span class="icon-box" style="background:#FFF6E0">' + ic('i-coin', 20, 'var(--gold-deep)') + '</span>' +
      '<div class="row-grow"><div class="row-title">换零花钱</div>' +
      '<div class="row-sub">1 星尘 = ' + num(cash.rate) + ' 元 · 本月还能换 ' +
      num(cash.left_cash) + ' 元（' + num(cash.left) + ' 星尘）</div></div>' +
      (cash.balance > 0
        ? '<button class="btn btn--sm" id="kExCash">去兑换</button>'
        : '<span class="t-3" style="font-size:10.5px">先攒点星尘</span>') + '</div>';
  }

  // 宝箱（v23 起买箱子的入口在商店页，不在「宝箱」栏；只卖金 / 钻石 / 王者三档）。
  // 明牌货：买来的箱子开不出随机件，这一句必须写在这儿，孩子站在价签前就得知道。
  const boxes = (d.boxes || []);
  if (boxes.length) {
    const bleft = Math.max(0, (+d.box_limit || 0) - (+d.box_used || 0));
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-chest-gold', 16, 'var(--orange)') + '宝箱也能买</span>' +
      '<span class="sect-note">每周期最多 ' + num(d.box_limit) + ' 个 · 还能买 ' +
      num(bleft) + ' 个</span></div>' +
      '<div class="card"><div class="grid3" style="gap:8px">' + boxes.map(b => {
        const can = bleft > 0 && d.stardust >= b.price;
        return '<button class="card--buy" data-box="' + b.tier + '" data-p="' + b.price + '"' +
          (can ? '' : ' disabled') + '>' + ic(kBoxIcon(b.tier), 22) +
          '<span class="v" style="gap:3px;align-items:flex-start">' +
          '<span style="font-size:10.5px;font-weight:700">' + esc(kBoxName(b)) + '</span>' +
          '<span class="h" style="gap:2px">' + ic('i-stardust', 9, 'var(--stardust)') +
          '<span class="num" style="font-size:11px;color:var(--orange)">' + num(b.price) +
          '</span><span class="t-3" style="font-size:9px">星尘</span></span></span></button>';
      }).join('') + '</div>' +
      '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:11px">' +
      '买来的箱不含随机件，开不出传说和钻石级的卡；打满分白拿的那个才有机会出</div></div>';
  }

  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-coupon', 16, 'var(--orange)') + '用星尘买券</span>' +
    '<span class="sect-note">限购的每周 1 张</span></div>';
  h += '<div class="grid2">' + (d.tickets || []).map(t => {
    const lim = t.weekly_limit
      ? '每周 ' + t.weekly_limit + ' 张 · 本周已买 ' + num(t.bought_this_cycle)
      : '不限购';
    const off = t.weekly_limit && t.bought_this_cycle >= t.weekly_limit;
    return '<div class="goods-card">' + glyph(t.icon, 'ticket', 32) +
      '<span class="coupon-name">' + esc(t.name) + '</span>' +
      '<span class="coupon-desc">' + esc(t.desc) + '</span>' +
      '<span class="coupon-desc">' + esc(lim) + (t.owned ? ' · 手上 ' + num(t.owned) + ' 张' : '') +
      '</span>' +
      '<button class="btn btn--sm' + (off ? ' is-disabled' : '') + '" data-t="' + esc(t.code) +
      '" data-p="' + t.price + '"' + (off ? ' disabled' : '') + '>' +
      (off ? '本周买过了' : num(t.price) + ' 星尘 · 买') + '</button></div>';
  }).join('') + '</div>';

  const reqs = (cash && cash.requests) || [];
  if (reqs.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-coin', 16, 'var(--gold-deep)') + '零花钱记录</span>' +
      '<span class="sect-note">最近 ' + num(reqs.length) + ' 条</span></div>';
    reqs.forEach(r => { h += cashReqRow(r); });
  }
  // 卡一张都不卖（v24）。这一句写在商店里，比写在别处有用：
  // 孩子站在这儿找卡，得当场知道「这里没有，去开箱」。
  h += '<div class="footnote">' + ic('i-lock', 12, 'var(--ink-line)') +
    '这里买到的都是明牌，没有随机件；随机件只在宝箱里出。卡也不卖，只能开箱开出。</div>';
  return kShell({}, h);
}

/* ============================================================ 成长报告 */
async function kScreenReport() {
  const mid = S.me.id;
  const cyc = await api('GET', '/api/cycle?member_id=' + mid);
  const dims = await kg('/api/dims?member_id=' + mid + '&days=7');
  const ex = await kg('/api/explore?member_id=' + mid);
  const rep = await kg('/api/report?member_id=' + mid + '&days=31');
  const hist = await kg('/api/score/history?member_id=' + mid + '&days=14');
  // 月度统计那一块的数据。跟家长端同一张表同一个接口，一次把整月拿回来，
  // 点某一天不用再跑一趟。
  const ym = todayStr().slice(0, 7);
  const mdays = new Date(+ym.slice(0, 4), +ym.slice(5), 0).getDate();
  const mh = await kg('/api/score/history?member_id=' + mid +
    '&until=' + ym + '-' + String(mdays).padStart(2, '0') + '&days=' + mdays);

  const c = cyc.current || {};
  const tiers = c.tiers || [];
  const top = tiers.length ? tiers[tiers.length - 1].threshold : 49;
  const energy = +c.energy || 0;

  let h = '<div class="appbar">' +
    '<button class="appbar-back" type="button" data-go="' + kBack('report') + '">' + ic('i-back', 16, 'var(--ink)') + '</button>' +
    '<span class="appbar-grow"><div class="appbar-title">成长报告</div>' +
    '<div class="appbar-sub">本周 vs 上周的自己</div></span>' +
    '<span class="pill pill--gray" style="background:rgba(255,255,255,.72)">' +
    esc(String(c.start_date || '').slice(5) + ' - ' + String(c.end_date || '').slice(5)) + '</span></div>';

  // ① 星探时刻：爸爸妈妈写下的原话。它排在最上面，是这一页真正的主角 ——
  //    分数是给家长看的，孩子记住的是那句话。
  const phrases = ((ex && ex.items) || []).filter(x => x.phrase);
  const first = phrases[0];
  h += '<div class="hero" style="padding:14px">' +
    '<div class="hb" style="margin-bottom:8px">' +
    '<span class="h g5 pill pill--white" style="padding:4px 9px">' +
    ic('i-stardust', 12, '#fff') + '星探时刻</span>' +
    '<span class="on-hero-82" style="font-size:10.5px">' +
    (phrases.length ? '最近 ' + num(Math.min(phrases.length, 3)) + ' 条' : '还没写下过') + '</span></div>' +
    (first
      ? '<div style="font-size:13.5px;font-weight:500;line-height:1.55">「' +
        esc(first.phrase) + '」</div>' +
        '<div class="on-hero-82" style="font-size:10.5px;margin-top:8px">' +
        esc(String(first.ts || '').slice(5, 10).replace('-', '月') + '日') +
        (first.stardust ? ' · 星尘 +' + num(first.stardust) : '') + '</div>'
      : '<div style="font-size:13px;line-height:1.55">做到了什么，' +
        '让爸爸妈妈给你记一句。这句话会一直挂在成长报告最上面。</div>') +
    '</div>';

  // ② 七种能量（雷达）
  const items = (dims && dims.dims) || [];
  if (items.length) {
    const vals = items.map(x => x.total ? (x.hit / x.total) : 0);
    const mx = Math.max.apply(null, vals), mn = Math.min.apply(null, vals);
    const lab = items.map((x, i) => {
      const v = vals[i];
      const cls = (v === mx && mx > 0) ? 'strong' : (v === mn ? 'weak' : '');
      return { name: x.name, n: x.hit, tip: cls === 'strong' ? '强' : (cls === 'weak' ? '待补' : ''), cls: cls };
    });
    h += '<div class="card"><div class="hb" style="margin-bottom:10px">' +
      '<span class="card-title">七种能量</span>' +
      '<span class="pill" style="padding:5px 11px"><span class="num" style="font-size:14px">' +
      num(energy) + '</span><span class="num" style="font-size:10px;color:var(--orange);opacity:.8"> / ' +
      num(top) + '</span></span></div>' +
      kRadar(vals, lab) +
      '<hr class="rule" style="margin:10px 0 12px">' +
      '<div class="hb"><span class="h g7">' + ic('i-star', 15, 'var(--gold)') +
      '<span style="font-size:11.5px;font-weight:600">本月完美日</span></span>' +
      '<span class="t-2" style="font-size:10.5px">' + num(kPerfectDays(rep)) +
      ' 个 · 只增不减</span></div>' +
      '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:8px">' +
      '七项全拿满才算一个完美日；这几天每项拿到几天，' +
      '看的是最近七天</div></div>';
  }

  // ③ 这一周的我：七天的分数，跟上一周比
  const days = (hist && hist.days) || [];
  if (days.length >= 8) {
    const cur7 = days.slice(-7), prev7 = days.slice(-14, -7);
    const sum = a => a.reduce((s, x) => s + (+x.score || 0), 0);
    const diff = Math.round((sum(cur7) - sum(prev7)) * 10) / 10;
    const full = Math.max.apply(null, cur7.map(x => +x.full || 7).concat([7]));
    h += '<div class="card"><div class="hb" style="margin-bottom:10px">' +
      '<span class="card-title">这一周的我</span>' +
      '<span class="pill ' + (diff >= 0 ? 'pill--blue' : 'pill--gray') + '" style="padding:4px 9px">' +
      ic('i-arrow-up', 10, diff >= 0 ? 'var(--blue-deep)' : 'var(--ink-3)') +
      (diff >= 0 ? '比上周多 ' + num(diff) + ' 分' : '比上周少 ' + num(-diff) + ' 分') +
      '</span></div>' +
      kWeekChart(cur7, prev7, full) +
      '<div class="footnote" style="justify-content:flex-start;margin-top:10px">' +
      ic('i-lock', 12, 'var(--ink-3)') + '只跟上周的自己比 · 这里没有排行榜</div></div>';
  }

  // ④ 被扣过的：这几天哪一项掉过。它不属于「成长」，但孩子有权知道自己
  //    被扣了什么 —— 只报喜不报忧的报告，孩子第二次就不看了。
  const notes = [];
  items.forEach(x => {
    (x.fines || []).forEach(f => notes.push({ ts: f.ts, text: f.text || f.reason, dim: x.name }));
  });
  if (notes.length) {
    h += '<div class="card"><div class="hb" style="margin-bottom:6px">' +
      '<span class="card-title">这几天被扣过</span>' +
      '<span class="card-note">只有这些地方扣了分</span></div>' +
      notes.slice(0, 5).map(n => '<div class="row-sub" style="margin-top:7px">' +
        esc(String(n.ts || '').slice(5, 10)) + ' · ' + esc(n.dim) + '：' +
        esc(n.text || '') + '</div>').join('') + '</div>';
  }
  // ⑤ 月度统计。放在最后：上面几块看的是「这一周」，这一块尺度更大，
  //    拿它收尾。格子和小结必须同源 —— 两处各算一遍迟早会出现
  //    「图上有 5 个满格，下面写完美日 4 天」。
  if (mh && mh.days && mh.days.length) {
    const m = { ym: ym, rows: mh.days, total: mh.total };
    KCAL = m;
    h += kCalHTML(m) + kMonthKpi(m);
  }
  return kShell({}, h);
}

/* ============================================================ 月度统计（孩子端） */
/* 从家长端「打分 · 月度统计」那一屏搬过来的两块：月历五态 + 本月小结三格。
   色板换成孩子端这一套，0 分格走柔红不用家长端那个正红 —— 这一页是给他看的，
   0 分是「这天没过好」，不是「你被记了一笔」。
   只画本月，不做翻月：孩子要看的是「这个月我在哪儿」，家长才需要往回翻账。 */
let KCAL = null;
const K_CAL_WD = ['一', '二', '三', '四', '五', '六', '日'];

function kCalHTML(m) {
  const ym = m.ym, Y = +ym.slice(0, 4), M = +ym.slice(5);
  const lead = (new Date(Y, M - 1, 1).getDay() + 6) % 7;   // 周一排第一列
  const today = todayStr();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  m.rows.forEach(r => cells.push(r));
  while (cells.length % 7) cells.push(null);

  let h = '<div class="card"><div class="hb" style="margin-bottom:10px">' +
    '<span class="card-title">' + M + ' 月打分日历</span>' +
    '<span class="card-note">点一格看当天七项</span></div>' +
    '<div class="kcal">' +
    K_CAL_WD.map(d => '<span class="kcal-wd">' + d + '</span>').join('');
  cells.forEach(r => {
    if (!r) return h += '<span class="kcal-blank"></span>';
    let st;
    if (r.future) st = 'future';
    else if (!r.scored) st = (r.transition ? 'trans' : 'none');
    else if (r.score >= r.full) st = 'full';
    else if (r.score > 0) st = 'part';
    else st = 'zero';
    const cls = 'kcal-cell is-' + st + (r.day === today ? ' is-today' : '');
    // 未来的日子点不开，别给一个点了只会说「还没到」的按钮
    h += r.future
      ? '<span class="' + cls + '">' + (+r.day.slice(8)) + '</span>'
      : '<button type="button" class="' + cls + '" data-kcd="' + r.day + '">' +
        (+r.day.slice(8)) + '</button>';
  });
  h += '</div>' +
    '<div class="kcal-lg">' +
    '<span><b class="lg-full"></b>满分</span>' +
    '<span><b class="lg-part"></b>部分</span>' +
    '<span><b class="lg-none"></b>没打分</span>' +
    '<span><b class="lg-zero"></b>0 分</span>' +
    '<span><b class="lg-future"></b>未来</span></div>' +
    '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:8px">' +
    '虚线那几天是没打过分的，不算进下面那个达成率。' +
    '「0 分」和「没打分」不是一件事。</div></div>';
  return h;
}

/* 本月小结。三个数字跟上面那张图同源，分开算迟早对不上。 */
function kMonthKpi(m) {
  const today = todayStr();
  const t = m.total || { score: 0, full: 0, days: 0 };
  const elapsed = m.rows.filter(r => r.day <= today).length;
  const perfect = m.rows.filter(r => r.scored && r.score >= r.full).length;
  const first = m.rows.length ? m.rows[0].day.slice(5) : '';
  const last = m.rows.length ? m.rows[m.rows.length - 1].day.slice(5) : '';
  return '<div class="card"><div class="hb" style="margin-bottom:10px">' +
    '<span class="card-title">本月小结</span>' +
    '<span class="card-note">' + esc(first) + ' - ' + esc(last) + '</span></div>' +
    '<div class="kkpi-row">' +
    '<div class="kkpi"><span class="k">本月固定分</span><span class="v">' +
    num(t.score) + ' / ' + num(t.full) + '</span></div>' +
    '<div class="kkpi"><span class="k">完美日</span><span class="v">' + num(perfect) + ' 天</span></div>' +
    '<div class="kkpi"><span class="k">打过分的天</span><span class="v">' +
    num(t.days) + ' / ' + num(elapsed) + '</span></div></div></div>';
}

/* 点一格看当天七项。数据就在 KCAL 里，不再跑接口。
   没打分之天要说清「没记录不等于没做到」，不然孩子会以为自己被抹掉了。 */
function kCalDaySheet(r) {
  const p = String(r.day).split('-');
  const wd = K_CAL_WD[(new Date(+p[0], +p[1] - 1, +p[2]).getDay() + 6) % 7];
  let h = '<h3>' + (+p[1]) + ' 月 ' + (+p[2]) + ' 日 · 周' + wd + '</h3>';
  if (r.transition) h += '<p class="muted">这两天是假期过渡日，不计分。</p>';
  if (r.scored) {
    h += '<div class="kcal-s"><span>这天拿到</span><b>' + num(r.score) + '</b>' +
      '<span>/ ' + num(r.full) + '</span></div>' +
      '<div class="kcal-dl">' + (r.cells || []).map(c =>
        '<div class="kcal-d">' + glyph(c.icon, 'dim', 22) +
        '<span class="kcal-dn">' + esc(c.name) + '</span>' +
        '<span class="kcal-dv ' + (c.value > 0 ? 'yes' : 'no') + '">' +
        (c.value > 0 ? '✓' : '✗') + '</span></div>').join('') + '</div>';
    if (r.reason && r.reason.note) {
      h += '<p class="t-2" style="font-size:11px;margin-top:10px">备注：' + esc(r.reason.note) + '</p>';
    } else if (r.reason && r.reason.lost && r.reason.lost.length) {
      h += '<p class="t-2" style="font-size:11px;margin-top:10px">扣的是：' +
        esc(r.reason.lost.join('、')) + '</p>';
    } else {
      h += '<p class="t-2" style="font-size:11px;margin-top:10px">这天七项都拿到了。</p>';
    }
  } else {
    h += '<p class="muted">这天没有打分记录。没记录不等于没做到，所以它不算进达成率。</p>';
  }
  sheet(h, function () {});
}

/* 本月完美日：七项全拿满的天数。「本月」按自然月算，
   不是最近 30 天 —— 月初点进来看到的是 0，那一格才有意义。 */
function kPerfectDays(rep) {
  if (!rep || !rep.daily) return 0;
  const ym = todayStr().slice(0, 7);
  return rep.daily.filter(x => String(x.day).slice(0, 7) === ym && (+x.score || 0) >= 7).length;
}

/* 七轴雷达。中心向外的三段圈 + 一条折线。值域是「这一项这七天拿到几天 / 7」，
   不是分数 —— 分数在家长那端，孩子这边看的是「哪一项我总也拿不到」。 */
function kRadar(vals, lab) {
  const n = vals.length, cx = 150, cy = 98, R = 56;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
  };
  const ring = f => vals.map((_, i) => pt(i, R * f).map(v => v.toFixed(1)).join(',')).join(' ');
  let g = '';
  [1, 2 / 3, 1 / 3].forEach((f, i) => {
    const st = ['#F5E6CE', '#F8F0E2', '#FBF6EC'][i];
    g += '<polygon points="' + ring(f) + '" fill="none" stroke="' + st + '"/>';
  });
  // 最外那圈上面 [1, 2/3, 1/3] 里已经画过了（f=1，同一组点同一个色），
  // 这里原本还有一条重复的 <path>，而且拼法是把第一个点的两个坐标也用 L 连，
  // SVG 解析不了（M150.0L42.0）。删掉，不留一条看不见的报错。
  const poly = vals.map((v, i) => pt(i, Math.max(3, R * Math.max(0, Math.min(1, v))))
    .map(x => x.toFixed(1)).join(',')).join(' ');
  g += '<polygon points="' + poly + '" fill="#FF8A3D" fill-opacity="0.18" stroke="#FF8A3D" ' +
    'stroke-width="2" stroke-linejoin="round"/>';
  vals.forEach((v, i) => {
    const p = pt(i, Math.max(3, R * Math.max(0, Math.min(1, v))));
    g += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) +
      '" r="3.2" fill="#FFC93C" stroke="#FF8A3D" stroke-width="1.6"/>';
  });
  lab.forEach((x, i) => {
    const p = pt(i, R + 17);
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    const anchor = Math.abs(Math.cos(a)) < 0.25 ? 'middle' : (Math.cos(a) > 0 ? 'start' : 'end');
    const col = x.cls === 'strong' ? '#FF8A3D' : (x.cls === 'weak' ? '#7A93B8' : '#8A7359');
    g += '<text x="' + p[0].toFixed(1) + '" y="' + (p[1] + 3.4).toFixed(1) +
      '" text-anchor="' + anchor + '" font-size="10" font-weight="' +
      (x.cls ? '700' : '500') + '" fill="' + col + '">' +
      esc(x.name) + ' ' + x.n + (x.tip ? ' ' + x.tip : '') + '</text>';
  });
  return '<div style="position:relative;height:196px">' +
    '<svg viewBox="0 0 300 196" width="100%" height="196" style="position:absolute;inset:0">' +
    g + '</svg></div>';
}

/* 这一周的我：实线是这七天，虚线是上七天。两条画在同一个坐标里，
   「比上周好」这件事才看得见 —— 只画一条线，那个数字就只是个数。 */
function kWeekChart(cur, prev, full) {
  const n = 7, W = 300, H = 104, padT = 10, padB = 20;
  const y = v => padT + (1 - Math.max(0, Math.min(1, v / full))) * (H - padT - padB);
  const x = i => 16 + i * ((W - 32) / (n - 1));
  const line = a => a.map((p, i) => x(i).toFixed(1) + ',' +
    y(+p.score || 0).toFixed(1)).join(' ');
  const wk = ['一', '二', '三', '四', '五', '六', '日'];
  let g = '<path d="M0 ' + y(full).toFixed(1) + 'H' + W + '" stroke="#F5EDE0"/>' +
    '<path d="M0 ' + y(full / 2).toFixed(1) + 'H' + W + '" stroke="#FBF5EA"/>';
  if (prev.length === n) {
    g += '<polyline points="' + line(prev) + '" fill="none" stroke="#D8CCBD" stroke-width="2" ' +
      'stroke-dasharray="4 4" stroke-linecap="round" stroke-linejoin="round"/>';
  }
  g += '<polygon points="' + line(cur) + ' ' + x(n - 1).toFixed(1) + ',' + y(0).toFixed(1) +
    ' ' + x(0).toFixed(1) + ',' + y(0).toFixed(1) + '" fill="#FF8A3D" fill-opacity="0.10"/>' +
    '<polyline points="' + line(cur) + '" fill="none" stroke="#FF8A3D" stroke-width="3" ' +
    'stroke-linecap="round" stroke-linejoin="round"/>';
  cur.forEach((p, i) => {
    const last = i === n - 1;
    g += '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(+p.score || 0).toFixed(1) + '" r="' +
      (last ? '4.6' : '3.2') + '" fill="' + (last ? '#FFC93C' : '#FF8A3D') + '"' +
      (last ? ' stroke="#FF8A3D" stroke-width="2.2"' : '') + '/>';
    const wd2 = wk[(new Date(String(p.day) + 'T00:00:00')).getDay() === 0 ? 6
      : (new Date(String(p.day) + 'T00:00:00')).getDay() - 1];
    g += '<text x="' + x(i).toFixed(1) + '" y="' + (H - 4) + '" text-anchor="middle" ' +
      'font-size="9.5" font-weight="' + (last ? '700' : '400') + '" fill="' +
      (last ? '#FF8A3D' : '#A08E7A') + '">' + wd2 + '</text>';
  });
  return '<div style="position:relative;height:' + H + 'px">' +
    '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" height="' + H +
    '" style="position:absolute;inset:0">' + g + '</svg></div>';
}

/* ============================================================ 心愿屋 */
async function kScreenWish() {
  const mid = S.me.id;
  const w = await api('GET', '/api/wishes');
  const pool = await kg('/api/pool');
  const p = pool && pool.pool;
  const sd = S.data.overview ? S.data.overview.stardust : 0;

  const pend = w.items.filter(x => x.status === 'wished');
  const active = w.items.filter(x => x.status === 'active');
  const hist = w.items.filter(x => x.status === 'achieved' || x.status === 'claimed'
    || x.status === 'cancelled');

  let h = '<div class="appbar">' +
    '<button class="appbar-back" type="button" data-go="' + kBack('wish') + '">' + ic('i-back', 16, 'var(--ink)') + '</button>' +
    '<span class="appbar-grow appbar-title">心愿屋</span>' +
    '<span class="appbar-right"><span class="pill" style="gap:5px;padding:5px 10px">' +
    ic('i-stardust', 11, 'var(--stardust)') + '<span class="num" style="font-size:11px">' +
    num(sd) + '</span></span></span></div>';

  // ⑥ 许愿的入口。原来是个橙虚线框加一句「+ 我想要……」—— 虚线框读起来像
  //    「这儿还有东西没填」，可这一页本来就空着等他做这一件事。
  //    改成一张入口卡，跟首页那张「想要点什么？」同形，一眼知道点哪儿。
  h += '<div class="row wish-new" id="kWnew">' +
    '<span class="icon-box" style="background:var(--pink-bg)">' +
    ic('i-wishstar', 20, 'var(--pink-deep)') + '</span>' +
    '<div class="row-grow"><div class="row-title">许个愿……</div>' +
    '<div class="row-sub">写下来挂到心愿屋，爸爸妈妈给你定条件</div></div>' +
    ic('i-chevron', 16, 'var(--pink-deep)') + '</div>';

  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-wishstar', 16, 'var(--pink-deep)') + '我的心愿</span>' +
    '<span class="sect-note">进行中 ' + num(active.length) + ' / ' + num(w.limit) + '</span></div>';
  if (!pend.length && !active.length && !hist.length) {
    h += '<div class="card"><div class="empty">还没有心愿。<br>' +
      '点上面那个按钮，把想要的写下来。</div></div>';
  }

  active.forEach(x => {
    const p2 = x.progress || {};
    const whole = !p2.manual && !p2.has_manual && !p2.has_pending;
    h += '<div class="card card--tight">' +
      '<div class="h g10">' +
      '<span class="icon-box" style="flex:0 0 34px;width:34px;height:34px;background:var(--pink-bg)">' +
      glyph(x.icon, 'wish', 18) + '</span>' +
      '<div class="grow v g3"><div class="row-title">' + esc(x.title) + '</div>' +
      '<div class="row-sub">' + esc(String(x.created_at || '').slice(0, 10)) + ' 许的</div></div>' +
      (x.price_note ? '<span class="pill pill--pink" style="padding:5px 10px">' +
        esc(x.price_note) + '</span>' : '') + '</div>' +
      // ① 条件单独一块。以前它跟「提醒」都是一行小灰字，
      //   孩子分不清哪句是「要去做的」。
      '<div class="wcond"><div class="wcond-h">要做到什么</div>' +
      '<div class="wcond-t">' + esc(wishCondText(x)) + '</div>' +
      (p2.where ? '<div class="t-3" style="font-size:10.5px;margin-top:4px">' +
        esc(p2.where) + '</div>' : '') + '</div>' +
      // ② 进度：汇总那一行 + 进度条。子条件不在这儿列，下面按条列。
      wishProgHTML(x, false) +
      // ③ 每一条各一行，该按哪个按钮就在那一行上
      ((p2.subs || []).length
        ? '<div class="wsubs">' + p2.subs.map(s2 => wishSubRow(x, s2)).join('') + '</div>'
        : wishSelfRow(x, p2)) +
      (p2.done || (p2.ready && whole)
        ? '<div class="hb" style="margin-top:10px">' +
          '<span class="ok-t" style="font-size:10.5px">够了，可以随时兑现</span>' +
          '<button class="btn btn--sm" data-wdone="' + x.id + '">我做到了</button></div>'
        : '') +
      wishNotesHTML(x) +
      '</div>';
  });

  if (pend.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-clock', 16, 'var(--purple)') + '还等着定条件</span>' +
      '<span class="sect-note">还能挂 ' + num(Math.max(0, w.pending_limit - pend.length)) +
      ' 个</span></div>';
    pend.forEach(x => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:var(--purple-bg)">' + glyph(x.icon, 'wish', 18) + '</span>' +
        '<div class="row-grow"><div class="row-title">' + esc(x.title) + '</div>' +
        '<div class="row-sub">' + esc(String(x.created_at || '').slice(0, 10)) +
        ' 许的 · 等爸爸妈妈定条件</div></div>' +
        '<button class="btn btn--sm line" data-wdrop="' + x.id + '">不想要了</button></div>';
    });
  }

  // 全家许愿池
  h += '<div class="card" style="background:linear-gradient(135deg,#F6F2FF 0%,#EDE8FF 100%);' +
    'border-color:#DCD2FF">' +
    '<div class="hb"><span class="h g8">' + ic('i-pool', 20, 'var(--purple-deep)') +
    '<span class="card-title">全家许愿池</span></span>' +
    (p ? '<span class="num" style="font-size:15px;color:var(--purple-deep)">' +
      num(p.collected_stardust) + ' / ' + num(p.target_stardust) + '</span>' : '') + '</div>';
  if (!p) {
    h += '<div class="t-2" style="font-size:11px;line-height:1.6;margin-top:8px">' +
      '爸爸妈妈还没定全家的目标。定好了，你投的星尘也会算在里面。</div>';
  } else {
    h += '<div style="font-size:13px;font-weight:700;margin:10px 0">' + esc(p.title) + '</div>' +
      '<div class="bar bar--purple"><i style="width:' +
      Math.max(0, Math.min(100, p.percent)) + '%"></i></div>' +
      '<div class="t-2" style="font-size:10px;line-height:1.6;margin-top:10px">' +
      (p.target_desc ? esc(p.target_desc) + '　' : '') +
      (p.target_stardust > p.collected_stardust
        ? '还差 ' + num(p.target_stardust - p.collected_stardust) + ' 星尘'
        : '攒够了，等爸爸妈妈安排') + '　攒满就出发</div>' +
      '<button class="btn btn--sm" id="kDep" style="margin-top:11px">把我的星尘投进去</button>';
    const es = (pool.entries || []).slice(0, 6);
    if (es.length) {
      h += '<div style="margin-top:10px;padding-top:8px;border-top:1px dashed rgba(139,107,255,.3)">' +
        es.map(e => '<div class="row-sub" style="margin-top:5px">' +
          esc(e.name || '有人') + ' 投了 ' + num(e.stardust) + ' 星尘' +
          (e.note ? '　' + esc(e.note) : '') + '</div>').join('') + '</div>';
    }
  }
  h += '</div>';

  if (hist.length) {
    h += '<div class="card" style="padding:0;overflow:hidden">' +
      '<button class="hist-toggle" id="kHistTg" style="display:flex;align-items:center;' +
      'justify-content:space-between;gap:8px;width:100%;padding:13px;font-size:12.5px;' +
      'font-weight:700;color:var(--ink);text-align:left">' +
      '<span>历史心愿</span><span class="t-3" style="font-weight:500">' + num(hist.length) +
      ' 条　' + (WISH_HIST_OPEN ? '收起' : '展开') + '</span></button>' +
      '<div class="hist-body"' + (WISH_HIST_OPEN ? '' : ' hidden') + ' style="padding:0 13px 6px">' +
      hist.map(wishHistRow).join('') + '</div></div>';
  }
  return kShell({}, h);
}

/* ============================================================ 我的 */
async function kScreenMine() {
  const mid = S.me.id;
  const hold = await api('GET', '/api/holdings?member_id=' + mid);
  const cat = await kg('/api/catalog?member_id=' + mid);
  const cyc = await api('GET', '/api/cycle?member_id=' + mid);
  const lvl = await kg('/api/levels?member_id=' + mid);
  const ev = await kg('/api/events?member_id=' + mid);
  const rep = await kg('/api/report?member_id=' + mid + '&days=31');
  const pool = S.data.pool;

  const lv = lvl && lvl.level;
  const ticketCnt = (hold.tickets || []).reduce((a, t) => a + (+t.qty || 0), 0);
  const cardCnt = (hold.cards || []).reduce((a, c) => a + (+c.qty || 0), 0);
  /* 这一格点进去是券包，券包里现在券和卡都摆着，只数券的话，手上三张卡
     那一格还写着 0，看着像东西没到手。 */
  const privCnt = ticketCnt + cardCnt;
  const perfect = kPerfectDays(rep);

  let h = '<div class="hero">' +
    '<div class="h g12">' +
    '<span style="flex:0 0 56px">' + avatarHTML(S.me, 56) + '</span>' +
    '<div class="grow v g5">' +
    '<div class="h g7"><span style="font-size:21px;font-weight:700">' + esc(S.me.name) + '</span>' +
    (lv ? '<span class="pill pill--white" style="padding:3px 9px">Lv.' + lv.level +
      (lv.title ? ' · ' + esc(lv.title) : '') + '</span>' : '') + '</div>' +
    '<div class="on-hero-90" style="font-size:10.5px;font-weight:500">' +
    (lv && lv.next ? '再攒 ' + num(lv.need) + ' 星尘升到「' + esc(lv.next.title) + '」'
      : (lv ? '已经是最高一档了' : '等级按累计获得的星尘算')) + '</div>' +
    '</div>' +
    '<button type="button" id="kAvEdit" style="flex:0 0 30px;width:30px;height:30px;' +
    'border-radius:50%;background:rgba(255,255,255,.22);display:grid;place-items:center;border:0;' +
    'cursor:pointer">' + ic('i-sliders', 18, '#fff') + '</button>' +
    '</div>' +
    (lv ? '<div class="bar bar--onhero" style="margin:14px 0 10px"><i style="width:' +
      Math.max(0, Math.min(100, lv.percent)) + '%"></i></div>' +
      '<div class="hb"><span class="num on-hero-88" style="font-size:10.5px">升级进度 ' +
      num(lv.total) + ' / ' + num(lv.next ? lv.next.threshold : lv.threshold) + '</span>' +
      '<span class="h g5 pill pill--white" style="padding:4px 10px">' +
      ic('i-stardust', 12, 'var(--gold-pale)') + num(hold.stardust) + ' 可用</span></div>'
      : '<div class="h g5 pill pill--white" style="padding:4px 10px;margin-top:12px">' +
        ic('i-stardust', 12, 'var(--gold-pale)') + num(hold.stardust) + ' 可用</div>') +
    '</div>';

  if (hold.debt > 0) {
    h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') +
      '还欠 ' + num(hold.debt) + ' 星尘，下次结算时先扣</div>';
  }
  if (ev && ev.state && ev.state.active) {
    h += '<div class="tip">' + ic('i-info', 15, '#D18A3C') +
      '设备降级中，还有 ' + num(ev.state.days_left) + ' 天。到 ' +
      esc(ev.state.end_date) + ' 自动恢复，不用再谈</div>';
  }

  // 三宫格：星尘看余额；第二格数「券 + 卡」有多少，点了去券包；第三格是
  // 这个月的完美日，点了去成长报告 —— 报告底部那张月历就是它逐天摊开的样子，
  // 两边必须是同一个数，点过去才不打架。后两格能点，标签后面挂个小箭头 ——
  // 三格长得一模一样，不给个记号就看不出「这两格能点」。
  const kGoArrow = '<span class="k-go">' + ic('i-chevron', 10, 'var(--ink-line)') + '</span>';
  h += '<div class="card" style="display:grid;grid-template-columns:1fr auto 1fr auto 1fr;' +
    'align-items:center;padding:14px">' +
    '<div class="v g5" style="text-align:center"><span class="num" style="font-size:20px;' +
    'color:var(--orange)">' + num(hold.stardust) + '</span>' +
    '<span class="t-2" style="font-size:10px">星尘余额</span></div>' +
    '<span style="width:1px;height:30px;background:var(--line)"></span>' +
    '<div class="v g5 k-tap" style="text-align:center" data-go="coupon">' +
    '<span class="num" style="font-size:20px;color:var(--pink-deep)">' + num(privCnt) + '</span>' +
    '<span class="t-2 k-lab" style="font-size:10px">特权道具' + kGoArrow + '</span></div>' +
    '<span style="width:1px;height:30px;background:var(--line)"></span>' +
    '<div class="v g5 k-tap" style="text-align:center" data-go="report">' +
    '<span class="num" style="font-size:20px;color:var(--purple-deep)">' + num(perfect) + '</span>' +
    '<span class="t-2 k-lab" style="font-size:10px">本月完美日' + kGoArrow + '</span></div></div>';

  const catN = cat ? cat.items.filter(x => x.owned > 0).length : 0;
  const catT = cat ? cat.items.length : 0;
  const rec = (cyc.history || []);
  h += '<div class="row" data-go="wish" style="cursor:pointer">' +
    '<span class="icon-box" style="background:var(--pink-bg)">' + ic('i-wishstar', 19, 'var(--pink-deep)') + '</span>' +
    '<div class="row-grow"><div class="row-title">心愿屋</div>' +
    '<div class="row-sub">发起心愿 · 看进度 · 家庭许愿池</div></div>' +
    ic('i-chevron', 16, 'var(--ink-line)') + '</div>' +
    '<div class="row" data-go="atlas" style="cursor:pointer">' +
    '<span class="icon-box" style="background:var(--purple-bg)">' + ic('i-cards', 19, 'var(--purple-deep)') + '</span>' +
    '<div class="row-grow"><div class="row-title">图鉴</div>' +
    '<div class="row-sub">已收集 ' + num(catN) + ' / ' + num(catT) + ' 张卡 · 碎片 ' +
    num(hold.fragment) + '</div></div>' +
    ic('i-chevron', 16, 'var(--ink-line)') + '</div>' +
    '<div class="row" data-go="report" style="cursor:pointer">' +
    '<span class="icon-box" style="background:var(--blue-bg)">' + ic('i-calendar', 19, 'var(--blue-deep)') + '</span>' +
    '<div class="row-grow"><div class="row-title">成长报告</div>' +
    '<div class="row-sub">星探时刻 · 七种能量 · 这一周的我 · 本月小结</div></div>' +
    ic('i-chevron', 16, 'var(--ink-line)') + '</div>' +
    '<div class="row" data-go="family" style="cursor:pointer">' +
    '<span class="icon-box" style="background:#FFEEE0">' + ic('i-family', 19, 'var(--orange)') + '</span>' +
    '<div class="row-grow"><div class="row-title">家庭</div>' +
    '<div class="row-sub">' + num(S.members.length) + ' 口人' +
    (pool ? ' · 许愿池 ' + num(pool.collected_stardust) + ' / ' + num(pool.target_stardust) : '') +
    (rec.length ? ' · 走过 ' + num(rec.length) + ' 个周期' : '') + '</div></div>' +
    ic('i-chevron', 16, 'var(--ink-line)') + '</div>';

  h += '<div class="card" style="padding:0;overflow:hidden">' +
    '<div class="hb" style="padding:13px;cursor:pointer" id="kAvRow">' +
    ic('i-palette', 20, 'var(--orange)') +
    '<span class="grow" style="font-size:12.5px;font-weight:500">头像与皮肤</span>' +
    ic('i-chevron', 16, 'var(--ink-line)') + '</div>' +
    '<div style="height:1px;background:var(--line)"></div>' +
    '<div class="hb" style="padding:13px;cursor:pointer" id="kPw">' +
    ic('i-lock', 20, 'var(--purple-deep)') +
    '<span class="grow" style="font-size:12.5px;font-weight:500">修改密码</span>' +
    ic('i-chevron', 16, 'var(--ink-line)') + '</div>' +
    '<div style="height:1px;background:var(--line)"></div>' +
    '<div class="hb" style="padding:13px;cursor:pointer" id="kOut">' +
    ic('i-back', 20, 'var(--ink-3)') +
    '<span class="grow" style="font-size:12.5px;font-weight:500">退出登录</span>' +
    ic('i-chevron', 16, 'var(--ink-line)') + '</div></div>';

  h += '<div class="footnote">' + ic('i-lock', 12, 'var(--ink-line)') +
    '这是你自己的页面 · 爸妈那端不显示等级</div>';
  return kShell({}, h);
}

/* ============================================================ 图鉴 */
async function kScreenAtlas() {
  const mid = S.me.id;
  const hold = await api('GET', '/api/holdings?member_id=' + mid);
  const cat = await api('GET', '/api/catalog?member_id=' + mid);
  const have = cat.items.filter(x => x.owned > 0).length;

  let h = '<div class="appbar">' +
    '<button class="appbar-back" type="button" data-go="' + kBack('atlas') + '">' + ic('i-back', 16, 'var(--ink)') + '</button>' +
    '<span class="appbar-grow"><div class="appbar-title">图鉴</div>' +
    '<div class="appbar-sub">已收集 ' + num(have) + ' / ' + num(cat.items.length) +
    ' 张 · 卡不卖，只能开箱开出</div></span></div>';

  // v38：这里原本第三格数「手上有用的」，现在那一整段搬去券包了，
  // 留在图鉴里会跟券包那一页数同一件事 —— 一个数两个地方看，迟早对不上。
  h += '<div class="grid2">' +
    '<div class="card card--tight v g3" style="text-align:center">' +
    '<span class="num" style="font-size:20px;color:var(--purple-deep)">' + num(have) +
    '</span><span class="t-2" style="font-size:10px">收集到的卡</span></div>' +
    '<div class="card card--tight v g3" style="text-align:center">' +
    '<span class="num" style="font-size:20px;color:var(--gold-deep)">' + num(cat.fragment) +
    '</span><span class="t-2" style="font-size:10px">碎片</span></div></div>';

  if (cat.fragment >= 10) {
    h += '<div class="card card--tight"><div class="hb">' +
      '<span style="font-size:12px;font-weight:700">碎片换卡</span>' +
      '<span class="h g6">' +
      '<button class="btn btn--sm line" data-frag="random">10 片随机</button>' +
      (cat.fragment >= 20 ? '<button class="btn btn--sm" data-frag="pick">20 片自选</button>' : '') +
      '</span></div>' +
      '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:8px">' +
      '碎片只有一种来法：宝箱开出的卡超出持有上限时，多出来的会折成碎片。</div></div>';
  }

  /* v38：这里原本还有一段「手上能用的卡」，连「用」按钮一起整段搬去券包了。
     图鉴只回答「我收集到什么」，手上能用的东西在券包那边跟券摆在一起 ——
     「我现在有什么能用的」不该先翻一层图鉴才看得见，两页各列一份也迟早对不上。 */
  const exp = (hold.expiring || []);
  if (exp.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-clock', 16, 'var(--orange)') + '快到期的</span>' +
      '<span class="sect-note">续一次就再算 90 天</span></div>';
    exp.forEach(e => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:#FFF6E0">' + ic('i-box', 19, 'var(--gold-deep)') + '</span>' +
        '<div class="row-grow"><div class="row-title">' + esc(e.name) + '</div>' +
        '<div class="row-sub">' + esc(e.expires_at) + ' 到期，到期会折半转成星尘</div></div>' +
        '<button class="btn btn--sm line" data-renew="' + e.holding_id +
        '" data-cost="' + num(e.renew_cost) + '">续 ' +
        num(e.renew_cost) + '</button></div>';
    });
  }

  h += '<div class="sect-head"><span class="sect-title">' +
    ic('i-cards', 16, 'var(--purple)') + '全部图鉴</span>' +
    '<span class="sect-note">' + num(cat.items.length) + ' 种</span></div>' +
    '<div class="catalog">' + cat.items.map(c =>
      '<div class="cat-cell ' + (c.owned ? 'have' : '') + '"><b>' + esc(c.name) + '</b>' +
      esc(c.card_no || '') + '<br>' + (c.owned ? '×' + num(c.owned) : '未获得') + '</div>').join('') +
    '</div>';
  return kShell({}, h);
}

/* ============================================================ 家庭 */
async function kScreenFamily() {
  const pool = await kg('/api/pool');
  const cyc = await kg('/api/cycle?member_id=' + S.me.id);
  const p = pool && pool.pool;
  const hist = (cyc && cyc.history) || [];

  let h = '<div class="appbar">' +
    '<button class="appbar-back" type="button" data-go="' + kBack('family') + '">' + ic('i-back', 16, 'var(--ink)') + '</button>' +
    '<span class="appbar-grow"><div class="appbar-title">家庭</div>' +
    '<div class="appbar-sub">' + num(S.members.length) + ' 口人</div></span></div>';

  h += '<div class="card">' + S.members.map(m =>
    '<div class="h g10" style="padding:7px 0">' + avatarHTML(m, 38) +
    '<div class="grow"><div class="row-title">' + esc(m.name) + '</div>' +
    '<div class="row-sub">' + (m.role === 'parent' ? '家长 · 当裁判' : '孩子 · 玩游戏') + '</div></div>' +
    '</div>').join('') +
    '<div class="t-3" style="font-size:10px;line-height:1.6;margin-top:10px">' +
    '家长只当裁判，不参与打分，也没有星尘和等级。</div></div>';

  h += '<div class="card" style="background:linear-gradient(135deg,#F6F2FF 0%,#EDE8FF 100%);' +
    'border-color:#DCD2FF">' +
    '<div class="hb"><span class="h g8">' + ic('i-pool', 20, 'var(--purple-deep)') +
    '<span class="card-title">全家许愿池</span></span>' +
    (p ? '<span class="num" style="font-size:15px;color:var(--purple-deep)">' +
      num(p.collected_stardust) + ' / ' + num(p.target_stardust) + '</span>' : '') + '</div>';
  if (!p) {
    h += '<div class="t-2" style="font-size:11px;line-height:1.6;margin-top:8px">' +
      '还没有全家目标。爸爸妈妈定下来之后，这里会显示攒到哪儿了。</div>';
  } else {
    h += '<div style="font-size:13px;font-weight:700;margin:10px 0">' + esc(p.title) + '</div>' +
      '<div class="bar bar--purple"><i style="width:' + Math.max(0, Math.min(100, p.percent)) +
      '%"></i></div>' +
      '<div class="t-2" style="font-size:10px;line-height:1.6;margin-top:10px">' +
      (p.target_desc ? esc(p.target_desc) + '　' : '') +
      '全家一起攒 · 攒满就出发</div>';
  }
  h += '</div>';

  if (hist.length) {
    h += '<div class="sect-head"><span class="sect-title">' +
      ic('i-clock', 16, 'var(--purple)') + '家里走过的周期</span>' +
      '<span class="sect-note">最近 ' + num(hist.length) + ' 个</span></div>';
    hist.forEach(x => {
      h += '<div class="row">' +
        '<span class="icon-box" style="background:#FFF6E0">' + ic(kBoxIcon(x.tier || 1), 20) + '</span>' +
        '<div class="row-grow"><div class="row-title">' + esc(x.start) + ' - ' + esc(x.end) + '</div>' +
        '<div class="row-sub">你那一周 能量 ' + num(x.energy) + ' · ' +
        (x.status === 'settled' ? '星尘 +' + num(x.stardust) : '进行中') + '</div></div></div>';
    });
  }
  h += '<div class="footnote">' + ic('i-lock', 12, 'var(--ink-line)') +
    '这一页没有排行榜 · 只看自己的</div>';
  return kShell({}, h);
}

/* ============================================================ 渲染入口 */
const K_SCREENS = {
  home: kScreenHome, task: kScreenTask, hall: kScreenHall, chest: kScreenChest,
  coupon: kScreenCoupon, shop: kScreenShop, report: kScreenReport, wish: kScreenWish,
  mine: kScreenMine, atlas: kScreenAtlas, family: kScreenFamily,
};

const CHILD = {};

/* 启动时定屏：hash 里有合法的屏就用它（刷新后还在当前页），
   否则按 S.view 的老值翻一下，再不行回首页。 */
CHILD.pickView = function (fallback) {
  const v = String(location.hash || '').replace(/^#/, '');
  if (kValid(v)) return v;
  const map = { week: 'home', dims: 'report', boxes: 'chest', hall: 'hall', shop: 'shop', wish: 'wish' };
  return map[fallback] || (kValid(fallback) ? fallback : 'home');
};

CHILD.renderTabs = function () {
  if (S.isParent) return;
  const cur = K_TAB_OF[S.view] || 'home';
  $('#tabs').classList.remove('many');
  $('#tabs').innerHTML = '<div class="tabbar-pill">' + K_TABS.map(t =>
    '<button type="button" class="tab' + (cur === t[0] ? ' on' : '') + '" data-v="' + t[0] + '">' +
    ic(t[1], 21) + '<span>' + t[2] + '</span></button>').join('') + '</div>';
  $$('#tabs button').forEach(b => b.addEventListener('click', () => kGo(b.dataset.v)));
};

CHILD.renderTop = function () {
  // 孩子端没有顶栏：角色条在首页，「我是谁」在「我的」里。
  // 这里留一个空实现，是为了让 app.js 两边共用一套调用顺序，不用到处写 if。
};

CHILD.render = async function () {
  kSprite();
  const el = $('#view');
  el.innerHTML = '<div class="screen"><div class="content lead"><div class="empty">加载中…</div></div></div>';
  const fn = K_SCREENS[S.view] || K_SCREENS.home;
  try {
    el.innerHTML = await fn();
    CHILD.bind();
    startTkTick();
    startTicketPoll();
  } catch (e) {
    console.error('[kid] ' + S.view + ':', e);
    const msg = String((e && e.message) || e);
    el.innerHTML = '<div class="screen"><div class="content lead">' +
      '<div class="card"><div style="font-size:13px;font-weight:700">这个页面没能显示出来</div>' +
      '<div class="t-3" style="font-size:11px;margin-top:6px">' + esc(msg) + '</div>' +
      '<div class="t-3" style="font-size:11px;margin-top:4px">退出去再进来一次；还是这样，把上面这句记下来。</div>' +
      '</div></div></div>';
  }
};

/* 页面上的按钮分两种：一种是「换屏」（data-go，用事件委托，一处管全部），
   一种是「做事」（提交任务、买东西、用券）—— 那些仍然走 app.js 里既有的
   绑定函数，因为规则在那一侧，这里再写一遍一定会对不上。 */
CHILD.bind = function () {
  const el = $('#view');

  const av = $('#kAvEdit', el), avRow = $('#kAvRow', el);
  if (av) av.addEventListener('click', () => avatarSheet());
  if (avRow) avRow.addEventListener('click', () => avatarSheet());
  const pw = $('#kPw', el);
  if (pw) pw.addEventListener('click', () => changePwSheet());
  const out = $('#kOut', el);
  if (out) out.addEventListener('click', () => logoutNow());
  const ot = $('#kAskOt', el);
  if (ot) ot.addEventListener('click', () => askOvertimeSheet(S.me.id));
  const hp = $('#kAskHelp', el);
  if (hp) hp.addEventListener('click', () => askHelpSheet(S.me.id));
  const wn = $('#kWnew', el);
  if (wn) wn.addEventListener('click', () => wishNewSheet());
  const ht = $('#kHistTg', el);
  if (ht) ht.addEventListener('click', async () => { WISH_HIST_OPEN = !WISH_HIST_OPEN; await render(); });
  const ex = $('#kExCash', el);
  if (ex) ex.addEventListener('click', () => cashSheet());
  const dp = $('#kDep', el);
  if (dp) dp.addEventListener('click', () => kDepositSheet());

  // 成长报告底部那张月历：点一格看当天七项。明细就在 KCAL 里，不再跑接口。
  $$('[data-kcd]', el).forEach(b => b.addEventListener('click', () => {
    const row = KCAL && (KCAL.rows || []).filter(r => r.day === b.dataset.kcd)[0];
    if (row) kCalDaySheet(row);
  }));

  // 任务页底部那颗「展开全部」：拉半屏列表出来看。
  const hm = $('#kHistMore', el);
  if (hm) hm.addEventListener('click', () => { kTaskHistSheet(); });

  // 心愿的三个动作（交一条 / 付星尘 / 登记达成）走 app.js 里那一套，
  // 同一件事在首页和心愿屋两边必须一模一样，否则孩子会以为坏了。
  bindTaskActions();
  bindWishActions();
  $$('#view [data-wdrop]').forEach(b => b.addEventListener('click', async () => {
    askSheet({
      title: '撤掉这个心愿',
      hint: '这条心愿作废，付过的星尘会退回来',
      ok: '我不要了',
    }, async () => {
      try {
        await api('POST', '/api/wishes/' + b.dataset.wdrop + '/status', { status: 'cancelled' });
        closeSheet(); toast('撤掉了'); await render();
      } catch (e) { err(e); }
    });
  }));
  // 付星尘那一个按钮不在这里绑：bindWishActions 里已经绑过并带上了确认，
  // 两边都挂监听的话点一下会跑两遍（弹层叠两层、接口发两次）。
  // 宝箱页顶部那张「点我打开」。待开箱的箱子不管动画播多久，都在这里点开；
  // 开了但自选没挑完的那只，点下去是回到结果屏接着挑（后端 pick 那一支负责收尾）。
  $$('#view button[data-openbox]').forEach(b => b.addEventListener('click', () => {
    const row = ((S.pendBoxes || []).filter(x => x.box_id === +b.dataset.openbox)[0]) || null;
    kOpenBoxFlow(+b.dataset.openbox, b.dataset.tier, row);
  }));
  $$('#view button[data-box]').forEach(b => b.addEventListener('click',
    () => confirmBuyBox(+b.dataset.box, +b.dataset.p)));
  $$('#view button[data-t]').forEach(b => b.addEventListener('click',
    () => buyTicket(b.dataset.t, +b.dataset.p)));
  $$('#view button[data-c]').forEach(b => b.addEventListener('click',
    () => buyCard(b.dataset.c, +b.dataset.p)));
  $$('#view button[data-use]').forEach(b => b.addEventListener('click',
    () => useItemSheet(b.dataset.use, b.dataset.hid)));
  $$('#view button[data-renew]').forEach(b => b.addEventListener('click', async () => {
    const cost = num(+b.dataset.cost || 0);
    askSheet({
      title: '续 90 天，花 ' + cost + ' 星尘',
      hint: '续完这张卡接着用，错过到期日就折半转星尘',
      ok: '续 90 天，花 ' + cost + ' 星尘',
    }, async () => {
      try {
        const r = await api('POST', '/api/items/renew', { holding_id: +b.dataset.renew });
        closeSheet(); toast('续到 ' + r.expires_at); await boot();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-frag]').forEach(b => b.addEventListener('click', async () => {
    const pick = b.dataset.frag === 'pick';
    const cost = pick ? 20 : 10;
    askSheet({
      title: pick ? '换一张自己挑的' : '换一张随机传说卡',
      hint: '扣 ' + cost + ' 碎片换一张卡，选了不能改',
      ok: '确认兑换',
    }, async () => {
      try {
        const r = await api('POST', '/api/fragments/exchange', { member_id: S.me.id, mode: b.dataset.frag });
        closeSheet(); toast('换到「' + r.card.name + '」'); await boot();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-tk]').forEach(b => {
    if (b.disabled) return;
    b.addEventListener('click', async () => {
      const code = b.dataset.tk;
      const fun = (code === 'ticket_fun');
      // 额度这份快照要当场取，不能图省事用进那一屏时那一份：孩子可能在
      // 这一屏停了十分钟才点，这十分钟里那一轮可能已经结束进入休息了。
      // 少一次接口换来的是「看这能用、点下去被拒」。
      let st = { minutes: 0 };
      if (fun) {
        try { st = (await kg('/api/tickets/state?member_id=' + S.me.id)) || st; }
        catch (e) { st = { minutes: 0 }; }
      }
      // 库存也得真传：写死 0 的话「要几张」那排只会剩 1 张。
      ticketSheet(code, b.dataset.tkname || '', +(b.dataset.tkq || 0), st);
    });
  });
  $$('#view button[data-cashok]').forEach(b => b.addEventListener('click', async () => {
    const amt = num(+b.dataset.amt || 0);
    askSheet({
      title: '收到了 ' + amt + ' 元',
      hint: '点完这一条才算完，现金已经在你手上',
      ok: '收到了 ' + amt + ' 元',
    }, async () => {
      try {
        const r = await api('POST', '/api/cash/requests/' + b.dataset.cashok + '/received', {});
        closeSheet(); toast('记下了，收到 ' + num(r.cash) + ' 元'); await render();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-cashx]').forEach(b => b.addEventListener('click', async () => {
    askSheet({
      title: '不换这笔了',
      hint: '这条申请作废，星尘没扣，想换可以重新提交',
      ok: '不换了',
    }, async () => {
      try {
        await api('POST', '/api/cash/requests/' + b.dataset.cashx + '/cancel', {});
        closeSheet(); toast('撤回了'); await render();
      } catch (e) { err(e); }
    });
  }));
};

/* 投星尘进许愿池 */
function kDepositSheet() {
  const sd = S.data.overview ? S.data.overview.stardust : 0;
  sheet('<h3>投进许愿池</h3><p class="muted">投进去的星尘拿不回来，' +
    '但它会算进全家那个目标里。你现在有 ' + num(sd) + ' 星尘。</p>' +
    '<div class="field"><label>投多少</label><input id="kDsd" type="number" min="1" value="' +
    Math.max(1, Math.min(50, Math.floor(sd))) + '"></div>' +
    '<button class="btn wide" id="kDepGo">投进去</button>', box => {
    const b = box.querySelector('#kDepGo');
    b.addEventListener('click', async () => {
      try {
        await api('POST', '/api/pool/deposit', { stardust: +box.querySelector('#kDsd').value });
        closeSheet(); toast('投进去了'); await boot();
      } catch (e) { err(e); }
    });
  });
}

/* ============================================================ 启动 */
/* 换屏统一走这里。二级页（报告 / 心愿屋 / 图鉴 / 记录 / 家庭）不占底栏，
   但底栏要亮点着它所属的那一格，所以高亮查的是 K_TAB_OF。 */
document.addEventListener('click', function (e) {
  if (S.isParent || !S.me) return;
  let el = e.target;
  while (el && el !== document.body) {
    if (el.dataset && (el.dataset.go || el.dataset.goto)) {
      kGo(el.dataset.go || el.dataset.goto);
      return;
    }
    el = el.parentNode;
  }
});

window.addEventListener('popstate', kFromHash);
window.addEventListener('hashchange', kFromHash);
function kFromHash() {
  if (S.isParent || !S.me) return;
  const v = String(location.hash || '').replace(/^#/, '');
  if (kValid(v) && v !== S.view) {
    S.view = v;
    renderTabs();
    render();
  }
}
