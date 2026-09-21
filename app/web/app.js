'use strict';
/* 家庭积分 · 前端。原生 JS，无框架、无 CDN。
   v13：家长端和孩子端是两套导航。家长只打分，不进游戏循环；
   孩子端有星球等级（英雄面板 + 等级图）。 */

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.prototype.slice.call((r || document).querySelectorAll(s));
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function num(v) {
  const n = Number(v || 0);
  if (!isFinite(n)) return '0';
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100);
}

const S = {
  me: null, isParent: false, members: [], target: null,
  view: 'week', day: null, data: {}, score: {}, pin: {},
  // 二级页「来路」：哪一屏把我送到这儿来的。返回按钮按它走，
  // 写死目标的话「我的 → 成长报告 → 返回」会掉到首页去。见 child.js 的 kBack。
  from: {},
  // 打分页底部那张月度统计看的是哪个月（'YYYY-MM'）。空着就跟着 S.day 走，
  // 切了月份之后不再被选日期带着跑，否则点一个上月的格子月份会跟着跳。
  month: null,
};
const KIDS = () => S.members.filter(m => m.role === 'child');
const PARENTS = () => S.members.filter(m => m.role !== 'child');

/* ------------------------------------------------------------------ 基础 */
async function api(method, path, body) {
  const opt = { method: method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (e) { /* 空响应 */ }
  if (!r.ok) throw new Error((data && data.error) || ('请求失败 ' + r.status));
  return data;
}

let toastTimer = null;
function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 2200);
}
function err(e) { toast(e && e.message ? e.message : String(e)); }

function sheet(html, onOpen) {
  const box = $('#sheetBody');
  box.innerHTML = html;
  $('#sheet').classList.add('on');
  if (onOpen) onOpen(box);
}
function closeSheet() { $('#sheet').classList.remove('on'); }
$('#sheet').addEventListener('click', e => { if (e.target.id === 'sheet') closeSheet(); });

/* 做事之前的那一句。形状跟「确认花 XX 星尘」那一个弹层是同一套：
   一句话说清「点了会发生什么」，一个确认按钮，点外面或者按「取消」就是没这回事。
   不写「确定吗」—— 那三个字不带任何信息，误触的人照样点下去。

   back 是给「弹层里再弹一层」用的（比如心愿条那个「看看」）：
   取消的时候退回原来那层，而不是把整个弹层关掉。

   按钮位置：做事的那颗在左，取消永远在右，两颗分贴弹层两边。
   手指按错「确认」的代价，比多点一次取消大得多。 */
function askSheet(o, fn, back) {
  sheet('<h3>' + esc(o.title || '') + '</h3>' +
    (o.hint ? '<p class="muted">' + esc(o.hint) + '</p>' : '') +
    (o.line ? '<div class="callout-line">' + esc(o.line) + '</div>' : '') +
    '<div class="act-row">' +
    '<button type="button" class="btn btn--primary" id="askGo">' +
    esc(o.ok || '确认') + '</button>' +
    '<button type="button" class="btn btn--ghost" id="askNo">' +
    esc(o.cancel || '取消') + '</button></div>', box => {
      $('#askNo', box).addEventListener('click', () => {
        if (back) back(); else closeSheet();
      });
      $('#askGo', box).addEventListener('click', async () => {
        const b = $('#askGo', box);
        if (b.disabled) return;
        b.disabled = true;                       // 连点两下不该跑两遍
        try { await fn(); } catch (e) { err(e); b.disabled = false; }
      });
    });
}

function todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}
function shiftDay(day, n) {
  const p = day.split('-').map(Number);
  const d = new Date(p[0], p[1] - 1, p[2]);
  d.setDate(d.getDate() + n);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}
const WD = ['日', '一', '二', '三', '四', '五', '六'];
function wd(day) { const p = day.split('-').map(Number); return WD[new Date(p[0], p[1] - 1, p[2]).getDay()]; }
function memberName(id) {
  const m = S.members.find(x => x.id === id);
  return m ? m.name : String(id);
}
function memberOf(id) { return S.members.find(x => x.id === id) || null; }
function targetId() { return S.target || (S.me && S.me.id); }
function targetRole() {
  const m = memberOf(targetId());
  return m ? m.role : (S.me && S.me.role);
}
// 家长没选孩子时，接口要 member_id；这里保证一定指向一个孩子
function kidId() {
  if (S.isParent && targetRole() !== 'child') {
    const k = KIDS();
    return k.length ? k[0].id : null;
  }
  return targetId();
}
/* ================================================================== 头像 */
/* 头像值有两种来源，得同时吃下：
     1. token  'dad_1'      ->  avatars/dad_1.svg     （v25 起，从清单里挑）
     2. 别的   '爸' / '小宝' ->  取前两个字当文字头像   （老库里的值，和从没挑过的人）
   认不出来的 token 不报错也不留空框，回落成文字。加头像这件事不该让
   任何一个老账号突然没有头 —— 这一条和图标那套「认不出来就画个灰圈」
   是同一个道理，只是头像有更好看的兜底可用。                            */
const AVATAR_TOKENS = {};
const AVATAR_GROUPS = [];
(function () {
  if (typeof AVATARS === 'undefined') return;
  AVATARS.forEach(function (a) { AVATAR_TOKENS[a.t] = a; });
  AVATARS.forEach(function (a) {
    let g = AVATAR_GROUPS.filter(x => x.g === a.g)[0];
    if (!g) { g = { g: a.g, items: [] }; AVATAR_GROUPS.push(g); }
    g.items.push(a);
  });
})();

function avatarHTML(m, size, cls) {
  const px = size || 24;
  const c = cls ? ' ' + cls : '';
  const v = String((m && m.avatar) || '');
  if (AVATAR_TOKENS[v]) {
    // encodeURIComponent：值来自数据库，万一被塞了斜杠也飞不出 avatars/ 这个目录
    return '<img class="av-img' + c + '" src="avatars/' + encodeURIComponent(v) +
      '.svg" alt="" width="' + px + '" height="' + px + '" loading="lazy">';
  }
  return '<span class="av-tx' + c + '" style="width:' + px + 'px;height:' + px +
    'px;font-size:' + Math.round(px * 0.4) + 'px">' +
    esc(((v || (m && m.name)) || '?').slice(0, 2)) + '</span>';
}

function av(m) { return avatarHTML(m, 24); }

const RAR = { common: '普通', rare: '稀有', legend: '传说', diamond: '钻石' };
const DIM_IC = { heart: '心', study: '智', vigor: '力', bond: '伴', craft: '匠', clean: '洁', order: '序' };
const BOX_NAME = ['木', '铜', '银', '金', '钻', '王', '完美'];

/* ================================================================== 图标 */
/* 一个字段装三种东西：
     1. token   'rw_box'  ->  icons/rw_box.svg
     2. 字符    '😀' '心'  ->  直接当字符显示
     3. 空      ->  按类型给它一个默认
   为什么不拆成三列：一个东西只会有一张图，拆三列每次渲染都要写一遍三选一，
   而且家长换图的时候还得记得把另外两列清空 —— 多两个能出错的机会。

   认不出来的 token 不报错，画一个空心圈。这一条是留给未来的：以后只想往
   web/icons 里丢一个 SVG 就能用，不用前后端同时发版。
   老版本的 DIM_IC 保留着，仅用于「数据库里那一列还是空的」这种情况。       */
const ICON_TOKENS = {};
(function () {
  if (typeof ICONS === 'undefined') return;
  ICONS.forEach(function (i) { ICON_TOKENS[i.t] = i.l; });
})();
const ICON_DEFAULT = {
  task: 'quest_scroll', repair: 'sys_repair', wish: 'sys_wish', box: 'rw_box',
  ticket: 'rw_ticket', card: 'rw_card', dim: 'dim_study', pool: 'sys_pool', item: 'rw_card',
};

function iconLabel(icon, kind) {
  const t = String(icon == null ? '' : icon).trim() || (ICON_DEFAULT[kind] || '');
  if (!t) return '不加图';
  return ICON_TOKENS[t] || t;
}

/* 唯一的图标渲染出口。凡是显示一张图的地方都调它，别就地拼 img。 */
/* eager=true 时不加 loading="lazy"。选图面板里那 120 个格子是面板一开就要
   看见的东西，懒加载会把首屏留成一片空底色，家长以为「图没加载出来」。 */
function glyph(icon, kind, size, cls, eager) {
  const px = size || 20;
  const c = cls ? ' ' + cls : '';
  const tok = String(icon == null ? '' : icon).trim() || (ICON_DEFAULT[kind] || '');
  if (!tok) {
    const d = Math.round(px * 0.44);
    return '<span class="gly gly-0' + c + '" style="width:' + px + 'px;height:' + px + 'px">' +
      '<i style="width:' + d + 'px;height:' + d + 'px"></i></span>';
  }
  if (ICON_TOKENS[tok]) {
    // encodeURIComponent：token 来自数据库，万一被塞了斜杠也飞不出 icons/ 这个目录。
    // gly-svg 是给外面那层容器（.dic / .dr-ic 这些）看的：自带的糖果色圆底
    // 已经够看了，别再给它垫一层淡绿背景，方角会从圆的四个角露出来。
    return '<img class="gly gly-svg' + c + '" src="icons/' + encodeURIComponent(tok) + '.svg" alt="" ' +
      'width="' + px + '" height="' + px + '"' + (eager ? '' : ' loading="lazy"') + '>';
  }
  return '<span class="gly gly-t' + c + '" style="width:' + px + 'px;height:' + px +
    'px;font-size:' + Math.round(px * 0.58) + 'px">' + esc(tok) + '</span>';
}

/* ------------------------------------------------------------------ 选图 */
/* 做成塞在表单里的折叠面板，而不是二级弹层：弹层是全局唯一的那一个，
   二级一开就把外面这份表单顶掉了，填了一半的东西全没了。 */
const IP = {};                 // 每个实例一份状态：当前值 / 当前组 / 搜索词
const IP_LIMIT = 120;          // 一次最多画这么多格子，再多选的同学靠滚动加载没必要

function iconField(id, cur, kind, label) {
  // 配任务的图先落在「任务」那一组（悬赏卷轴 / 勋章 / 钥匙 / 藏宝图这些），
  // 家长发活时找的就是这一类；一上来铺「全部」，得从七个维度那儿开始往下划。
  IP[id] = { v: cur || '', g: kind === 'task' ? '任务' : '', q: '', kind: kind || '' };
  return '<div class="field">' + (label ? '<label>' + label + '</label>' : '') +
    '<div class="ip"><button type="button" class="ip-btn" data-ip="' + id + '">' +
    glyph(cur, kind, 26) + '<span class="ip-n">' + esc(iconLabel(cur, kind)) + '</span>' +
    '<span class="ip-x">换</span></button>' +
    '<div class="ip-box" id="ipb-' + id + '" hidden></div>' +
    '<input type="hidden" id="' + id + '" value="' + esc(cur || '') + '"></div></div>';
}

function ipGroups() {
  const gs = [''];
  const seen = {};
  ICONS.forEach(function (i) { if (!seen[i.g]) { seen[i.g] = 1; gs.push(i.g); } });
  (typeof EMOJI_GROUPS === 'undefined' ? [] : EMOJI_GROUPS).forEach(function (e) {
    if (typeof e.g === 'string') gs.push('emoji:' + e.g);
  });
  (typeof CHAR_GROUPS === 'undefined' ? [] : CHAR_GROUPS).forEach(function (e) {
    if (typeof e.g === 'string') gs.push('字:' + e.g);
  });
  return gs;
}

function ipItems(g, q) {
  const out = [];
  ICONS.forEach(function (i) {
    if (g && g !== i.g) return;
    if (q && i.l.indexOf(q) < 0 && i.k.indexOf(q) < 0 && i.t.indexOf(q) < 0) return;
    out.push({ t: i.t, l: i.l, img: true });
  });
  (typeof EMOJI_GROUPS === 'undefined' ? [] : EMOJI_GROUPS).forEach(function (e) {
    if (g && g !== 'emoji:' + e.g) return;
    if (q && e.g.indexOf(q) < 0) return;
    e.items.forEach(function (m) { out.push({ t: m, l: m, img: false }); });
  });
  (typeof CHAR_GROUPS === 'undefined' ? [] : CHAR_GROUPS).forEach(function (e) {
    if (g && g !== '字:' + e.g) return;
    if (q && e.g.indexOf(q) < 0) return;
    e.items.forEach(function (m) { out.push({ t: m, l: m, img: false }); });
  });
  return out;
}

/* 「不要图」原来是一颗占满整行的格子（grid-column:1/-1），面板一开先看见
   它，图标被推到下面那片限高 232px 的滚动区里 —— 家长以为「没图」。
   现在它缩成头部右上角一颗小按钮，格子从第一行就开始铺。 */
function ipGrid(id) {
  const st = IP[id];
  const items = ipItems(st.g, st.q);
  const shown = items.slice(0, IP_LIMIT);
  const cnt = st.q ? '找到 ' + items.length + ' 张' : '共 ' + items.length + ' 张';
  let h = '<div class="ip-stat">' + cnt + (st.g ? '　·　' + esc(st.g) : '') + '</div>';
  if (!items.length) {
    return h + '<div class="ip-more">没找到，换个词试试，或者点「重置」看全部。</div>';
  }
  h += '<div class="ip-grid">' + shown.map(function (it) {
    return '<button type="button" class="ip-cell' + (st.v === it.t ? ' on' : '') +
      '" data-ipv="' + id + '" data-v="' + esc(it.t) + '" title="' + esc(it.l) + '">' +
      // eager：这一屏是打开就要看的，别让懒加载把首屏留成一片空底色
      glyph(it.t, st.kind, 30, '', true) + '</button>';
  }).join('') + '</div>';
  if (items.length > shown.length) {
    h += '<div class="ip-more">还有 ' + (items.length - shown.length) + ' 个，搜个字再挑</div>';
  }
  return h;
}

function ipRender(id) {
  const box = $('#ipb-' + id);
  if (!box) return;
  const st = IP[id];
  box.innerHTML =
    '<div class="ip-head"><span class="ip-title">配一张图 · 当前：' +
    esc(iconLabel(st.v, st.kind)) + '</span>' +
    '<button type="button" class="ip-clear" data-ipv="' + id + '" data-v="">不要图</button></div>' +
    '<div class="ip-top"><input class="ip-q" id="ipq-' + id + '" placeholder="搜：钥匙、星星、宝箱…" ' +
    'value="' + esc(st.q) + '">' +
    '<button type="button" class="ip-cl" data-ipc="' + id + '">重置</button></div>' +
    '<div class="ip-chips">' + ipGroups().map(function (g) {
      const nm = g === '' ? '全部' : (g.indexOf(':') > 0 ? g.split(':')[1] : g);
      return '<button type="button" class="chip' + (st.g === g ? ' on' : '') +
        '" data-ipg="' + id + '" data-g="' + esc(g) + '">' + esc(nm) + '</button>';
    }).join('') + '</div>' +
    '<div id="ipg-' + id + '">' + ipGrid(id) + '</div>';
}

/* 面板里所有交互都走事件委托，绑在 root 上，一个 root 只绑一次。
   原来开合按钮和搜索框是逐个 addEventListener 的，那是**快照**：发布页的容器
   #view 不重画（每次切页只换里面的 innerHTML），加上 dataset.ipBound 那道
   「只绑一次」的守卫，第二次进「发布 → 写任务」时，新画出来的那颗「配一张图」
   身上一个监听都没有，点下去毫无反应。搜索框更早就坏了 —— 它是点开之后才
   生成的，绑的那会儿它还不存在。
   委托之后，谁在场上谁生效，root 只绑一次也不怕。 */
function bindIconField(root) {
  const r = root || document;
  if (r.dataset && r.dataset.ipBound) return;
  if (r.dataset) r.dataset.ipBound = '1';
  r.addEventListener('click', function (e) {
    const t = e.target && e.target.closest
      ? e.target.closest('[data-ip],[data-ipv],[data-ipg],[data-ipc]') : null;
    if (!t) return;
    const id = t.dataset.ip || t.dataset.ipv || t.dataset.ipg || t.dataset.ipc;
    if (!id || !IP[id]) return;
    if (t.dataset.ip) {                    // 开 / 合这一格的面板
      const box = $('#ipb-' + id);
      if (!box) return;
      box.hidden = !box.hidden;
      if (!box.hidden) ipRender(id);
      return;
    }
    if (t.dataset.ipv) {                   // 挑一张
      IP[id].v = t.dataset.v || '';
      const inp = $('#' + id);
      if (inp) inp.value = IP[id].v;
      const btn = $('button[data-ip="' + id + '"]');
      if (btn) {
        btn.querySelector('.ip-n').textContent = iconLabel(IP[id].v, IP[id].kind);
        const old = btn.querySelector('.gly');
        if (old) old.outerHTML = glyph(IP[id].v, IP[id].kind, 26);
      }
      const box = $('#ipb-' + id);
      if (box) box.hidden = true;
      e.stopPropagation();
      return;
    }
    if (t.dataset.ipg) { IP[id].g = t.dataset.g; ipRender(id); return; }
    if (t.dataset.ipc) { IP[id].g = ''; IP[id].q = ''; ipRender(id); return; }
  });
  r.addEventListener('input', function (e) {
    const i = e.target;
    if (!i || !i.classList || !i.classList.contains('ip-q')) return;
    const id = i.id.slice(4);
    if (!IP[id]) return;
    IP[id].q = i.value.trim();
    clearTimeout(IP[id].tm);
    // 只重画格子，不重画整个面板。连着整个重画的话每敲一个字输入框就失焦一次
    IP[id].tm = setTimeout(function () {
      const g = $('#ipg-' + id);
      if (g) g.innerHTML = ipGrid(id);
    }, 200);
  });
}


/* ================================================================== 家长端 · 图标 */
/* 家长端 34 个图标（parent-icons.js 里的雪碧图）。跟孩子端同一套做法：
   颜色走 currentColor，由调用处决定；版心不统一（22 的器物、32/34 带底圆的、
   46 的头像），所以 viewBox 从 PARENT_VB 里取 —— 写死 24 会把图形裁掉一圈。

   雪碧图只在家长端第一次渲染时注入一次。孩子端有它自己那 43 个，
   两边名字不重叠（家长端是 i-nav-* / i-log-* 这些），互不打扰。 */
let P_SPRITE_ON = false;
function pSprite() {
  if (P_SPRITE_ON || typeof PARENT_SPRITE === 'undefined') return;
  document.body.insertAdjacentHTML('afterbegin', PARENT_SPRITE);
  P_SPRITE_ON = true;
}
/* 唯一的图标出口。认不出来的名字安静地什么都不画，别在页面上留一段
   <use href="#undefined"> —— 那种东西不会报错，只会让某个按钮空一块。 */
function pic(name, size, cls, color) {
  if (!name || typeof PARENT_ICONS === 'undefined' || PARENT_ICONS.indexOf(name) < 0) return '';
  const px = size || 20;
  const vb = (PARENT_VB && PARENT_VB[name]) || '0 0 24 24';
  /* 尺寸走 calc(px * var(--u))（--u 在 style.css 的 :root，390 处正好 1px），
     与 ic() 同一套写法：style 压过 CSS 里那些 `.ico { width: 22px }`，
     宽度属性压不过。 */
  return '<svg class="ico ' + (cls || '') + '" style="width:calc(' + px + ' * var(--u));height:calc(' + px + ' * var(--u))' +
    (color ? ';color:' + color : '') + '" viewBox="' + vb + '" aria-hidden="true">' +
    '<use href="#' + name + '"/></svg>';
}

/* ================================================================== 家长端 · 路由 */
/* 底栏 5 格。语义和孩子端完全不同（那边是 首页/任务/宝箱/券包/我的）：
   家长这边是 总览 / 审核 / 打分 / 发布 / 我的。
   一级页之外还有二级页（动态日志 / 宝箱 / 商店 / 家庭页 / 心愿与许愿池 /
   孩子详细 / 打分矩阵），它们压在 Tab 之上，底栏高亮自己所属的那一格。
   刷新后停在哪一屏、手机返回键能不能退回去，都靠 P_TAB_OF 这张表。 */
const P_TABS = [
  ['home', 'i-nav-compass', '总览'],
  ['review', 'i-nav-stamp', '审核'],
  ['score', 'i-nav-quill', '打分'],
  ['publish', 'i-nav-flag', '发布'],
  ['me', 'i-nav-user', '我的'],
];
const P_TAB_OF = {
  home: 'home', logs: 'home',
  review: 'review',
  score: 'score', month: 'score', history: 'score',
  publish: 'publish',
  me: 'me', chest: 'me', shop: 'me', family: 'me', wish: 'me', kid: 'me',
  settings: 'me',
};
function pValid(v) { return !!(v && P_TAB_OF[v]); }

function pHash(v, push) {
  if (location.hash === '#' + v) return;
  try {
    if (push === false) history.replaceState({ v: v }, '', '#' + v);
    else history.pushState({ v: v }, '', '#' + v);
  } catch (e) { /* file:// 之类下面没有 history，能跑就行 */ }
}

/* 换屏的唯一入口。底栏走 pGo（同一格再点一次不堆历史），
   二级页入口走 pGo 也一样 —— 语义不同只在于进的是哪一屏。 */
function pGo(v) {
  if (!pValid(v)) return;
  if (v === S.view) { pHash(v, false); render(); return; }
  S.view = v;
  // 离开设置页就把「正在看哪一组」清掉。不清的话：设置 → 周期与假期 →
  // 底栏切走 → 再进设置，会直接落在上一次那一组里，一级那七行看不见了。
  if (v !== 'settings') P_SETGRP = '';
  pHash(v);
  scrollTop0();
  renderTabs(); render();
}
/* 换屏要回到顶上。render() 现在会把滚动位置还回去，所以这里必须先清成 0，
   否则从「审核」切到「打分」，新的一屏停在上一屏滚到的地方。 */
function scrollTop0() {
  const el = $('#view');
  if (!el) return;
  el.scrollTop = 0;
  const c = el.querySelector('.content');
  if (c) c.scrollTop = 0;
}
function pPick(fallback) {
  const v = String(location.hash || '').replace(/^#/, '');
  if (pValid(v)) return v;
  // 旧屏名认一下：升级前停在「任务」「设置」上的人，刷新后不该看见空白页
  const map = { tasks: 'publish', setup: 'me', settings: 'me', kid: 'family' };
  if (map[fallback]) return map[fallback];
  return pValid(fallback) ? fallback : 'home';
}
function pFromHash() {
  if (!S.isParent || !S.me) return;
  const v = String(location.hash || '').replace(/^#/, '');
  if (pValid(v) && v !== S.view) { if (v !== 'settings') P_SETGRP = ''; S.view = v; renderTabs(); render(); }
}
window.addEventListener('popstate', pFromHash);
window.addEventListener('hashchange', pFromHash);

/* 拉一份可选的接口，失败就当没有。
   家长端一屏要拼七八个数据源，任何一个抖一下都不该让整页变成「没能显示出来」，
   但主要数据（待办、分数、周期）仍然用 api() 直接抛。 */
async function pg(path, fallback) {
  try { return await api('GET', path); } catch (e) { return fallback; }
}

/* ------------------------------------------------------------------ 启动 */
async function boot() {
  window.__APP_BOOTED__ = true;   // 供 index.html 的启动探测读，防止白屏无声失败
  try {
    const b = await api('GET', '/api/bootstrap');
    S.members = b.members || [];
    S.me = b.me;
    S.isParent = !!b.is_parent;
    // overview / holiday / pool 都是 bootstrap 一次带回来的，存起来给各页复用，
    // 免得顶栏和首页为了一个星尘数再多跑一趟接口。
    S.data = { overview: b.overview || null, holiday: b.holiday || null,
      pool: b.pool || null, version: b.version || '', needsSetup: !!b.needs_setup };
    // 登录页第一行那句家庭名。设置项 family.name，默认「我们家」。
    S.famName = b.family_name || '我们家';
    if (!S.me) {
      // 试一下 cookie 失效的情况：直接进登录页
      renderLogin();
      return;
    }
    if (S.target == null || !S.members.some(m => m.id === S.target)) {
      const kids = KIDS();
      S.target = S.me.role === 'parent' ? (kids.length ? kids[0].id : S.me.id) : S.me.id;
    }
    if (!S.day) S.day = todayStr();
    document.body.classList.remove('lg');
    LG_PIN_TAP = null;
    // 两套界面共用这一个 DOM：家长端「糖果冒险 · 角色换位」，孩子端「糖果冒险」。
    // 分叉就一个 body 上的类，加在这里而不是登录页 —— 刷新后也要立刻对，
    // 不然孩子端会先闪一下家长端的暖橙再变成糖果色（两边同色板，闪一下不容易
    // 看出来，但家长端的装饰层会漏到孩子端头上）。
    document.body.classList.toggle('kid', !S.isParent);
    document.body.classList.toggle('grown', S.isParent);
    const tc = document.querySelector('meta[name="theme-color"]');
    if (tc) tc.setAttribute('content', '#FF8A3D');
    if (S.isParent) {
      // hash 里有合法的屏就用它，刷新后还停在原来那一屏；旧屏名在 pPick 里换掉
      S.view = pPick(S.view);
    } else {
      // 孩子端换皮以后屏名也换了（week→home、dims→report、boxes→chest …），
      // 定屏交给孩子端自己。
      S.view = CHILD.pickView(S.view);
    }
    $('#topbar').style.display = '';
    renderTabs();
    renderTop();
    await render();
  } catch (e) {
    // 启动就失败时不能只弹个 toast，否则页面停在「加载中…」，看着还是白屏
    err(e);
    $('#view').innerHTML = '<div class="empty">没能连上服务：' + esc(e.message) +
      '<br><br>服务可能停掉了，或者数据文件出问题了。</div>';
  }
}

/* ------------------------------------------------------------------ 登录 */
/* v36：冷启动只落一屏。
   进来先看见「你是谁呀？」和一面头像墙，点谁的头像才切到输密码那一屏。
   家里共用一个平板，所以不再有中间那屏「选身份」—— 进来就必须明确谁在用
   （交付包 §1，2026-09-20 定案）。家长入口是退路，不是并列选项：
   只在右下角留一行橙色下划线文字，不跟孩子抢注意力。

   三个状态是同一条路由的三个形状，靠 hash 分：
     #login            ① 选头像（默认）
     #login/<成员号>    ② 输密码（带着「在给谁输」）
     #login/parent     ③ 家长端登录

   状态为什么要进 URL 而不是只放内存：手机上刷新一下得还在原来那一屏，
   返回键得能退回选头像那一屏。所以走 pushState。
   孩子端登录不用账号，只靠「头像 + 4 位数字」认人。                       */
let LG_AT = '';          // 当前登录态的形状，用来挡掉多余的重绘
let LG_PIN_TAP = null;   // 输密码那一刻的键盘接入口，换屏时清空

/* 眼睛，两态。不引图标库：只有这一处用，内联两条路径比多一个 sprite 省事。 */
const LG_EYE = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" ' +
  'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" ' +
  'stroke-linejoin="round"><path d="M2 12s3.8-6.6 10-6.6S22 12 22 12s-3.8 6.6-10 6.6S2 12 2 12Z"/>' +
  '<circle cx="12" cy="12" r="3.1"/></svg>';
const LG_EYE_OFF = LG_EYE.replace('</svg>',
  '<path d="M3.8 20.2 20.2 3.8"/></svg>');

const LG_TITLE = '家庭积分 · 一起攒星尘';   // 软件标题，常量（交付包 §9.1）
const LG_FOOT = '数据只存在自己家里的 NAS 上 · 不外传';

function lgHash(v, push) {
  if (location.hash === '#' + v) return;
  try {
    if (push === false) history.replaceState({ v: v }, '', '#' + v);
    else history.pushState({ v: v }, '', '#' + v);
  } catch (e) { /* file:// 之下没有 history，能跑就行 */ }
}
/* 登录成功那一刻，把 #login/... 从地址栏摘掉。留着它，页面明明换了身份，
   刷新一下地址栏还写着「在给小满输密码」，容易让人以为没进去。 */
function lgClearHash() {
  try { history.replaceState(null, '', location.pathname + location.search); }
  catch (e) { /* 同上 */ }
}

function lgRoute() {
  const h = String(location.hash || '').replace(/^#/, '');
  if (h === 'login/parent') return { st: 'parent' };
  const m = /^login\/(\d+)$/.exec(h);
  if (m) return { st: 'pin', mid: +m[1] };
  return { st: 'wall' };
}

function lgFromHash() {
  if (S.me || !document.body.classList.contains('lg')) return;
  if (S.data.needsSetup) return;
  const r = lgRoute();
  if (r.st + ':' + (r.mid || '') === LG_AT) return;   // 已经是这一屏，不重绘
  renderLogin();
}
window.addEventListener('popstate', lgFromHash);
window.addEventListener('hashchange', lgFromHash);

/* 桌面上的物理键盘：手机用不上，但电脑上给一串数字还要拿鼠标点九宫格
   就太难用了。挂一次，靠 LG_PIN_TAP 这个开关决定现在认不认。 */
document.addEventListener('keydown', e => {
  if (!LG_PIN_TAP) return;
  if (/^[0-9]$/.test(e.key)) { LG_PIN_TAP(e.key); }
  else if (e.key === 'Backspace') { e.preventDefault(); LG_PIN_TAP('del'); }
});

/* ---------------------------------------------------------- 登录页零件 */
function lgShell(deco, body) {
  return '<div class="lg-deco ' + deco + '"></div>' +
    '<div class="lg-inner">' + body + '</div>';
}
function lgFoot(extra) {
  return '<div class="lg-foot">' + (extra || '') +
    '<div class="lg-note">' + LG_FOOT + '</div></div>';
}
const LG_PARENT_BTN = '<button type="button" class="lg-parent" id="lgPar">家长登录</button>';

/* 头像墙。只列孩子 —— 爸妈走右下角那条路，不在这面墙上跟孩子并排。 */
function lgWall(onId, slim) {
  const kids = KIDS();
  if (!kids.length) {
    return '<div class="lg-empty">还没有孩子的账号。<br>' +
      '让管理员在「我的 → 家人账号」里加一个，再回来登录。</div>';
  }
  return '<div class="lg-wall' + (slim ? ' slim' : '') + '">' + kids.map(k =>
    '<button type="button" class="lg-pick lg-group' +
    (onId === k.id ? ' on' : '') + (k.has_password ? '' : ' locked') +
    '" data-as="' + k.id + '">' +
    '<span class="lg-frame">' + avatarHTML(k, 96) + '</span>' +
    '<span class="lg-name">' + esc(k.name) + '</span>' +
    '</button>').join('') + '</div>';
}

function lgCells(n) {
  let h = '';
  for (let i = 0; i < 4; i++) {
    if (i < n) h += '<div class="lg-cell"><i></i></div>';
    else if (i === n) h += '<div class="lg-cell now"></div>';
    else h += '<div class="lg-cell off"></div>';
  }
  return h;
}
function lgKeys() {
  let h = '';
  for (let i = 1; i <= 9; i++) {
    h += '<button type="button" class="lg-key" data-k="' + i + '">' + i + '</button>';
  }
  h += '<span class="lg-key gap"></span>' +
    '<button type="button" class="lg-key" data-k="0">0</button>' +
    '<button type="button" class="lg-key del" data-k="del" aria-label="退格">' +
    '<img src="login/i-backspace.svg" alt=""></button>';
  return h;
}

/* ---------------------------------------------------------- 四屏 */
function lgScreenWall() {
  return lgShell('child',
    '<div class="lg-brand">' +
    '<img src="login/logo-family.svg" alt="">' +
    '<div class="lg-fam">' + esc(S.famName || '我们家') + '</div>' +
    '<div class="lg-sub">' + LG_TITLE + '</div>' +
    '</div>' +
    '<div class="lg-lead"><h1>你是谁呀？</h1><p>点一下自己的头像</p></div>' +
    lgWall(null, false) +
    '<div class="lg-fill"></div>' +
    lgFoot(LG_PARENT_BTN));
}

function lgScreenPin(kid) {
  return lgShell('child',
    '<div><button type="button" class="lg-back" id="lgBack" aria-label="返回">' +
    '<img src="login/i-back.svg" alt=""></button></div>' +
    '<div class="lg-lead left"><h1>' + esc(kid.name) + '，输密码吧</h1>' +
    '<p>4 位数字，输错可以重来</p></div>' +
    lgWall(kid.id, true) +
    '<div class="lg-pin-hint">输入 4 位数字密码</div>' +
    '<div class="lg-cells" id="lgCells">' + lgCells(0) + '</div>' +
    '<div class="lg-keys" id="lgKeys">' + lgKeys() + '</div>' +
    '<div class="lg-fill"></div>' +
    lgFoot('<div class="lg-kid-l"><span>忘了密码？找爸妈帮忙</span>' +
      LG_PARENT_BTN + '</div>'));
}

function lgScreenParent() {
  return lgShell('parent',
    '<div class="lg-badge">' +
    '<img src="login/badge-compass.svg" alt="">' +
    '<h1>家庭积分 · 家长端</h1><p>领航员入口 · 只给爸爸妈妈</p></div>' +
    '<div class="lg-card">' +
    '<div class="lg-f"><label for="lgU">账号</label><div class="lg-input">' +
    '<input id="lgU" autocomplete="username" placeholder="账号就是名字"></div></div>' +
    '<div class="lg-f"><label for="lgP">密码</label><div class="lg-input">' +
    '<input id="lgP" type="password" autocomplete="current-password">' +
    '<button type="button" class="lg-eye" id="lgEye" aria-label="显示密码">' +
    LG_EYE + '</button></div></div>' +
    '<div class="lg-row">' +
    '<label class="lg-check"><input type="checkbox" id="lgRem" checked>记住我</label>' +
    '<button type="button" class="lg-forgot" id="lgForgot">忘记密码？</button>' +
    '</div>' +
    '<button type="button" class="lg-btn" id="lgGo">进入裁判席</button>' +
    '<button type="button" class="lg-btn line" id="lgKid">我是孩子，去孩子端</button>' +
    '</div>' +
    '<div class="lg-fill"></div>' +
    lgFoot());
}

function lgScreenSetup() {
  const dad = (S.members.filter(m => m.role === 'parent')[0] || S.members[0] || {});
  return lgShell('child',
    '<div class="lg-badge">' +
    '<img src="login/logo-family.svg" alt="">' +
    '<h1>第一次用</h1><p>先给管理员定一个账号</p></div>' +
    '<div class="lg-card">' +
    '<div class="lg-f"><label for="lgU">账号名</label><div class="lg-input">' +
    '<input id="lgU" autocomplete="username" value="' + esc(dad.name || '') + '"></div></div>' +
    '<div class="lg-f"><label for="lgP">密码</label><div class="lg-input">' +
    '<input id="lgP" type="password" autocomplete="new-password"></div></div>' +
    '<div class="lg-f"><label for="lgP2">再输一次</label><div class="lg-input">' +
    '<input id="lgP2" type="password" autocomplete="new-password"></div></div>' +
    '<button type="button" class="lg-btn" id="lgGo">设好，进去</button>' +
    '</div>' +
    '<div class="lg-fill"></div>' +
    '<div class="lg-foot"><div class="lg-note wide">这个账号是管理员：能给别人开通账号、' +
    '能重置别人的密码。其他人现在进不来，等管理员进去以后在「我的 → 家人账号」里一个个开通。</div></div>');
}

/* ---------------------------------------------------------- 绑定 */
/* 登录成功的收尾都一样，抽一处，免得三处各写一遍漏掉某一行。 */
function lgEnter(r, msg) {
  toast(msg);
  S.me = r.member; S.target = null; S.day = todayStr(); S.view = null;
  lgClearHash();
  return boot();
}

function lgBindWall() {
  $$('#view [data-as]').forEach(b => b.addEventListener('click', () => {
    const k = memberOf(+b.dataset.as);
    if (!k) return;
    if (!k.has_password) {
      // 还没开通过的号：不装死，也不把人往输密码那屏领
      err({ message: k.name + ' 还没设过密码，让爸妈在「家人账号」里开一个' });
      return;
    }
    lgHash('login/' + k.id);
    renderLogin();
  }));
  const p = $('#lgPar');
  if (p) p.addEventListener('click', () => { lgHash('login/parent'); renderLogin(); });
}

function lgBindPin(kid) {
  const cells = $('#lgCells');
  let pin = '';
  let busy = false;
  const draw = () => { const c = $('#lgCells'); if (c) c.innerHTML = lgCells(pin.length); };

  async function submit() {
    if (busy || pin.length !== 4) return;
    busy = true;
    try {
      const r = await api('POST', '/api/login', { member_id: kid.id, password: pin });
      LG_PIN_TAP = null;
      await lgEnter(r, '欢迎回来，' + ((r.member && r.member.name) || kid.name));
    } catch (e) {
      err(e);
      // 清格 + 轻抖。不锁定次数 —— 家里用的东西，锁了添乱（交付包 §3.2）。
      pin = '';
      if (cells) cells.classList.add('shake');
      setTimeout(() => { if (cells) cells.classList.remove('shake'); draw(); }, 340);
    } finally { busy = false; }
  }
  const tap = k => {
    if (!document.body.classList.contains('lg') || busy) return;
    if (k === 'del') { pin = pin.slice(0, -1); draw(); return; }
    if (pin.length >= 4) return;
    pin += k;
    draw();
    if (pin.length === 4) setTimeout(submit, 60);   // 让第 4 个点先画出来
  };
  LG_PIN_TAP = tap;

  $$('#view [data-k]').forEach(b => b.addEventListener('click', () => tap(b.dataset.k)));
  // 这一屏的头像墙还能点：点别人就换成给别人输，等于换个人
  $$('#view [data-as]').forEach(b => b.addEventListener('click', () => {
    lgHash('login/' + b.dataset.as);
    renderLogin();
  }));
  const back = $('#lgBack');
  if (back) back.addEventListener('click', () => { lgHash('login'); renderLogin(); });
  const p = $('#lgPar');
  if (p) p.addEventListener('click', () => { lgHash('login/parent'); renderLogin(); });
}

function lgBindParent() {
  const pw = $('#lgP');
  const eye = $('#lgEye');
  eye.addEventListener('click', () => {
    const on = pw.type === 'password';
    pw.type = on ? 'text' : 'password';
    eye.innerHTML = on ? LG_EYE_OFF : LG_EYE;
    eye.classList.toggle('on', on);
  });
  const go = async () => {
    const u = $('#lgU').value.trim();
    if (!u) { err({ message: '先填账号' }); return; }
    try {
      const r = await api('POST', '/api/login',
        { username: u, password: pw.value, remember: $('#lgRem').checked });
      await lgEnter(r, '欢迎回来');
    } catch (e) { err(e); }
  };
  $('#lgGo').addEventListener('click', go);
  $('#lgU').addEventListener('keydown', e => { if (e.key === 'Enter') pw.focus(); });
  pw.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  $('#lgKid').addEventListener('click', () => { lgHash('login'); renderLogin(); });
  $('#lgForgot').addEventListener('click', () => sheet(
    '<h3>密码忘了怎么办</h3>' +
    '<p class="muted">这套东西没有自助找回，也没有密保问题 —— 规则层就这么定的。</p>' +
    '<p class="muted">孩子忘了：随便哪个家长进「我的 → 家人账号」里给他重置一个。</p>' +
    '<p class="muted">家长自己忘了：让另一个管理员给你重置。家里只有一位管理员又忘了，' +
    '只能在 NAS 上停掉容器改一次库。</p>' +
    '<div class="muted" style="margin-top:10px">重置之后他只在本机掉一次登录，别的设备不受影响。</div>'));
}

function lgBindSetup() {
  const go = async () => {
    const u = $('#lgU').value.trim(), p = $('#lgP').value, p2 = $('#lgP2').value;
    if (p !== p2) { err({ message: '两次输的密码不一样' }); return; }
    try {
      const r = await api('POST', '/api/setup/admin', { username: u, password: p });
      await lgEnter(r, '设好了');
    } catch (e) { err(e); }
  };
  $('#lgGo').addEventListener('click', go);
  $$('#view input').forEach(el => el.addEventListener('keydown',
    e => { if (e.key === 'Enter') go(); }));
}

/* ---------------------------------------------------------- 入口 */
function renderLogin() {
  // 登录页自带一套糖果色板（login.css，挂 body.lg 下）。登出时 body 上
  // 还挂着 kid / grown 的变量，一起摘掉 —— 留着就是两套暖色互相抢类名。
  document.body.classList.remove('kid');
  document.body.classList.remove('grown');
  document.body.classList.add('lg');
  $('#topbar').style.display = 'none';
  $('#tabs').innerHTML = '';
  stopTkTick();
  stopTicketPoll();
  LG_PIN_TAP = null;
  // 版本号不挂在登录页：孩子每天要输好几次密码，屏幕上多一个 v36
  // 只会让人以为还有另一个版本要选。版本在家长端「我的」那一版说明里看。

  if (S.data.needsSetup) {
    LG_AT = 'setup';
    $('#view').innerHTML = lgScreenSetup();
    lgBindSetup();
    return;
  }

  const kids = KIDS();
  const r = lgRoute();
  let st = r.st, mid = r.mid;
  if (st === 'wall' && kids.length === 1) {
    // 家里只有一个孩子：直接进输密码。这里用 replaceState —— 那面只有一个
    // 头像的墙没什么可回去看的，返回键该退出页面，而不是回到一屏废话。
    st = 'pin'; mid = kids[0].id; lgHash('login/' + mid, false);
  } else if (st === 'pin' && !kids.some(k => k.id === mid)) {
    st = 'wall'; mid = null; lgHash('login', false);
  } else if (st === 'wall') {
    lgHash('login', false);
  }
  LG_AT = st + ':' + (mid || '');

  if (st === 'parent') {
    $('#view').innerHTML = lgScreenParent();
    lgBindParent();
    return;
  }
  const kid = kids.filter(k => k.id === mid)[0];
  if (!kid) {
    $('#view').innerHTML = lgScreenWall();
    lgBindWall();
    return;
  }
  $('#view').innerHTML = lgScreenPin(kid);
  lgBindPin(kid);
}

/* 改自己的密码。孩子和家长用的是同一个接口，也都要输旧密码。 */
function changePwSheet() {
  sheet('<h3>改密码</h3><p class="muted">' + esc(S.me.name) +
    '　账号 ' + esc(S.me.username || '（还没设账号）') + '</p>' +
    '<div class="field"><label>现在的密码</label><input id="po" type="password" autocomplete="current-password"></div>' +
    '<div class="field"><label>新密码</label><input id="pn" type="password" autocomplete="new-password"></div>' +
    '<div class="field"><label>新密码再输一次</label><input id="pn2" type="password" autocomplete="new-password"></div>' +
    '<button class="btn wide" id="go">存好</button>' +
    '<div class="muted" style="margin-top:10px">改完别的设备要重新登录，这台不用。' +
    '密码至少 4 位，简单的也可以，别写在别人看得见的地方。</div>',
    box => {
      $('#go', box).addEventListener('click', async () => {
        const a = $('#pn', box).value, b = $('#pn2', box).value;
        if (a !== b) return err({ message: '两次输的新密码不一样' });
        try {
          const r = await api('POST', '/api/me/password',
            { old: $('#po', box).value, new: a });
          closeSheet(); toast(r.note || '改好了');
        } catch (e) { err(e); }
      });
    });
}

/* ------------------------------------------------------------------ 顶层 */
/* 两套导航：家长是协会的公告板（总览/审核/打分/发布/我的），
   孩子是游戏世界的 5 格底栏。两套的图标表、分屏表、二级页归属都跟各自的
   样式放在一起，改哪边不用先在脑子里分辨「这段到底给谁用」。 */

function renderTabs() {
  if (!S.isParent) { CHILD.renderTabs(); return; }
  const cur = P_TAB_OF[S.view] || 'home';
  $('#tabs').classList.remove('many');
  $('#tabs').innerHTML = '<div class="nav-pill">' + P_TABS.map(t =>
    '<button type="button" class="nav-item' + (cur === t[0] ? ' on' : '') +
    '" data-v="' + t[0] + '">' + pic(t[1], 22) + '<span>' + t[2] + '</span></button>').join('') +
    '</div>';
  $$('#tabs button').forEach(b => b.addEventListener('click', () => pGo(b.dataset.v)));
}

function renderTop() {
  // 两端都没有顶栏。家长端是这次换皮去掉的：切孩子搬到打分页头上的小胶囊，
  // 「我是谁」搬到「我的」页的身份卡。留一个空实现，是为了让调用顺序两边一致。
  if (!S.isParent) { CHILD.renderTop(); return; }
}

/* 点「我的」页身份卡开的那个弹层。v19 起这里不再提供「切换成别人」——
   账号密码下，换成另一个人就是用他的账号重新登录，点一下就能变成孩子身份
   等于密码白设了。 */
function whoSheet() {
  const me = S.me;
  sheet('<h3>' + esc(me.name) + '</h3>' +
    '<p class="muted">账号　' + esc(me.username || '（还没设账号）') + '　' +
    (me.role === 'parent' ? '家长 · 只打分' : '孩子 · 玩游戏') +
    (me.is_admin ? '　管理员' : '') + '</p>' +
    '<button class="btn wide line" id="chpw">改密码</button>' +
    '<button class="btn wide line" id="logout" style="margin-top:8px">退出登录</button>' +
    '<div class="muted" style="margin-top:10px">要换成别人，先退出，再用他的账号进。</div>',
    box => {
      $('#chpw', box).addEventListener('click', () => { closeSheet(); changePwSheet(); });
      $('#logout', box).addEventListener('click', async () => {
        await api('POST', '/api/logout');
        closeSheet(); S.me = null; S.data = {}; S.view = null; await boot();
      });
    });
}

/* ------------------------------------------------------------------ 家人账号 */
/* 谁能对谁做什么，一句话：管理员对谁都行，家长只对自己的孩子，
   孩子只能改自己的。这条线在前后端各写一遍是有意的 ——
   前端藏按钮是为了不让人白点，后端拦是为了不让人绕过去。 */
function memberTag(m) {
  let t = m.role === 'parent' ? '<span class="tag">家长</span>' : '<span class="tag ok">孩子</span>';
  if (m.is_admin) t += ' <span class="tag gold">管理员</span>';
  return t;
}

function canResetPassword(me, m) {
  if (me.is_admin) return true;
  return me.role === 'parent' && m.role === 'child';
}

/* ------------------------------------------------------------------ 头像 */
/* 给谁换、谁来点，是两条不同的权限路：
     · 换自己的      POST /api/me/avatar   —— 谁都行。头像是自己那张脸
     · 换别人的      PATCH /api/members/:id —— 管理员对谁都行，家长只对孩子
   所以这里按「是不是我自己」分流，而不是按角色分流。                     */
function avatarSheet(m, after) {
  const me = S.me || {};
  const mine = !m || m.id === me.id;
  const target = mine ? me : m;
  const cur = String(target.avatar || '');
  let h = '<h3>换头像</h3><p class="muted">' +
    (mine ? '挑一个。头像不参与分数、额度和排名，这一张是你自己的脸。'
      : '挑一个给 ' + esc(target.name) + '。头像不影响他的分数和额度。') + '</p>';

  if (!AVATAR_GROUPS.length) {
    h += '<div class="notice warn">头像清单没加载出来（avatars.js 没取到）。' +
      '先不换也不影响用。</div>';
  } else {
    h += '<div class="card pad">' + AVATAR_GROUPS.map(g =>
      '<div class="av-gp">' + esc(g.g) + '</div><div class="av-grid">' +
      g.items.map(a => '<button type="button" class="av-pick' + (cur === a.t ? ' on' : '') +
        '" data-av="' + a.t + '" title="' + esc(a.l) + '" aria-label="' + esc(a.l) + '">' +
        avatarHTML({ avatar: a.t, name: '' }, 46) + '</button>').join('') +
      '</div>').join('') + '</div>';
  }

  sheet(h, box => {
    $$('[data-av]', box).forEach(b => b.addEventListener('click', async () => {
      try {
        if (mine) await api('POST', '/api/me/avatar', { avatar: b.dataset.av });
        else await api('PATCH', '/api/members/' + target.id, { avatar: b.dataset.av });
        closeSheet(); toast('换好了');
        // 顶上和列表里的头像都是启动时抓的一份，不重拉一遍还是旧的那张。
        // 这里不 boot()：那一下会把「家人账号」那一层也一起关掉。
        await refreshMembers();
        if (after) await after(); else await render();
      } catch (e) { err(e); }
    }));
  });
}

async function membersSheet() {
  let d;
  try { d = await api('GET', '/api/members'); } catch (e) { return err(e); }
  const me = S.me;
  const lists = d.members;
  const notYet = lists.filter(m => !m.has_password);

  let h = '<h3>家人账号</h3><p class="muted">账号就是名字。' +
    '密码只有本人知道，忘了就让家长或管理员重置一个。</p>';

  if (notYet.length) {
    h += '<div class="notice warn">还有 ' + notYet.length + ' 个没设密码（' +
      notYet.map(m => esc(m.name)).join('、') + '）。没设密码的人进不来。</div>';
  }

  /* 一行拆三层：名字 / 账号 / 按钮。
     原来这四样挤在同一条横线上，按钮一多就把名字压成一字一行 —— 跟账号
     长短无关，短名也一样坏。拆开之后账号再长也只是自己折行，压不到别人。 */
  h += '<div class="card">' + lists.map(m =>
    '<div class="item mem-row">' +
    '<div class="mem-line">' + avatarHTML(m, 34) +
    '<div class="txt"><div class="nm">' + esc(m.name) + ' ' + memberTag(m) +
    (m.id === me.id ? ' <span class="tag blue">我自己</span>' : '') + '</div></div>' +
    '<div class="mem-pw">' + (m.has_password ? '<span class="ds">密码已设</span>'
      : '<span class="no-t">还没设密码</span>') + '</div></div>' +
    '<div class="mem-line mem-line--acc"><span class="mem-key">账号</span>' +
    '<span class="mem-acc">' + esc(m.username || '—') + '</span></div>' +
    '<div class="wact">' +
    (canResetPassword(me, m) && m.id !== me.id
      ? '<button class="btn sm' + (m.has_password ? ' line' : '') +
        '" data-mpw="' + m.id + '">' + (m.has_password ? '重置密码' : '设密码') + '</button>' : '') +
    (me.is_admin
      ? '<button class="btn sm ghost" data-medit="' + m.id + '">改名</button>' : '') +
    (me.is_admin || m.id === me.id || (me.role === 'parent' && m.role === 'child')
      ? '<button class="btn sm ghost" data-mav="' + m.id + '">换头像</button>' : '') +
    (me.is_admin && m.id !== me.id && m.active !== 0
      ? '<button class="btn sm ghost" data-mdel="' + m.id + '">停用</button>' : '') +
    '</div></div>').join('') + '</div>';

  if (me.is_admin) {
    h += '<div class="hr"></div>' +
      '<div class="muted">开通一个新人。密码给完就能用，' +
      '旧记录一律不动。</div>' +
      '<button class="btn wide" id="mAdd" style="margin-top:10px">添加家人</button>';
  } else {
    h += '<div class="hr"></div><div class="muted">开通新账号是管理员的事。' +
      '现在管理员是 ' + esc((lists.filter(x => x.is_admin)[0] || {}).name || '（未指定）') + '。</div>';
  }

  sheet(h, box => {
    $$('[data-mpw]', box).forEach(b => b.addEventListener('click', () => {
      const m = lists.filter(x => x.id === +b.dataset.mpw)[0];
      closeSheet(); memberPwSheet(m, me);
    }));
    $$('[data-medit]', box).forEach(b => b.addEventListener('click', () => {
      const m = lists.filter(x => x.id === +b.dataset.medit)[0];
      closeSheet(); memberEditSheet(m, me);
    }));
    $$('[data-mav]', box).forEach(b => b.addEventListener('click', () => {
      const m = lists.filter(x => x.id === +b.dataset.mav)[0];
      closeSheet(); avatarSheet(m);
    }));
    $$('[data-mdel]', box).forEach(b => b.addEventListener('click', async () => {
      const m = lists.filter(x => x.id === +b.dataset.mdel)[0];
      try {
        await api('DELETE', '/api/members/' + m.id);
        closeSheet(); toast(m.name + ' 已停用，记录都留着'); await membersSheet();
      } catch (e) { err(e); }
    }));
    const add = $('#mAdd', box);
    if (add) add.addEventListener('click', () => { closeSheet(); memberAddSheet(); });
  });
}

/* 换了名字 / 头像 / 口令之后只把成员表重拉一遍。
   以前这里一律 boot()（整机重启），那一下会把弹层栈整个塌掉：
   从「设置 → 家人账号 → 改某某」保存完直接回到「我的」，还得从头点进去。 */
async function refreshMembers() {
  try {
    const b = await api('GET', '/api/bootstrap');
    if (b.members && b.members.length) S.members = b.members;
    if (b.me) S.me = b.me;
  } catch (e) { /* 拉不动就沿用旧的，别为了刷新把这一屏弄没了 */ }
}

function memberPwSheet(m, me) {
  const reset = !!m.has_password;
  sheet('<h3>' + (reset ? '重置 ' : '给 ') + esc(m.name) + (reset ? ' 的密码' : ' 设密码') + '</h3>' +
    '<p class="muted">' + (reset
      ? '旧密码就不用了。设完他下次要用新的进，别的设备上会退出来。'
      : '设完他就能登录了。') + '　账号　' + esc(m.username || '—') + '</p>' +
    '<div class="field"><label>新密码</label>' +
    '<input id="np" type="password" autocomplete="new-password"></div>' +
    '<div class="field"><label>再输一次</label>' +
    '<input id="np2" type="password" autocomplete="new-password"></div>' +
    '<button class="btn wide" id="go">' + (reset ? '重置' : '设好') + '</button>' +
    '<div class="muted" style="margin-top:10px">' +
    (m.id === me.id ? '这是你自己，改完别的设备要重新登录。'
      : '当面告诉他，别发在群里。密码至少 4 位。') + '</div>',
    box => {
      $('#go', box).addEventListener('click', async () => {
        const a = $('#np', box).value, b = $('#np2', box).value;
        if (a !== b) return err({ message: '两次输的密码不一样' });
        try {
          const r = await api('POST', '/api/members/' + m.id + '/password', { password: a });
          toast(r.note || '设好了');
          await membersSheet();      // 退回「家人账号」那一层，不是塌回「我的」
        } catch (e) { err(e); }
      });
    });
}

function memberEditSheet(m, me) {
  sheet('<h3>改 ' + esc(m.name) + '</h3>' +
    '<div class="field"><label>名字</label><input id="nm" value="' + esc(m.name) + '"></div>' +
    '<div class="field"><label>账号名</label><input id="un" value="' + esc(m.username || '') + '"></div>' +
    (m.role === 'parent' && !m.is_admin
      ? '<button class="btn wide line" id="mAdmin">把管理员交给他</button>' : '') +
    '<button class="btn wide" id="go" style="margin-top:10px">保存</button>' +
    (m.id === me.id ? '<div class="muted" style="margin-top:10px">改了自己的账号名，下次要用新的登。</div>' : ''),
    box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          await api('PATCH', '/api/members/' + m.id,
            { name: $('#nm', box).value, username: $('#un', box).value });
          toast('存好了');
          await refreshMembers();
          await membersSheet();      // 退回「家人账号」那一层，不是塌回「我的」
        } catch (e) { err(e); }
      });
      const ma = $('#mAdmin', box);
      if (ma) ma.addEventListener('click', async () => {
        try {
          await api('PATCH', '/api/members/' + m.id, { is_admin: 1 });
          closeSheet(); toast('管理员已经交给 ' + m.name + '，你这边就只剩打分和重置孩子的密码');
          await boot();
        } catch (e) { err(e); }
      });
    });
}

function memberAddSheet() {
  sheet('<h3>添加家人</h3><p class="muted">账号和密码一起给，给完就能进。</p>' +
    '<div class="field"><label>名字</label><input id="nm" placeholder="例如：奶奶"></div>' +
    '<div class="field"><label>身份</label><select id="role">' +
    '<option value="child">孩子（玩游戏、被打分）</option>' +
    '<option value="parent">家长（只打分、不进游戏）</option></select></div>' +
    '<div class="field"><label>账号名</label><input id="un" placeholder="留空就用名字"></div>' +
    '<div class="field"><label>密码</label><input id="pw" type="password" autocomplete="new-password"></div>' +
    '<button class="btn wide" id="go">开通</button>' +
    '<div class="muted" style="margin-top:10px">家长最多 2 位，孩子最多 3 个。' +
    '生日礼物、零花钱这些线下的东西，系统只记账。</div>',
    box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          const r = await api('POST', '/api/members', {
            name: $('#nm', box).value, role: $('#role', box).value,
            username: $('#un', box).value, password: $('#pw', box).value });
          closeSheet(); toast(r.note || '开通了'); await membersSheet();
        } catch (e) { err(e); }
      });
    });
}

/* ------------------------------------------------------------------ 路由 */
async function render() {
  const v = $('#view');
  // 换内容之前先把滚动位置攥住：家长端滚的是 #view 自己，孩子端滚的是它里面
  // 那个 .content。innerHTML 一清，两个 scrollTop 都归零，再填回来也不会自己
  // 回到刚才那一屏 —— 于是每次保存、每次点「同意」，页面都弹回顶上。
  // 切屏的入口（pGo / 孩子端 kGo）会先把它们清成 0，所以换屏仍然是回到顶上。
  const keepV = v.scrollTop;
  const oldC = v.querySelector('.content');
  const keepC = oldC ? oldC.scrollTop : 0;
  v.innerHTML = '<div class="empty">加载中…</div>';
  try {
    if (S.isParent) {
      pSprite();
      const P = {
        home: renderAdminHome, review: renderAdminReview, publish: renderAdminPublish,
        score: renderAdminScore, month: renderAdminMonth, me: renderAdminMe,
        logs: renderAdminLogs, chest: renderParentChest, shop: renderParentShop,
        family: renderFamily, wish: renderParentWish, settings: renderAdminSettings,
        kid: renderKidDetail, history: renderKidHistory,
      };
      await (P[S.view] || renderAdminHome)(v);
    } else {
      // 孩子端 12 屏全在 child.js：糖果冒险那套皮，数据与动作还是原来那些接口。
      await CHILD.render();
    }
    renderTop();
    startTkTick();
    startTicketPoll();
  } catch (e) {
    // 渲染挂了整页就是空的，这里不能再无声吞掉。
    // 两个必须保留的动作：① console.error 打出来，巡检靠它抓；
    // ② 页面上给一句人话 + 原始信息，用户看到的不能是一句孤零零的 is not defined。
    // 曾经这里只写 '<div class="empty">' + e.message + '</div>'，
    // 结果 e2e 的「空视图」断言把它当成有内容放过去了（长度 > 8），
    // 于是「某个 tab 一进去就报错」能一路走到用户面前。
    console.error('[render] ' + (S ? S.view : '') + ':', e);
    var _msg = String((e && e.message) || e);
    v.innerHTML = '<div class="card pad"><div class="nm">这个页面没能显示出来</div>' +
      '<div class="ds muted">' + esc(_msg) + '</div>' +
      '<div class="ds muted">退出去再进来一次；还是这样，把上面这句记下来。</div></div>';
  }
  v.scrollTop = keepV;
  const newC = v.querySelector('.content');
  if (newC) newC.scrollTop = keepC;
}

/* ------------------------------------------------------------------ 星球等级 */
function levelName(lv) {
  if (!lv) return '';
  return 'LV ' + lv.level + '　' + lv.title;
}

// 孩子端顶部的英雄面板：名字、星尘、星球等级、升级进度
function heroHTML(lv, opt) {
  opt = opt || {};
  const me = S.me;
  let h = '<div class="hero"><div class="hero-top">' +
    '<div class="hero-av">' + avatarHTML(me, 44) + '</div>' +
    '<div class="hero-id"><span class="eyebrow" style="color:rgba(255,255,255,.62)">' +
    esc(opt.kicker || '我的星球') + '</span><h2>' + esc(me.name) + '</h2>' +
    '<div class="sub">' + esc(opt.sub || '') + '</div></div>' +
    (opt.stardust == null ? '' : '<div class="hero-bal"><b>' + num(opt.stardust) +
      '</b><span>星尘</span></div>') +
    '</div>';
  if (lv) {
    h += '<div class="lv-line"><span class="lv-chip">LV <strong>' + lv.level + '</strong></span>' +
      '<span class="lv-title">' + esc(lv.title) + '</span>' +
      '<span class="lv-xp">' + num(lv.total) + ' / ' +
      num(lv.next ? lv.next.threshold : lv.threshold) + '</span></div>' +
      '<div class="xp-track"><i style="width:' + lv.percent + '%"></i></div>' +
      '<div class="hero-note">' + (lv.next
        ? '再攒 ' + num(lv.need) + ' 星尘升到「' + esc(lv.next.title) + '」。花掉的星尘不算，等级只升不降。'
        : '已经是最高一档了，往上只有你自己。') + '</div>';
  }
  if (opt.stats && opt.stats.length) {
    h += '<div class="hero-stats">' + opt.stats.map(s =>
      '<div><span>' + esc(s[0]) + '</span><strong>' + esc(s[1]) + '</strong></div>').join('') + '</div>';
  }
  return h + '</div>';
}

function ladderHTML(tiers, cur) {
  return '<div class="ladder">' + tiers.map(t => {
    const on = cur && t.level === cur.level;
    return '<div class="' + (on ? 'on' : '') + '"><b>' + esc(t.title) + '</b>' + t.threshold + '</div>';
  }).join('') + '</div>';
}

/* 七档箱子横过来一条。宝箱栏和「这周」栏共用这一处 —— 同一组门槛在两个页面
   各画一遍，改一处漏一处的时候两边显示的档位就会对不上。
   v24 给每一格加了「几张券」：以前只写分数，站在「这周」那一页根本看不出
   35 分意味着十张券，得点进宝箱栏才知道。已够的格子底色变浅，当前这一档描边。 */
function boxLadderHTML(tiers, snap) {
  const energy = (snap && snap.energy) || 0;
  const cur = snap && snap.tier ? snap.tier.tier : null;
  return '<div class="boxtrack">' + (tiers || []).map(t => {
    const got = energy >= t.threshold;
    const on = cur === t.tier;
    const nCard = (t.card_count != null)
      ? t.card_count
      : (t.cards || []).reduce((a, c) => a + (c.count || 0), 0);
    return '<div class="' + (got ? 'got' : '') + (on ? ' on' : '') + '">' +
      '<b>' + esc(t.name) + '</b>' +
      '<span class="bt-s">' + t.threshold + '</span>' +
      '<span class="bt-c">' + num(t.tickets) + ' 券' +
      (nCard ? ' +' + nCard + ' 卡' : '') + '</span></div>';
  }).join('') + '</div>';
}

function cycleCard(c) {
  let h = '<div class="card pad">' +
    '<div class="row between"><div><div class="big">' + c.energy +
    '<span class="muted" style="font-size:13px"> / ' + (c.tier ? c.tier.threshold : 49) + '</span></div>' +
    '<div class="muted">周能量　固定分 ' + c.fixed_score + '　额外 +' + c.bonus_energy + '</div></div>' +
    '<div style="text-align:right">' +
    (c.tier ? '<div class="tag gold">' + esc(c.tier.name) + '</div>' : '<div class="muted">还没到第一档</div>') +
    '</div></div>';
  h += '<div class="bar" style="margin-top:10px"><i class="gold" style="width:' +
    Math.min(100, Math.round(c.energy / (49 * (c.ratio || 1)) * 100)) + '%"></i></div>';
  if (c.tiers && c.tiers.length) h += boxLadderHTML(c.tiers, c);
  if (c.next_tier) h += '<div class="muted" style="margin-top:8px">再拿 ' + c.next_tier.need + ' 分就到' +
    esc(c.next_tier.name) + '</div>';
  else h += '<div class="muted" style="margin-top:8px">已经拿到最好的箱子了</div>';
  return h + '</div>';
}

/* ================================================================== 首页动态 */
/* 三条线（任务 / 心愿 / 校准）在后端已经拍平成同一副骨架：状态是一句话，
   进度要么是三颗点，要么是一个百分比。前端只负责画，一份代码两个端共用。
   「谁在等谁」由后端排好序，这里不再重排 —— 同一个排序规则写两遍一定会走味。 */
const FEED_TAG = {
  submitted: 'ok', ready: 'ok',
  pending: 'warn', wished: 'warn', debt: 'warn',
  claimed: 'blue', active: 'blue', device: 'blue',
};

function stepsHTML(step, labels) {
  return '<div class="steps">' + labels.map((t, i) =>
    '<span class="stp' + (i < step ? ' on' : '') + '"><b></b>' + esc(t) + '</span>').join('') + '</div>';
}

function feedRow(x, opt) {
  const gk = x.kind === 'task' ? 'task' : (x.kind === 'wish' ? 'wish' : 'task');
  let h = '<div class="item task-row">' + glyph(x.icon, gk, 30) + '<div class="txt">' +
    '<div class="nm">' + (opt.who && x.who ? '<span class="fwho">' + esc(x.who) + '</span>' : '') +
    esc(x.title) + ' <span class="tag ' + (FEED_TAG[x.state_key] || '') + '">' +
    esc(x.state_text) + '</span></div>' +
    // 一条动态里混着任务、心愿、校准三种东西，先报是哪一种再看细节
    '<div class="ds">' + esc(x.kind_text || '') +
    (x.detail ? '　' + esc(x.detail) : '') + '</div>';
  if (x.steps && x.steps.length && x.step) h += stepsHTML(x.step, x.steps);
  if (x.percent != null) {
    h += '<div class="wprog"><div class="bar"><i' + (x.percent >= 100 ? '' : ' class="gold"') +
      ' style="width:' + Math.min(100, x.percent) + '%"></i></div>' +
      (x.text ? '<div class="ds muted">' + esc(x.text) + '</div>' : '') + '</div>';
  }
  h += '</div>';
  // 孩子端那两页要能就地动手：光看见进度、还得自己翻到任务大厅去交，等于没做。
  if (opt.kid && x.task_id && (x.kind === 'task' || x.kind === 'calibration')) {
    if (x.state_key === 'claimed') {
      h += '<button class="btn sm" data-tdone="' + x.task_id + '">做完了</button>' +
        '<button class="btn sm line" data-tgive="' + x.task_id + '">我不做了</button>';
    } else if (x.state_key === 'pending') {
      h += '<button class="btn sm" data-tdone="' + x.task_id + '">做完了</button>';
    }
  }
  if (opt.kid && x.wish_id && x.state_key === 'ready') {
    h += '<button class="btn sm" data-wdone="' + x.wish_id + '">我做到了</button>';
  }
  return h + '</div>';
}

function feedHTML(d, opt) {
  opt = opt || {};
  const items = (d && d.items) || [];
  const recent = (d && d.recent) || [];
  if (!items.length && !recent.length) {
    return '<div class="sec"><div class="sec-h"><h2>动态</h2></div>' +
      '<div class="card pad"><div class="empty">眼下没有在推进的事</div></div></div>';
  }
  let h = '<div class="sec"><div class="sec-h"><h2>动态</h2><span class="sub">' +
    (items.length ? '手上还有 ' + items.length + ' 件没完' : '手头都清干净了') + '</span></div>';
  if (items.length) {
    h += '<div class="card">' + items.map(x => feedRow(x, opt)).join('');
    if (d.total > items.length) {
      h += '<div class="pad muted">还有 ' + (d.total - items.length) + ' 件没列出来</div>';
    }
    h += '</div>';
  }
  if (recent.length) {
    h += '<div class="card" style="margin-top:10px"><div class="fband">最近发生</div>' +
      recent.map(r => '<div class="item"><div class="txt">' +
        '<div class="nm" style="font-weight:550;font-size:13.5px">' +
        (opt.who && r.who ? esc(r.who) + ' ' : '') + esc(r.text) + '</div>' +
        '<div class="ds">' + esc(String(r.ts || '').slice(5, 16)) + '</div></div></div>').join('') +
      '</div>';
  }
  return h + '</div>';
}

/* 任务大厅的三个动作：领、交、放。
   「这周」和大厅页共用这一处，免得同一套规则写两遍、改一处漏一处。 */
function bindTaskActions() {
  $$('#view button[data-tclaim]').forEach(b => b.addEventListener('click', async () => {
    askSheet({
      title: '接这件活',
      hint: '进「我的任务」；中途不想做可以放回去，不扣分',
      ok: '确认接下',
    }, async () => {
      try {
        await api('POST', '/api/tasks/' + b.dataset.tclaim + '/claim');
        closeSheet(); toast('领到了，做完点「交上去」'); render();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-tdone]').forEach(b => b.addEventListener('click', async () => {
    askSheet({
      title: '这件做好了',
      hint: '交给爸爸妈妈看，他们点头就发奖励',
      ok: '我做好了',
    }, async () => {
      try {
        await api('POST', '/api/tasks/' + b.dataset.tdone + '/submit');
        closeSheet(); toast('交了，等爸爸妈妈确认'); render();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-tgive]').forEach(b => b.addEventListener('click', () => {
    const tid = +b.dataset.tgive;
    sheet('<h3>不做了？</h3><p class="muted">这件会回到大厅，别人能接着领。' +
      '想好了再点。</p><button class="btn wide" id="giveGo" style="margin-top:10px">我不做了</button>',
      box => {
        $('#giveGo', box).addEventListener('click', async () => {
          try {
            await api('POST', '/api/tasks/' + tid + '/abandon');
            closeSheet(); toast('放回去了'); render();
          } catch (e) { err(e); }
        });
      });
  }));
  // 首页动态里那条「够了，可以兑现」的心愿，按钮是 data-wdone，
  // 绑定只写在 bindWishActions 里一处 —— 两个函数都给同一个按钮挂监听的话，
  // 点一下会跑两遍（心愿登记两次、弹层叠两层）。
}

/* 心愿的三个动作用同一套文案：孩子端（许愿屋）和家长端（心愿单）都走它。 */
function askWishDone(id, after) {
  askSheet({
    title: '这条心愿达成了',
    hint: '确认是这一条心愿，点完进已达成且不能改回去',
    ok: '确认达成',
  }, async () => {
    await api('POST', '/api/wishes/' + id + '/status', { status: 'achieved' });
    closeSheet(); toast('记下了，跟爸爸妈妈说一声');
    if (after) await after(); else await render();
  });
}

/* ================================================================== 孩子端 · 许愿屋 */
/* 心愿单三个动作：孩子许愿 → 家长定条件 → 达成兑现。
   这一页是整套系统里孩子唯一能自己发起的地方，所以「我想要什么」的入口
   必须长在这一页上。以前心愿只能家长建，孩子能做的只有看，那条通道是堵的。 */
const WISH_COND = {
  fixed: '固定分达标', stardust: '星尘自付', task_count: '完成任务数',
  streak: '连续达标', perfect_day: '完美日',
  custom: '自己写一条', any: '多选条件',
};
const WISH_COND_HINT = {
  fixed: '本周期（周六到周五）攒够这些固定分，星探和任务的分不算',
  stardust: '自己拿出这么多星尘。掏钱这个动作本身就在训练取舍',
  task_count: '条件定下来之后，交掉几件爸爸妈妈发布的任务',
  streak: '连着几个周期的固定分都到线，断一周就从头数',
  perfect_day: '本月集满几个「7 项全满」的日子，门槛最高，留给大愿望',
  custom: '你写一句话，系统算不了它 —— 没有进度条。他做完了点一下，你确认就算成',
  any: '下面勾两条以上，再定「做到其中几条算成」。这几条不用都做到，凑够条数就行',
};
const WISH_DEFAULT = { fixed: 49, stardust: 100, task_count: 3, streak: 2, perfect_day: 5 };
/* 「多选条件」里允许勾的六条：v26 起六条全放。
   v25 把「星尘自付」挡在外面，理由是那一条到点了还得再付一次钱；现在让它进来，
   但付钱这一步仍然只有孩子自己能点（后端只看 paid、不看余额），他可以选走这条路，
   也可以把星尘留着、靠别的条凑数。
   「自己写一条」进来也一样：它不参与自动计数，含它的心愿随时可以点「我做到了」，
   够不够由家长在确认那一步看。 */
const ANY_COND_KEYS = ['fixed', 'stardust', 'task_count', 'streak', 'perfect_day', 'custom'];
const ANY_COND_NEED = 1;      // 「做到其中几条算成」的默认值

function wishCondText(w) {
  const c = w.cond || {};
  const note = w.price_note ? '　' + w.price_note : '';
  // 自定义那条的「条件」就是那句话本身，别再在前面挂一个条件名
  if (w.cond_type === 'custom') return (c.text || WISH_COND.custom) + note;
  if (w.cond_type === 'any') {
    const items = c.items || [];
    const parts = items.map(it => it.type === 'custom'
      ? (it.text || WISH_COND.custom)
      : (WISH_COND[it.type] || it.type) + ' ' + num(it.value));
    const need = +c.need >= 1 ? +c.need : ANY_COND_NEED;
    if (!parts.length) return WISH_COND.any + note;
    return parts.join('、') + '　其中做到 ' +
      (items.length > 1 && need > 1 ? need + ' 条' : '一条') + '就算' + note;
  }
  const t = WISH_COND[w.cond_type] || w.cond_type || '';
  const n = c.value !== undefined ? c.value
    : (c.amount !== undefined ? c.amount : (c.count !== undefined ? c.count : null));
  return t + (n === null ? '' : ' ' + num(n)) + note;
}

/* 一条心愿的进度条。cur/target/percent 和那句话都由后端算 ——
   withSubs 传 false 时不列下面那排子条件（孩子端自己会列一排可操作的）。
   各种条件各自的锚点不一样（本周期 / 本月 / 定条件那天起 / 余额 / 连着几周），
   在前后端各写一遍一定对不上。这里只负责画。

   v25 两种新形态各画各的：
   · 自己写一条（manual）没有百分比，也不能画一根一直停在 0% 的条 ——
     那看起来像「做到了一点」，其实是「系统根本算不了」。这里只把那句话和
     「靠谁判」写清楚。
   · 多选条件（any）主条画的是**做到几条 / 要几条**（后端给的 percent），
     下面把每一条各列一行。列出来不是为了好看：不列的话，孩子看到
     「还差 2 条」也不知道是哪两条在差。子行里那句「靠人判」代替百分比 ——
     自定义那条本来就没有百分比，写个 0% 是在撒谎。 */
function wishProgHTML(x, withSubs) {
  const p = x.progress;
  if (!p || !p.known) return '';
  // 孩子端下面还有一排「按条」的（每行带按钮），这里再列一次就是同样两排条件。
  // 家长端没有那一排，所以默认还是列出来。
  const showSubs = withSubs !== false;
  if (p.manual) {
    // 带一个 wmanual：这条没有进度条，界面上和别的条件长得不一样是应该的，
    // 留个类名让「哪条在算、哪条靠人判」在 DOM 层面也分得开（巡检靠它断言）。
    return '<div class="wprog wmanual"><div class="ds">' + esc(p.text || '') + '</div>' +
      (p.where ? '<div class="ds muted">' + esc(p.where) + '</div>' : '') + '</div>';
  }
  const pc = (p.percent == null ? 0 : p.percent);
  return '<div class="wprog">' +
    '<div class="row between"><span class="ds">' + esc(p.text) + '</span>' +
    '<span class="tag ' + (p.done ? 'ok' : 'gold') + '">' + pc + '%</span></div>' +
    '<div class="bar" style="margin-top:6px"><i' + (p.done ? '' : ' class="gold"') +
    ' style="width:' + pc + '%"></i></div>' +
    (showSubs && (p.subs || []).length
      ? '<div class="wsubs" style="margin-top:7px">' + p.subs.map(s =>
        '<div class="row between"><span class="ds ' + (s.done ? 'ok-t' : 'muted') + '">' +
        (s.done ? '✓ ' : '') + esc(s.text) + '</span>' +
        '<span class="ds muted">' +
        (s.percent == null ? (s.manual ? '靠人判' : '—') : s.percent + '%') +
        '</span></div>').join('') +
        '</div>' : '') +
    (p.where ? '<div class="ds muted">' + esc(p.where) + '</div>' : '') +
    '</div>';
}

/* 一条子条件一行（v29）。
   每一行只回答两件事：这一条走到哪一步了，下一步该谁按。
   系统算得出来的那几条（分数、星尘、任务数）不需要提交 —— 算够了就是够了，
   再让人替一件已经成立的事实去等审批，是把判定权从系统手里收回给大人。
   只有家长自己写的那句话才要交上去等人点头，所以只有那一行有「我做到了」。 */
function wishSubRow(w, s) {
  let cls = '', right = '';
  if (s.pending) {
    cls = ' pend';
    right = '<span class="tag blue">等确认</span>';
  } else if (s.done) {
    cls = ' done';
    right = '<span class="tag ok">✓ 做到了' + (s.by ? '（' + esc(s.by) + '确认）' : '') + '</span>';
  } else if (s.rejected) {
    cls = ' rej';
    right = '<button class="btn sm ghost" data-wsubmit="' + w.id + '">再提交</button>';
  } else if (s.manual) {
    right = '<button class="btn sm" data-wsubmit="' + w.id + '">我做到了</button>';
  } else if (s.key === 'stardust' && s.can_pay) {
    right = '<button class="btn sm" data-wself="' + w.id + '" data-wselfpay="' +
      num(s.target) + '">付掉 ' + num(s.target) + ' 星尘</button>';
  } else {
    right = '<span class="ds muted">' +
      (s.percent == null ? '不算' : s.percent + '%') + '</span>';
  }
  return '<div class="wsub' + cls + '">' +
    '<div class="row between"><span class="ds">' + (s.done ? '✓ ' : '') +
    esc(s.text) + '</span>' + right + '</div>' +
    (s.pending
      ? '<div class="ds muted">' + esc(s.where || '已经交给爸爸妈妈了') + '</div>' +
        // 驳回之后再交一次，那条理由会被新提交顶掉 —— 而它正是他接着改的依据
        (s.last_reject_note
          ? '<div class="ds tk-no">上一次没通过：' + esc(s.last_reject_note) + '</div>' : '')
      : '') +
    (s.rejected ? '<div class="ds tk-no">没通过：' + esc(s.reject_note || '') + '</div>' : '') +
    (s.key === 'stardust' && s.can_pay
      ? '<div class="ds muted">不想花星尘，也可以靠别的条件凑够 —— 走哪条路由你自己定。</div>' : '') +
    (s.manual || s.rejected
      ? '<div class="wsubmit" hidden><input class="inp" placeholder="写一句你做了什么（可以不写）">' +
        '<button class="btn sm" data-wsend="' + w.id + '">交给爸爸妈妈</button></div>'
      : '') +
    '</div>';
}

/* 单条条件（不是多选）那一行。整条心愿就是那一个条件，
   所以这里只处理「该不该给他一个按钮」这一点。 */
function wishSelfRow(w, p) {
  if (p.key === 'custom') {
    return '<div class="wsubs" style="margin-top:9px">' + wishSubRow(w, {
      key: 'custom', text: p.text || w.title, manual: true, done: p.done,
      pending: p.pending, rejected: p.rejected, reject_note: p.reject_note,
      by: p.by, where: p.where, percent: null,
    }) + '</div>';
  }
  if (p.can_pay) {
    return '<div class="wsubs" style="margin-top:9px"><div class="wsub">' +
      '<div class="row between"><span class="ds">星尘够了，走这条路就自己点一下付掉；' +
      '不想花星尘，也可以靠别的条件凑够。</span>' +
      '<button class="btn sm" data-wself="' + w.id + '" data-wselfpay="' + num(p.target) +
      '">付掉 ' + num(p.target) + ' 星尘</button></div></div></div>';
  }
  return '';
}

/* 提醒事项。它是「别忘了」，不是「现在该做什么」——
   以前它跟条件挤在一起，同样是灰字，孩子分不清哪句是要去做的。 */
function wishNotesHTML(x) {
  const parts = [];
  if (x.reward_desc) parts.push(esc(x.reward_desc));
  if (x.price_note) parts.push(esc(x.price_note));
  if (x.selfpay_stardust) {
    parts.push('这笔 ' + num(x.selfpay_stardust) + ' 星尘已经付掉了，中途放弃会全额退回。');
  }
  if (!parts.length) return '';
  return '<div class="wnote"><div class="wnote-h">提醒</div>' +
    parts.map(t => '<div class="ds muted">' + t + '</div>').join('') + '</div>';
}

/* 心愿页的三个动作：交一条、付星尘、登记达成。 */
function bindWishActions() {
  $$('#view button[data-wsubmit]').forEach(b => b.addEventListener('click', () => {
    const box = b.parentNode.querySelector('.wsubmit');
    if (!box) return;
    box.hidden = !box.hidden;
    if (!box.hidden) { const i = box.querySelector('input'); if (i) i.focus(); }
  }));
  $$('#view button[data-wsend]').forEach(b => b.addEventListener('click', async () => {
    const box = b.parentNode;
    const note = box.querySelector('input');
    askSheet({
      title: '这一条我做到了',
      hint: '这条交给爸爸妈妈看，他们确认后就达成',
      ok: '我做到了',
    }, async () => {
      try {
        await api('POST', '/api/wishes/' + b.dataset.wsend + '/submit',
          { cond_key: 'custom', note: note ? note.value.trim() : '' });
        closeSheet(); toast('交上去了，等爸爸妈妈确认');
        await render();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-wself]').forEach(b => b.addEventListener('click', async () => {
    const pay = +b.dataset.wselfpay || 0;
    askSheet({
      title: '付掉 ' + num(pay) + ' 星尘',
      hint: '立刻从你账上扣 ' + num(pay) + ' 星尘，真正需要的时候再用',
      ok: '确认支付',
    }, async () => {
      try {
        const r = await api('POST', '/api/wishes/' + b.dataset.wself + '/pay');
        closeSheet(); toast('付掉了，还剩 ' + num(r.balance) + ' 星尘'); await render();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-wdone]').forEach(b => b.addEventListener('click', async () => {
    askWishDone(b.dataset.wdone);
  }));
}

/* 历史心愿默认收起。它不是每天要看的东西，但也不能删掉 ——
   撤掉的那条如果凭空消失，孩子下次许愿会当成「写了也白写」。 */
let WISH_HIST_OPEN = false;

/* 一条结束的心愿。四种结束方式在孩子那儿是四句不同的话：
   被驳回是「你不同意」，自己放弃是「我自己不要了」，
   家长撤掉是「这事不算了」，自己撤了是「我改主意了」。
   全画成「已结束」，这一栏就等于没写。 */
function wishHistRow(x) {
  let cls = 'tag', label = '已结束';
  if (x.status === 'achieved') { cls = 'tag ok'; label = '已达成'; }
  else if (x.status === 'claimed') { cls = 'tag ok'; label = '已兑现'; }
  else if (x.status === 'cancelled' && x.closed_from) {
    // 老库里结束的心愿没留下「谁点的」，那种退化成「已结束」，不猜名字
    const by = x.closed_by ? memberOf(x.closed_by) : null;
    const adult = !!(by && by.role !== 'child');
    if (x.closed_from === 'wished') label = adult ? '被驳回' : '自己撤了';
    else label = adult ? '被撤掉' : '自己放弃';
    cls = 'tag warn';
  }
  const when = String(x.claimed_at || x.achieved_at || x.cancelled_at || x.created_at || '').slice(0, 10);
  return '<div class="item">' + glyph(x.icon, 'wish', 28) +
    '<div class="txt"><div class="nm">' + esc(x.title) +
    ' <span class="' + cls + '">' + label + '</span></div>' +
    (x.cond_type ? '<div class="ds">条件　' + esc(wishCondText(x)) + '</div>' : '') +
    '<div class="ds muted">' + esc(when) + '</div></div></div>';
}

/* 孩子许愿。只问「想要什么」，条件的坑留给家长填 ——
   如果这里也让填条件，孩子会照着最容易达标的那一档写，这张表就变成猜谜了。 */
function wishNewSheet() {
  sheet('<h3>我想要……</h3>' +
    '<p class="muted">写清楚想要什么，越具体越好。「一本《XX》45 元」比「想要个礼物」好，' +
    '具体的东西才算得出条件，也才谈得成。写完先挂在墙上，' +
    '爸爸妈妈定下「怎么才算够格」它就开始算。</p>' +
    '<div class="field"><label>想要什么</label>' +
    '<input id="wn" placeholder="例如：去天文馆看球幕" maxlength="40"></div>' +
    '<div class="field"><label>为什么想要（可选）</label>' +
    '<input id="ww" placeholder="例如：同桌说那个球幕躺下看特别震撼"></div>' +
    '<button class="btn wide" id="wgo">挂上去</button>', box => {
    $('#wgo', box).addEventListener('click', async () => {
      const title = $('#wn', box).value.trim();
      if (!title) { toast('先写想要什么'); return; }
      try {
        await api('POST', '/api/wishes', { title: title, reward_desc: $('#ww', box).value });
        closeSheet(); toast('挂上了，等爸爸妈妈定条件'); await render();
      } catch (e) { err(e); }
    });
  });
}

/* ================================================================== 孩子端 · 宝箱 */

/* 一个箱子里面到底有什么。宝箱栏和商店都用它，写两处迟早会对不上。
   v24 起保底卡可能不止一张（完美箱是普 + 稀 + 传），所以从 cards 列表读，
   老接口只给 card_rarity 的时候退回单张的写法。
   v25：商店那一份（t.purchased）不写概率。买来的箱子本来就不出随机件
   —— 后端把它的 random_rate 直接给 0 了，这里再明说一句：
   「不含随机件」比省略不说清楚，省得孩子拿宝箱栏那张概率表来对。 */
function boxContentText(t) {
  const p = ['保底 ' + num(t.tickets) + ' 张券'];
  if (t.stardust) p.push(num(t.stardust) + ' 星尘');
  const cards = t.cards || [];
  if (cards.length) {
    p.push('必出 ' + cards.map(c => (RAR[c.rarity] || '') + '卡 ×' + (c.count || 1)).join('、'));
  } else if (t.card_rarity) {
    p.push('必出 1 张' + (RAR[t.card_rarity] || '') + '卡');
  }
  if (t.purchased) {
    p.push('不含随机件');
    return p.join('　');
  }
  if (t.random_rate) p.push(Math.round(t.random_rate * 100) + '% 出随机件');
  if (t.diamond_rate) p.push(Math.round(t.diamond_rate * 100) + '% 出钻石级');
  return p.join('　');
}

function confirmBuyBox(tier, price) {
  sheet('<h3>直购宝箱</h3><p class="muted">花 ' + price + ' 星尘买第 ' + tier +
    ' 档。买来的箱子没有随机件，开出什么买之前就写清楚了，而且永远比打出来贵。</p>' +
    '<button class="btn wide" id="go">确认花 ' + price + ' 星尘</button>', box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          const r = await api('POST', '/api/boxes/buy', { member_id: S.me.id, tier: tier });
          closeSheet();
          // v38：直购是付完星尘当场开，孩子端补同一段开箱动画（打出来的箱、
          // 买来的箱都从这一段过）。家长端没有开箱入口，照旧走结果弹层。
          if (!S.isParent && typeof window.kOpenBoxAnimThenShow === 'function') {
            await window.kOpenBoxAnimThenShow(r);
          } else {
            showBoxResult(r);
          }
          await boot();
        } catch (e) { err(e); }
      });
    });
}

function showBoxResult(r) {
  const given = (r.given || []).map(g => {
    if (g.type === 'ticket') return '娱乐券 ×' + g.qty;
    if (g.type === 'stardust') return '星尘 +' + num(g.qty);
    if (g.type === 'card') return RAR[g.rarity] + '卡「' + g.name + '」' + (g.fragment ? '（超出上限，拆成 ' + g.fragment + ' 碎片）' : '');
    if (g.type === 'random') return '随机件：' + (g.label || g.name);
    if (g.type === 'diamond') return '钻石级「' + g.name + '」';
    return g.name || '';
  }).filter(Boolean);
  sheet('<h3>' + esc(r.name) + ' 开了</h3><div class="hr"></div>' +
    given.map(x => '<div class="kv"><span class="k">·</span><span class="v" style="text-align:right">' +
      esc(x) + '</span></div>').join('') +
    (r.note ? '<div class="notice" style="margin-top:12px">' + esc(r.note) + '</div>' : '') +
    (canReroll(r) ? '<div class="act-row">' +
      '<button class="btn btn--primary" id="rr">用一张重抽券再抽一次</button>' +
      '<button class="btn btn--ghost" id="ok">知道了</button></div>'
      : '<button class="btn wide" id="ok" style="margin-top:14px">知道了</button>'),
    box => {
      $('#ok', box).addEventListener('click', closeSheet);
      const rr = $('#rr', box);
      if (rr) rr.addEventListener('click', () => doReroll(r.box_id));
    });
}

/* 这一箱值不值得给「再抽一次」这个选项：得真有随机件，而且手上得有重抽券。
   没有就不给按钮 —— 给一个点了才说「你没有券」的按钮，等于骗了一下。

   v38：自选件在「还没挑」的时候是可以重抽的（重抽挪到挑之前），挑完了才是
   他自己定下来的，那一下不给换。所以判据从「是不是自选件」改成「挑没挑过」。 */
function canReroll(r) {
  const rnd = r && r.random;
  return !!(r && r.box_id && rnd && !rnd.rerolled && !rnd.picked);
}

async function doReroll(boxId) {
  let cards = [];
  try { cards = (await api('GET', '/api/holdings?member_id=' + S.me.id)).cards || []; } catch (e) { }
  const has = cards.some(c => c.code === 'reroll_card' && (c.qty || 0) >= 1);
  if (!has) { toast('手上没有重抽券了'); return; }
  try {
    const r = await api('POST', '/api/boxes/' + boxId + '/reroll', {});
    closeSheet();
    toast(r.changed ? '换成更好的一件' : '还是原来那件更好');
    await boot();
    const merged = Object.assign({ name: r.changed ? '重抽结果' : '没换' }, r);
    // 重抽换出来的正好是自选件：那几张还得他自己挑，交给孩子端那一屏收尾
    // —— 家长端这一屏不认识 need_pick，走它会把这件东西吞掉。
    if (!S.isParent && r.need_pick && typeof window.kOpenResult === 'function') {
      window.kOpenResult(merged);
    } else {
      showBoxResult(merged);
    }
  } catch (e) { err(e); }
}

/* 兑换记录的一行。四种状态各说各的下一步，别只给一个「处理中」。 */
function cashReqRow(r) {
  const s = r.status;
  let tail = '';
  if (s === 'pending') tail = '<button class="btn sm line" data-cashx="' + r.id + '">撤回</button>';
  else if (s === 'approved') tail = '<button class="btn sm" data-cashok="' + r.id +
    '" data-amt="' + num(r.cash) + '">收到了</button>';
  return '<div class="item"><div class="txt">' +
    '<div class="nm">' + num(r.stardust) + ' 星尘 → ' + num(r.est_cash) + ' 元' +
    (r.cash && r.cash !== r.est_cash ? '（实发 ' + num(r.cash) + ' 元）' : '') +
    ' <span class="tag ' + (s === 'approved' ? 'ok' : (s === 'rejected' ? 'warn' : '')) + '">' +
    esc(r.status_text) + '</span></div>' +
    (r.note ? '<div class="ds">用途：' + esc(r.note) + '</div>' : '') +
    (s === 'rejected' && r.reject_note ? '<div class="ds no-t">' + esc(r.reject_note) + '</div>' : '') +
    (s === 'approved' ? '<div class="ds ok-t">找爸爸妈妈拿 ' + num(r.cash) + ' 元，拿到点右边。</div>' : '') +
    '<div class="ds muted">' + esc(String(r.created_at || '').slice(0, 16)) + '</div>' +
    '</div>' + tail + '</div>';
}

function buyTicket(code, price) {
  sheet('<h3>买券</h3>' + qtyPicker(1) + '<button class="btn wide" id="go">确认</button>', box => {
    let qty = 1;
    $$('.chip', box).forEach(c => c.addEventListener('click', () => {
      qty = +c.dataset.q; $$('.chip', box).forEach(x => x.classList.remove('on')); c.classList.add('on');
      $('#go', box).textContent = '花 ' + (price * qty) + ' 星尘';
    }));
    $('#go', box).textContent = '花 ' + price + ' 星尘';
    $('#go', box).addEventListener('click', async () => {
      try {
        await api('POST', '/api/shop/buy', { member_id: S.me.id, code: code, qty: qty });
        closeSheet(); toast('买到了'); await boot();
      } catch (e) { err(e); }
    });
  });
}
function qtyPicker(n) {
  return '<div class="field"><label>要几张</label><div class="chips">' +
    [1, 2, 3].map(i => '<button type="button" class="chip ' + (i === n ? 'on' : '') + '" data-q="' + i + '">' +
      i + ' 张</button>').join('') + '</div></div>';
}

function buyCard(code, price) {
  sheet('<h3>买卡</h3><p class="muted">花 ' + price + ' 星尘。买来的卡不参与碎片合成，也不能退。</p>' +
    '<button class="btn wide" id="go">确认买</button>', box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          await api('POST', '/api/shop/buy', { member_id: S.me.id, code: code });
          closeSheet(); toast('买到了'); await boot();
        } catch (e) { err(e); }
      });
    });
}

/* 换零花钱的入口（v24）。以前这里是「填个星尘数，点一下就到账」，
   现在改成提申请 —— 中间的换算是这一屏最要紧的信息：
   孩子填的是星尘，「拿到多少钱」得当场算给他看，不能让他自己去乘 0.5。 */
async function cashSheet() {
  const cash = await api('GET', '/api/cash?member_id=' + S.me.id);
  const cap = Math.max(0, Math.floor(Math.min(Number(cash.left || 0), Number(cash.balance || 0))));
  if (cap <= 0) {
    return sheet('<h3>换零花钱</h3><div class="notice warn">现在换不了：' +
      (Number(cash.left || 0) <= 0
        ? '本月的零花钱额度已经用完了（' + num(cash.cap_cash) + ' 元 / 月）。'
        : '手上只有 ' + num(cash.balance) + ' 星尘，先攒一点。') +
      '</div><button class="btn wide" id="ok">知道了</button>',
      box => $('#ok', box).addEventListener('click', closeSheet));
  }
  const def = Math.min(10, cap);
  sheet('<h3>换零花钱</h3>' +
    '<p class="muted">提一条申请，爸爸妈妈点同意就发钱；拿到手你点一下「收到了」，' +
    '这一条才算完。1 星尘 = ' + cash.rate + ' 元。</p>' +
    '<div class="field"><label>换多少星尘</label>' +
    '<input id="amt" type="number" inputmode="numeric" value="' + def + '" min="1" step="1" max="' + cap + '">' +
    '<div class="ds muted" style="margin-top:5px">手上 ' + num(cash.balance) + ' 星尘　' +
    '本月额度还剩 ' + num(cash.left) + ' 星尘 / ' + num(cash.left_cash) + ' 元' +
    (Number(cash.hold || 0) > 0 ? '（已经在审的 ' + num(cash.hold) + ' 星尘也算在里面）' : '') +
    '</div></div>' +
    '<div class="notice info" id="calc">填一个数，这里告诉你扣多少星尘、换多少钱</div>' +
    '<div class="field"><label>这笔钱打算做什么（可选）</label>' +
    '<input id="note" placeholder="例如：买个新笔袋"></div>' +
    '<button class="btn wide" id="go">提出申请</button>', box => {
      const amt = $('#amt', box), calc = $('#calc', box);
      const refresh = () => {
        const n = +amt.value || 0;
        calc.textContent = n > 0
          ? '扣 ' + n + ' 星尘，换 ' + num(n * cash.rate) + ' 元'
          : '填一个数，这里告诉你扣多少星尘、换多少钱';
      };
      amt.addEventListener('input', refresh);
      refresh();
      $('#go', box).addEventListener('click', async () => {
        try {
          await api('POST', '/api/cash/request',
            { member_id: S.me.id, stardust: +amt.value, note: $('#note', box).value });
          closeSheet(); toast('提上去了，等爸爸妈妈看一眼'); await render();
        } catch (e) { err(e); }
      });
    });
}

function askOvertimeSheet(mid) {
  sheet('<h3>申请加时</h3>' +
    '<p class="muted">10 星尘换 30 分钟，每周最多 2 次。这条是给「今天还想多玩一会儿」的，' +
    '突破的是当日上限，不突破「今天已经该睡了」，也不突破「当天学习任务已完成」。</p>' +
    '<p class="muted">家长可以同意也可以拒绝，拒绝必须写理由，那句话你随时能翻到。' +
    '写不出理由，就说明不该拒。</p>' +
    '<div class="field"><label>今天想玩什么（家长看得到）</label>' +
    '<input id="otre" placeholder="例如：同学约了一局"></div>' +
    '<button class="btn" id="otok">发出去</button>', box => {
    box.querySelector('#otok').addEventListener('click', async () => {
      try {
        await api('POST', '/api/overtime',
          { member_id: mid, reason: box.querySelector('#otre').value });
        closeSheet(); toast('已经告诉爸爸妈妈了'); await boot();
      } catch (e) { err(e); }
    });
  });
}

function askHelpSheet(mid) {
  sheet('<h3>遇到困难</h3>' +
    '<p class="muted">主动说不会不是丢人的事，它是这套规则里最有用的一句话。' +
    '把「承认不会」从丢人的事变成有收益的事，抄作业的动机就掉一大半。</p>' +
    '<p class="muted">只写「哪一题、卡在哪一步」，不写「不会什么」。</p>' +
    '<div class="field"><label>卡在哪一步</label>' +
    '<input id="hpd" placeholder="例如：数学第 7 题，列方程那步不知道设哪个"></div>' +
    '<button class="btn" id="hpok">告诉爸爸妈妈</button>', box => {
    box.querySelector('#hpok').addEventListener('click', async () => {
      try {
        await api('POST', '/api/help',
          { member_id: mid, detail: box.querySelector('#hpd').value });
        closeSheet(); toast('已经说给爸爸妈妈了'); await boot();
      } catch (e) { err(e); }
    });
  });
}

function stealGameSheet(mid) {
  sheet('<h3>记一次偷玩游戏</h3>' +
    '<p class="muted">这不是「多玩了一会儿」，是绕过系统。处理方式是降级：设备改成' +
    '只能在公共区域用，时长仍按券走，3 天自动恢复。不没收、不扣券、不罚钱。</p>' +
    '<p class="muted">先问一句再记。不问原因直接处理，下次他会做得更隐蔽，' +
    '而隐蔽比偷玩本身麻烦得多。30 天内第二次会延到 7 天，然后一起调规则。</p>' +
    '<div class="field"><label>问出来的原因（是什么就写什么）</label>' +
    '<input id="sgr" placeholder="例如：券不够用 / 同学在约 / 申请太麻烦"></div>' +
    '<button class="btn" id="sgok">记下来</button>', box => {
    box.querySelector('#sgok').addEventListener('click', async () => {
      try {
        const r = await api('POST', '/api/events/steal-game',
          { member_id: mid, reason: box.querySelector('#sgr').value });
        closeSheet(); toast(r.msg); await render();
      } catch (e) { err(e); }
    });
  });
}

function homeworkSheet(mid) {
  sheet('<h3>作业复核</h3>' +
    '<p class="muted">抄作业是「回避能力验证」，掩盖的是真实缺口。发现时第一句不是' +
    '「你怎么抄作业」，是「哪一题卡住了」。</p>' +
    '<p class="muted">事后才发现时，撤掉当天那 1 分智识，其余 6 项不动，' +
    '已开出的宝箱、已发的券和星尘一律不追回。撤的是一个还没被验证的判断，不是发出去的东西。</p>' +
    '<div class="field"><label>哪一天</label>' +
    '<input id="hwd" type="date" value="' + shiftDay(todayStr(), -1) + '"></div>' +
    '<div class="field"><label>哪一科（可选）</label>' +
    '<input id="hws" placeholder="例如：数学"></div>' +
    '<div class="field"><label>卡在哪一步（留给孩子看）</label>' +
    '<input id="hwn" placeholder="例如：第三题的第二步"></div>' +
    '<button class="btn" id="hwok">撤掉那 1 分</button>', box => {
    box.querySelector('#hwok').addEventListener('click', async () => {
      try {
        const r = await api('POST', '/api/events/homework', {
          member_id: mid, day: box.querySelector('#hwd').value,
          subject: box.querySelector('#hws').value, note: box.querySelector('#hwn').value });
        closeSheet(); toast('撤掉了 ' + r.revoked + ' 分'); await render();
      } catch (e) { err(e); }
    });
  });
}

function useItemSheet(effect, holdingId) {
  sheet('<h3>用这张卡</h3><p class="muted">用了就收不回来。有没有做到，家里人看得见。</p>' +
    '<div class="field"><label>用在哪件事上（可选）</label><input id="note" placeholder="例如：今晚的作业"></div>' +
    '<button class="btn wide" id="go">确认使用</button>', box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          const r = await api('POST', '/api/items/use', { member_id: S.me.id,
            code: effectCode(effect), note: $('#note', box).value });
          closeSheet();
          // 以前这里只说「用掉了」。卡的效果分四种走向，不写清楚的话孩子
          // 不知道这张卡是当场生效还是在等大人，会以为是系统坏了。
          toast(r.message || '用掉了');
          await boot();
        } catch (e) { err(e); }
      });
    });
}
/* 把额度快照翻译成一句人话。孩子看到的不该是"操作失败"，
   而应该是"为什么现在不行、什么时候行"。 */
function gateReason(st) {
  if (!st) return '';
  if (st.cooldown_left > 0) return '这一轮结束了，还要等 ' + st.cooldown_left + ' 分钟（' + st.ready_at + ' 之后能开新一轮）';
  if (st.max_qty_now <= 0) return '到点了，' + st.curfew + ' 收工，今天先睡';
  if (st.round_open) {
    return '这一轮还能要 ' + st.max_qty_now + ' 张　还有 ' + st.window_left +
      ' 分钟可以接着续，过了这一轮就结束';
  }
  return '现在能用，最多 ' + st.max_qty_now + ' 张　最后一轮要在 ' + st.curfew + ' 前结束';
}

function tkStatusText(s) {
  return { pending: '等爸爸妈妈点一下', approved: '可以用啦', self: '已用掉',
    rejected: '没同意', expired: '等太久，作废了' }[s] || s;
}

/* 一条申请「现在到哪一步了」的那句话。孩子提交之后最想知道的就这三件：
   批了没、为什么没批、还能玩多久。以前这行只写「→ 21:30」，看不出在不在玩。 */
function tkStatusNote(x) {
  if (x.status === 'pending') {
    const el = miniLeft(x.expire_at);
    return '还在等爸爸妈妈点一下' + (el ? '，' + el : '');
  }
  if (x.status === 'rejected') return '';            // 理由单独一行，更醒目
  if (x.status === 'expired') return '等太久了，这条自己作废了，想玩可以重新提';
  if (x.running) return '正在玩，' + tkLeftText(tkLeftMs(x.end_at)) + '结束';
  if (x.start_at) {
    return '玩过了：' + String(x.start_at).slice(11, 16) + ' → ' +
      String(x.end_at || '').slice(11, 16);
  }
  return '';
}

/* ------------------------------------------------------------------ 倒计时 */
/* 秒级倒计时只改那几个数字，不重画整页 —— 重画会把滚动位置抹掉，
   正看着进度条的孩子会莫名其妙被弹回页首。到点时才整页刷一次，
   让「正在玩」翻成「玩完了」。 */
function tkParse(ts) {
  if (!ts) return 0;
  return new Date(String(ts).replace(' ', 'T')).getTime() || 0;
}
function tkLeftMs(ts) { return tkParse(ts) - Date.now(); }

/* 只剩几分钟时最直观的样子：24:18。给「正在玩」那块大倒计时用。
   别的倒计时仍然是 tkLeftText 那句人话 —— 「还剩 2 天 3 小时」比 51:00 好懂。 */
function tkClock(ms) {
  if (!ms || ms <= 0) return '00:00';
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return (m < 10 ? '0' : '') + m + ':' + String(s % 60).padStart(2, '0');
}

function tkLeftText(ms) {
  if (!ms || ms <= 0) return '时间到了';
  const s = Math.round(ms / 1000);
  if (s < 60) return '还剩 ' + s + ' 秒';
  const m = Math.floor(s / 60);
  if (m < 60) return '还剩 ' + m + ' 分 ' + (s % 60) + ' 秒';
  const h = Math.floor(m / 60);
  if (h < 24) return '还剩 ' + h + ' 小时 ' + (m % 60) + ' 分';
  // 申请的作废时限是可配的，配大了就得说「天」，不能显示「还剩 720 小时」
  return '还剩 ' + Math.floor(h / 24) + ' 天 ' + (h % 24) + ' 小时';
}

let tkTimer = null;
function stopTkTick() { if (tkTimer) { clearInterval(tkTimer); tkTimer = null; } }

function tkRunTick() {
  let over = false;
  const paint = (el, at) => {
    const left = at - Date.now();
    const txt = $('[data-tkleft]', el);
    // 格式跟着元素走：孩子端首页那块要 mm:ss，其余地方仍是「还剩 X 分 Y 秒」。
    // 不认 data-tkfmt 的话，这里每秒会把 mm:ss 覆盖回人话。
    if (txt) txt.textContent = el.dataset.tkfmt === 'mmss' ? tkClock(left) : tkLeftText(left);
    const bar = $('[data-tkbar]', el);
    if (bar) {
      const total = (+el.dataset.tktotal || 0) * 60000;
      bar.style.width = total > 0
        ? Math.max(0, Math.min(100, left / total * 100)).toFixed(1) + '%' : '0%';
    }
    if (left <= 0) over = true;
  };
  $$('[data-tkend]').forEach(el => paint(el, tkParse(el.dataset.tkend)));
  $$('[data-tkexp]').forEach(el => paint(el, tkParse(el.dataset.tkexp)));
  if (over) { stopTkTick(); render(); }
}

function startTkTick() {
  stopTkTick();
  if (!$('[data-tkend]') && !$('[data-tkexp]')) return;
  tkRunTick();
  tkTimer = setInterval(tkRunTick, 1000);
}

/* 孩子提交完就盯着屏幕等 —— 家长什么时候点同意，他这块得自己翻过去，
   否则「不知道审核了没」会一直挂在那儿。每 15 秒问一次状态，
   只有真的变了才重画，不然会把人从正在看的地方弹走。 */
let tkPollTimer = null;
let tkSig = null;
let tkSigView = '';

async function tkPollOnce() {
  if (!S.me || S.isParent) return;
  try {
    const r = await api('GET', '/api/tickets/mine?member_id=' + S.me.id);
    const sig = JSON.stringify({
      i: (r.items || []).map(x => [x.id, x.status, x.start_at, x.end_at]),
      p: (r.playing || []).map(x => [x.id, x.end_at]),
    });
    if (tkSig === null) { tkSig = sig; return; }
    if (sig !== tkSig) { tkSig = sig; render(); }
  } catch (e) { /* 网络抖一下不管，下一轮再说 */ }
}

function startTicketPoll() {
  stopTicketPoll();
  if (S.isParent || !S.me) return;
  // 只有可能看到券状态的那几页值得轮询。别的页面白问一轮是浪费，也容易把人弹走。
  // 孩子端的首页（home）和券包页（coupon）也要：券卡就摆在那两屏第一眼，
  // 等审核从「等同意」变成「正在玩」，得自己翻过来。
  if (['mine', 'shop', 'week', 'home', 'coupon'].indexOf(S.view) < 0) return;
  if (tkSigView !== S.view) { tkSigView = S.view; tkSig = null; }
  tkPollTimer = setInterval(tkPollOnce, 15000);
}

function stopTicketPoll() {
  if (tkPollTimer) { clearInterval(tkPollTimer); tkPollTimer = null; }
}

/* 孩子首页的券状态卡（v29）。
   以前它躺在「我的 → 我的券」里：提交了不知道审没审、批了不知道还剩多久，
   都得自己翻进去看。券是**当下正在发生**的事，它该跟动态一起出现在第一屏，
   而不是跟库存一起待在角落里。等审核的那条给作废倒计时，批了的那条给秒级进度条。 */
function ticketBannerHTML(tk) {
  const items = (tk && tk.items) || [];
  const run = items.filter(x => x.running);
  const pend = items.filter(x => x.status === 'pending');
  const rej = items.filter(x => x.status === 'rejected');
  let h = '';
  if (run.length) {
    h += '<div class="sec"><div class="sec-h"><h2>正在玩</h2>' +
      '<span class="sub">到点自己结束</span></div>' +
      run.map(x => '<div class="card pad tk-run" data-tkend="' + esc(x.end_at) +
        '" data-tktotal="' + num(x.total_minutes || 0) + '">' +
        '<div class="row between"><span class="tag ok">' + esc(x.item) + ' ×' + num(x.qty) +
        '</span><b class="tk-big" data-tkleft>' +
        esc(tkLeftText(tkLeftMs(x.end_at))) + '</b></div>' +
        '<div class="bar gold" style="margin-top:9px"><i data-tkbar style="width:0%"></i></div>' +
        '<div class="muted" style="margin-top:7px">' +
        esc(String(x.start_at).slice(11, 16)) + ' → ' + esc(String(x.end_at).slice(11, 16)) +
        (x.by ? '　' + esc(x.by) + '同意的' : '') +
        (x.note ? '　' + esc(x.note) : '') + '</div></div>').join('') + '</div>';
  }
  if (pend.length) {
    h += '<div class="sec"><div class="card pad tk-pend">' +
      pend.map(x => '<div class="row between"><span><b>' + esc(x.item) + ' ×' + num(x.qty) +
        '</b>　等爸爸妈妈同意</span><span class="muted">' + esc(miniLeft(x.expire_at)) +
        '</span></div>' + (x.note ? '<div class="ds muted">' + esc(x.note) + '</div>' : '')
      ).join('') + '</div></div>';
  }
  if (rej.length) {
    h += '<div class="sec"><div class="card pad tk-judge">' + rej.map(x =>
      '<div><b>' + esc(x.item) + '</b> 没同意</div>' +
      (x.reject_note ? '<div class="ds tk-no">' + esc(x.reject_note) + '</div>' : '')
    ).join('') + '</div></div>';
  }
  return h;
}

/* 「正在玩」。家长要在第一屏就能看到：孩子说「我就玩一会儿」，
   到底是不是真的在用、还剩几分钟到点。带秒级倒计时，不用自己按刷新。

   全站只有这一块和「周期进度」走羊皮纸重点卡 —— 「此刻正在发生的事」
   得在一屏奶白卡里被一眼看见。刷成普通卡就淹了。 */
function playingHTML(items) {
  if (!items || !items.length) return '';
  return items.map(x => '<div class="card--parch" data-tkend="' + esc(x.end_at) +
    '" data-tktotal="' + num(x.total_minutes || 0) + '" data-tkfmt="mmss">' +
    '<div class="sec-head">' +
    '<span class="card-title">' + esc(x.who) + ' · ' + esc(x.item) + '</span>' +
    '<span class="pill pill--on-parch">' + pic('i-hourglass', 14) + ' ' + num(x.qty) + ' 张</span>' +
    '</div>' +
    '<div class="hero-num" style="margin-top:8px">' +
    '<span class="num num--md" data-tkleft>' + esc(tkClock(tkLeftMs(x.end_at))) + '</span></div>' +
    '<div class="bar bar--orange" style="margin-top:8px"><i data-tkbar style="width:62%"></i></div>' +
    '<div style="display:flex;justify-content:space-between;margin-top:6px">' +
    '<span class="caption--warm">' + esc(String(x.start_at).slice(11, 16)) + ' 开始</span>' +
    '<span class="caption--warm">' + esc(String(x.end_at).slice(11, 16)) + ' 自动结束</span>' +
    '</div>' +
    '<div class="parch-line">' + pic('i-check-circle', 14) +
    '<span class="caption--warm">' +
    (x.by ? esc(x.by) + '同意的 · ' : '') + '到点自己结束，不用手动关' +
    (x.note ? '　' + esc(x.note) : '') + '</span></div>' +
    '</div>').join('');
}

/* 申请离作废还剩多久。过期时间来自后端本地时间字符串，
   空格换成 T 再解析，否则 Safari 会当非法日期。
   有效时长是可配的（ticket.request_ttl_minutes），配大了就得说「天」，
   不然会看到「还剩 43398 分钟」这种东西。 */
function miniLeft(expireAt) {
  if (!expireAt) return '';
  const t = new Date(String(expireAt).replace(' ', 'T')).getTime();
  if (!t) return '';
  const m = Math.round((t - Date.now()) / 60000);
  if (m <= 0) return '已经超时了';
  if (m >= 2880) return '还剩 ' + Math.round(m / 1440) + ' 天';
  if (m >= 120) return '还剩 ' + Math.floor(m / 60) + ' 小时 ' + (m % 60) + ' 分钟';
  return '还剩 ' + m + ' 分钟';
}

function tkTagClass(s) {
  return s === 'approved' || s === 'self' ? 'gold' : (s === 'rejected' ? '' : '');
}

function ticketSheet(code, name, balance, state) {
  const isFun = code === 'ticket_fun';
  const cap = isFun ? Math.max(1, Math.min(balance, state.max_qty_now)) : Math.min(balance, 3);
  const opts = [];
  for (let i = 1; i <= cap; i++) opts.push(i);
  sheet('<h3>用「' + esc(name) + '」</h3>' +
    '<p class="muted">' + (isFun
      ? '一张 ' + num(state.minutes) + ' 分钟。一轮里可以一张一张接着续，' +
        '用满这一轮、或者隔 ' + num(state.renew_within_minutes || 10) +
        ' 分钟没续，才要休息。提交后要爸爸妈妈点一下才算数。'
      : '提交后要爸爸妈妈点一下才算数。') + '</p>' +
    '<div class="field"><label>要几张</label><div class="chips">' +
    opts.map(i => '<button type="button" class="chip' + (i === 1 ? ' on' : '') + '" data-q="' + i + '">' +
      i + ' 张</button>').join('') + '</div></div>' +
    (isFun ? '<div class="muted">' + esc(gateReason(state)) + '</div>' : '') +
    '<div class="field" style="margin-top:10px"><label>用在哪（可选，爸爸妈妈看得到）</label>' +
    '<input id="tnote" placeholder="例如：看一集动画"></div>' +
    '<button class="btn wide" id="go">提交申请</button>', box => {
      let qty = 1;
      $$('.chip', box).forEach(c => c.addEventListener('click', () => {
        $$('.chip', box).forEach(x => x.classList.remove('on'));
        c.classList.add('on');
        qty = +c.dataset.q;
      }));
      $('#go', box).addEventListener('click', async () => {
        try {
          const r = await api('POST', '/api/tickets/request',
            { member_id: S.me.id, code: code, qty: qty, note: $('#tnote', box).value });
          closeSheet();
          toast(r.mode === 'pending' ? '已经告诉爸爸妈妈了' : '用掉了');
          await boot();
        } catch (e) { err(e); }
      });
    });
}

// 卡片用 effect_key 传过来，这里映射回 code
function effectCode(key) {
  const map = {
    time_together: 'company_card', meal_choice: 'meal_pick', priority: 'priority_card',
    swap_chore: 'chore_swap', late_bed: 'late_sleep', late_rise: 'sleep_in',
    skip_errand: 'no_errand', skip_cooldown: 'skip_study', double_reward: 'double_card',
    reroll_random: 'reroll_card', extra_minutes: 'extra_time', offset_penalty: 'offset_card',
    no_nagging: 'no_nag', skip_chore_day: 'no_chore_day', friend_sleepover: 'friend_stay',
    choose_consequence: 'pick_consequence', double_stardust_week: 'double_week',
    call_meeting: 'family_meeting', double_allowance: 'allowance_x2',
    wish_accelerate: 'wish_boost', cosmetic_title: 'title_badge',
    cosmetic_pet: 'guardian', cosmetic_skin: 'skin',
  };
  return map[key] || key;
}

/* ================================================================== 家长端 · 日志（v28） */
/* 孩子自己按的每一个按钮（买券、买卡、开箱、兑零花钱、用券……）都记在账本里 —
   余额本来就是流水求和算出来的。这一页把账本翻成人话。

   家长问得最多的一句是「他那张券哪来的」：券从哪来这件事，账本一直知道，
   只是以前只有一行「商店·买券」，没人看得懂。 */
/* 三维筛选。孩子 / 类型 / 日期各一行，可以叠加。
   「自定义」是唯一会弹日期选择器的入口，所以它是虚线描边 ——
   一排筹码里长一个样子，点之前就知道它会开东西。 */
/* since / until 是「自定义」那一档挑出来的起止两天，跟着 LOG_FILTER 走，
   切回别的档位不用清 —— 再点「自定义」还是上次那段。 */
const LOG_FILTER = {
  member_id: '', group: '', date: 'month', limit: 40, mine: false,
  since: '', until: '',
};
const LOG_DATES = [
  ['today', '今天'], ['yesterday', '昨天'], ['last7', '近七天'],
  ['month', '本月'], ['all', '全部'], ['custom', '自定义'],
];
/* 日期档位换算成接口的 days（天数往回数）。昨天要多取一天再筛，
   不然「昨天」会把今天也算进去。
   自定义那档不走这条路 —— 它按日历切（since/until），换算成天数会多带半天。 */
function logDays() {
  const t = LOG_FILTER;
  if (t.date === 'today') return 1;
  if (t.date === 'yesterday') return 2;
  if (t.date === 'last7') return 7;
  if (t.date === 'month') return 30;
  return null;   // 全部时间 / 自定义
}
/* 筹码上写区间，不写「自定义」四个字 —— 挑完再看这一排，
   一眼就知道现在看的是哪一段，不用再点开弹层确认。 */
function logRangeText() {
  const t = LOG_FILTER;
  if (!t.since || !t.until) return '自定义';
  const a = t.since.slice(5), b = t.until.slice(5);
  return t.since.slice(0, 4) === t.until.slice(0, 4) ? a + ' ~ ' + b
    : t.since.slice(2) + ' ~ ' + t.until.slice(2);
}
/* 分组在前端的观感：颜色与图标都按「来源」走 —— 谁动的手，看圆点颜色就知道。
   分组文字用后端给的那一份（组名只有一处定义，前端不另起一套）。 */
const LOG_STYLE = {
  self:   { dot: '#FF8A3D', ico: 'i-log-task' },
  given:  { dot: '#FFC93C', ico: 'i-log-chest' },
  judge:  { dot: '#8B6BFF', ico: 'i-log-assign' },
  system: { dot: '#A08E7A', ico: 'i-log-system' },
};
function logTimeText(ts) {
  const s = String(ts || '');
  const day = s.slice(0, 10), hm = s.slice(11, 16);
  const t = todayStr();
  if (day === t) return '今天 ' + hm;
  if (day === shiftDay(t, -1)) return '昨天 ' + hm;
  return s.slice(5, 16);
}
function logRowHTML(x, showWho) {
  const neg = /^[−-]/.test(x.impact || '');
  const st = LOG_STYLE[x.group] || LOG_STYLE.system;
  return '<div class="log-item' + (neg ? ' is-neg' : '') + '">' +
    pic(st.ico, 20) +
    '<div class="body"><span class="txt">' +
    (showWho && x.who ? '<b>' + esc(x.who) + '</b>　' : '') + esc(x.text) + '</span>' +
    '<span class="meta">' + esc(logTimeText(x.ts)) +
    // v29：写具体那个人。以前这里写「爸爸妈妈经手」，两个大人各有一套口径时，
    // 这句话等于没说 —— 孩子问「谁扣的」，日志回答「大人扣的」。
    (x.by ? '　' + esc(x.by) + (x.by === '系统' ? '' : (x.by_parent ? ' 经手' : ' 自己')) : '') +
    (x.impact ? '　' + esc(x.impact) : '') + '</span></div>' +
    '</div>';
}

async function renderAdminLogs(v) {
  const f = LOG_FILTER;
  const days = logDays();
  let q = '/api/activity?limit=' + (f.mine ? 200 : f.limit);
  if (f.member_id) q += '&member_id=' + f.member_id;
  if (f.group) q += '&group=' + f.group;
  if (f.date === 'custom' && f.since && f.until) {
    // 按日历切：接口收的是起止两天，两头都算在内
    q += '&since=' + f.since + '&until=' + f.until;
  } else if (days) q += '&days=' + days;
  const d = await api('GET', q);
  const kids = KIDS();
  const multi = !f.member_id;

  // 「我的记录」＝家长自己的操作审计：我打过的分 / 我审过的 / 我发过的。
  // 和这一页的默认口径（全家混排）同源不同过滤 —— 接口没有「按经手人」这个
  // 参数，所以在取回来的这一页里筛；筛之前已经把 200 条拉满了。
  let items = d.items;
  if (f.mine) items = items.filter(x => x.by === S.me.name);
  if (f.date === 'yesterday') {
    const y = shiftDay(todayStr(), -1);
    items = items.filter(x => String(x.ts || '').slice(0, 10) === y);
  }
  const total = f.mine ? items.length : d.total;

  const back = f.mine ? 'me' : 'home';
  let h = '<div class="page-head" style="align-items:center">' +
    '<div class="head-line">' +
    '<button class="back-btn" type="button" data-go="' + back + '">' + pic('i-back', 18) + '</button>' +
    '<div class="left"><span class="heading-page" style="font-size:20px">' +
    (f.mine ? '我的记录' : '最近发生') + '</span>' +
    '<span class="caption--warm">共 ' + total + ' 条 · ' +
    (f.mine ? '只筛我自己经手的' : '两个孩子都在') + '</span></div>' +
    '</div></div>';

  // 三维筛选
  h += '<div class="stack--sm" style="display:flex;flex-direction:column;gap:6px">';
  h += '<div class="chip-row"><span class="dim-label">孩子</span><div class="chips">' +
    '<button class="chip' + (f.member_id ? '' : ' on') + '" data-lf="member_id" data-lv="">全部</button>' +
    kids.map(k => '<button class="chip' + (String(f.member_id) === String(k.id) ? ' on' : '') +
      '" data-lf="member_id" data-lv="' + k.id + '">' + esc(k.name) + '</button>').join('') +
    '</div></div>';
  h += '<div class="chip-row"><span class="dim-label">类型</span><div class="chips">' +
    '<button class="chip' + (f.group ? '' : ' on') + '" data-lf="group" data-lv="">全部</button>' +
    (d.groups || []).map(g => '<button class="chip' +
      (f.group === g.key ? ' on' : '') + '" data-lf="group" data-lv="' + g.key + '">' +
      esc(g.text) + '</button>').join('') +
    '</div></div>';
  h += '<div class="chip-row"><span class="dim-label">日期</span><div class="chips">' +
    LOG_DATES.map(x => '<button class="chip' + (f.date === x[0] ? ' on' : '') +
      (x[0] === 'custom' && f.date !== 'custom' ? ' chip--dashed' : '') +
      '" data-lf="date" data-lv="' + x[0] + '">' +
      (x[0] === 'custom' ? esc(logRangeText()) : x[1]) + '</button>').join('') +
    '</div></div>';
  h += '</div>';

  if (!items.length) {
    h += '<div class="card"><div class="empty">' +
      (f.mine ? '这段时间里没有你自己经手的记录' : '这段时间没有记录') + '</div></div>';
  } else {
    // 按来源分组：一屏里几十条混在一起，家长想回答的其实是「这是他做的，
    // 还是别人给的」——先按这个分堆，再往下看具体某一条。
    const order = (d.groups || []).map(g => g.key);
    const buckets = {};
    items.forEach(x => { (buckets[x.group] = buckets[x.group] || []).push(x); });
    order.forEach(gk => {
      if (!buckets[gk]) return;
      const st = LOG_STYLE[gk] || LOG_STYLE.system;
      h += '<div class="log-group"><div class="log-head">' +
        '<span class="dot" style="background:' + st.dot + '"></span>' +
        esc((d.groups.find(g => g.key === gk) || {}).text || '') + '</div>' +
        buckets[gk].map(x => logRowHTML(x, multi)).join('') + '</div>';
    });
    if (!f.mine && items.length < d.total) {
      h += '<div class="card" style="padding:10px"><button class="btn wide btn--ghost" id="lmore">' +
        '看更早的（还有 ' + (d.total - items.length) + ' 条）</button></div>';
    }
  }
  h += '<p class="footnote footnote--left">这一页是账本的原话：孩子自己买券、买卡、开箱、' +
    '换零花钱，还有升级奖励、宝箱、任务奖励、校准扣减，每一笔都在这儿。' +
    '东西少了多了，先翻这里再问孩子。</p>';

  v.innerHTML = h;
  $$('#view button[data-go]').forEach(b => b.addEventListener('click', () => pGo(b.dataset.go)));
  $$('#view .chip[data-lf]').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.lf, val = b.dataset.lv;
    if (k === 'date' && val === 'custom') return askLogRange();
    LOG_FILTER[k] = val;
    LOG_FILTER.limit = 40;              // 换了筛选条件，翻页从头开始
    render();
  }));
  const more = $('#lmore');
  if (more) more.addEventListener('click', () => {
    LOG_FILTER.limit += 40;
    render();
  });
}

/* 自定义日期的唯一入口。接口现在认起止两天（since / until），所以这里就问两个：
   只给一个起始日、后端却按「往回数几天」筛，家长挑的区间和看到的账对不上，
   那是在骗人。快捷那三颗只是替家长把两栏填好，不是另一套筛法。 */
function askLogRange() {
  const f = LOG_FILTER;
  sheet('<h3>看哪一段</h3>' +
    '<p class="muted">选开始和结束，日志只翻这一段，两头都算在内。</p>' +
    '<div class="field"><label>开始</label><input id="ls" type="date" value="' +
    (f.since || shiftDay(todayStr(), -13)) + '"></div>' +
    '<div class="field"><label>结束</label><input id="le" type="date" value="' +
    (f.until || todayStr()) + '"></div>' +
    '<div class="chip-row"><span class="dim-label">快捷</span><div class="chips">' +
    '<button type="button" class="chip" data-rg="month">本月</button>' +
    '<button type="button" class="chip" data-rg="lastmonth">上月</button>' +
    '<button type="button" class="chip" data-rg="last30">最近 30 天</button>' +
    '</div></div>' +
    '<button class="btn wide btn--primary" id="go">看这一段</button>', box => {
      const qs = $('#ls', box), qe = $('#le', box);
      $$('[data-rg]', box).forEach(b => b.addEventListener('click', () => {
        const t = todayStr(), p = t.split('-').map(Number);
        if (b.dataset.rg === 'month') {
          qs.value = p[0] + '-' + String(p[1]).padStart(2, '0') + '-01'; qe.value = t;
        } else if (b.dataset.rg === 'lastmonth') {
          const q = new Date(p[0], p[1] - 2, 1);
          const ym = q.getFullYear() + '-' + String(q.getMonth() + 1).padStart(2, '0');
          const lastDay = new Date(p[0], p[1] - 1, 0).getDate();
          qs.value = ym + '-01';
          qe.value = ym + '-' + String(lastDay).padStart(2, '0');
        } else { qs.value = shiftDay(t, -29); qe.value = t; }
      }));
      $('#go', box).addEventListener('click', () => {
        const a = qs.value, b = qe.value;
        if (!a || !b) return err({ message: '开始和结束都要选' });
        if (a > b) return err({ message: '开始的日子要在结束之前' });
        f.date = 'custom'; f.since = a; f.until = b;
        closeSheet(); render();
      });
    });
}

/* ================================================================== 家长端 · 公共小件 */

/* 问候语：按钟点换，不按身份。孩子看见的也是同一句，只是称呼不同。 */
function pHello() {
  const h = new Date().getHours();
  return (h < 11 ? '早上好，' : (h < 18 ? '下午好，' : '晚上好，')) +
    ((S.me && S.me.name) || '');
}
function pDayLine() {
  const t = todayStr(), p = t.split('-');
  return (+p[1]) + '月' + (+p[2]) + '日 周' + wd(t);
}
/* 一屏的页头。家长端每一屏都是这个壳：左标题 + 左副标，右边放一个东西
   （铃铛 / 计数胶囊 / 孩子切换 + 今日分）。 */
function pHead(o) {
  const right = o.right || '';
  return '<div class="page-head"' + (o.center ? ' style="align-items:center"' : '') + '>' +
    '<div class="' + (o.back ? '' : 'left') + '"' +
    (o.back ? ' style="display:flex;align-items:center;gap:10px;min-width:0"' : '') + '>' +
    (o.back ? '<button class="back-btn" type="button" data-back="' + o.back + '">' +
      pic('i-back', 18) + '</button>' : '') +
    '<div class="left"><span class="heading-page">' + esc(o.title) + '</span>' +
    (o.sub ? '<span class="caption--warm">' + esc(o.sub) + '</span>' : '') +
    '</div></div>' + (right ? '<div class="right">' + right + '</div>' : '') + '</div>';
}

/* 家长端的头像。交付包给了三枚：家长一枚、两个孩子各一枚（只换色，不重画 ——
   小满橙发、小朵粉发，一排扫下来就分得清谁是谁）。
   谁都没在设置里挑过图的时候用这三枚；挑过的人继续用自己挑的那张，
   家长自己换的头像不该被一套皮盖掉。 */
function pAvatar(m, size, kidIdx) {
  const px = size || 44;
  const v = String((m && m.avatar) || '');
  const isParent = !!(m && m.role !== 'child');
  if (AVATAR_TOKENS[v]) {
    return '<span class="avatar' + (px > 50 ? ' avatar--lg' : '') +
      '" style="width:' + px + 'px;height:' + px + 'px">' + avatarHTML(m, px) + '</span>';
  }
  const name = isParent ? 'avatar-parent' : (kidIdx ? 'avatar-child-b' : 'avatar-child-a');
  const tone = isParent ? ' avatar--parent' : (kidIdx ? ' avatar--b' : ' avatar--a');
  return '<span class="avatar' + tone + (px > 50 ? ' avatar--lg' : '') +
    '" style="width:' + px + 'px;height:' + px + 'px">' +
    '<svg width="100%" height="100%" viewBox="' + ((typeof PARENT_VB !== 'undefined' &&
      PARENT_VB[name]) || '0 0 46 46') +
    '" aria-hidden="true"><use href="#' + name + '"/></svg></span>';
}

/* 距今天几天。心愿挂起几天、「上次提醒是哪天」都用它。 */
function holdDays(ts) {
  const s = String(ts || '').slice(0, 10);
  if (!s) return 0;
  const ms = new Date(todayStr().replace(/-/g, '/') + ' 00:00:00').getTime() -
    new Date(s.replace(/-/g, '/') + ' 00:00:00').getTime();
  return Math.max(0, Math.round(ms / 86400000));
}

/* 心愿标题是孩子自己写下的原话，他很可能自己就写了「想要…」。
   外面再套一层「想要」就成了「女儿想要想要一套彩铅」——像是系统复读了。
   只在标题自带这个开头时才剥掉它，别的一律原样留着。 */
function wishTitleOnly(t) {
  const s = String(t || '').replace(/^\s*(想要|想买|想)\s*[：:]?\s*/, '');
  return s || String(t || '');     // 别把「想要」两个字单独写的心愿剥成空
}

/* ================================================================== 家长端 · 待办（唯一来源） */
/* 待办只有一个来源。首页的铃铛角标、首页那张「待审核」卡、审核页顶上的计数胶囊、
   审核页本身那串卡，四处都读它。上一版就是首页三处计数停在旧数字上，出现
   「首页 3 件 / 审核 5 件」，家长照着 3 去数，怎么也数不出第 4、第 5 张卡。

   一条待办回答三件事：谁的事、走到哪一步、下一步该谁按。
   第三句不写「是否同意」这种废话 —— 家长得先看见「现在批了会发生什么」，
   而不是点完才发现闸门早关了。 */
async function pTodoData() {
  const dash = await api('GET', '/api/dashboard');
  const r = await Promise.all([
    pg('/api/tasks?status=submitted', { items: [] }),
    pg('/api/overtime', { items: [] }),
    pg('/api/help', { items: [] }),
    pg('/api/tickets/pending', { items: [] }),
    pg('/api/cards/redeems', { items: [] }),
    pg('/api/wishes/pending', { items: [] }),
    pg('/api/cash/requests', { items: [] }),
    pg('/api/wishes/submissions', { items: [] }),
    pg('/api/calibration?member_id=' + kidId(), { items: [] }),
  ]);
  const tasks = r[0], ot = r[1], hlp = r[2], tk = r[3], rdm = r[4];
  const pendW = r[5], cash = r[6], subs = r[7], calib = r[8];
  const items = [];

  // 券核销：时效最强（申请有 TTL，过期自动作废），排最上面
  tk.items.forEach(x => {
    items.push({
      key: 'tk', ico: 'i-coupon', tone: 'var(--orange)', id: x.id,
      title: x.who + ' 想用 ' + num(x.qty) + ' 张' + x.item,
      l1: (x.minutes ? num(x.minutes) + ' 分钟 · ' : '') +
        String(x.ts || '').slice(11, 16) + ' 提交 · ' + miniLeft(x.expire_at),
      l2: x.can_now ? '券还在他手上，你点头才真扣'
        : '现在过不了闸门了：' + x.block_reason + '（点同意也会自动拒掉）',
      btn: { t: 'tk-ok', id: x.id, label: '同意' },
      alt: { t: 'tk-no', id: x.id, label: '拒绝' },
    });
  });
  // 修复任务：校准挂出来的活。他交上来了，你点头才算和解
  tasks.items.filter(t => t.kind === 'repair').forEach(t => {
    items.push({
      key: 'fix', ico: 'i-fix', tone: 'var(--warn)', id: t.id,
      title: '修复任务 · ' + (t.assignee || ''),
      l1: t.title + (t.std ? ' · ' + t.std : ''),
      l2: '他交上来了，你点头才算和解',
      btn: { t: 'task-ok', id: t.id, label: '确认' },
      alt: { t: 'task-no', id: t.id, label: '退回' },
    });
  });
  // 孩子说「我做到了」。他交的是哪一条，原话就摆在这儿 ——
  // 家长看到「他说他做到了」却不知道指的是哪一条，就只能去问，
  // 问到最后这句话就变成了「你到底做没做」。
  subs.items.forEach(x => {
    items.push({
      key: 'claim', ico: 'i-star', tone: 'var(--orange)', id: x.id,
      title: x.who + '说「' + (x.cond_text || x.cond_key) + '」做到了',
      l1: '心愿《' + x.title + '》· ' + String(x.created_at || '').slice(5, 16) + ' 提交',
      l2: (x.note ? '他说：' + x.note + ' · ' : '') + '要驳回就写清理由，他看得见',
      btn: { t: 'claim-look', id: x.id, label: '看看' },
    });
  });
  // 奖励任务：48 小时没处理，系统自己确认发奖
  tasks.items.filter(t => t.kind !== 'repair').forEach(t => {
    items.push({
      key: 'task', ico: 'i-task-flag', tone: 'var(--orange)', id: t.id,
      title: (t.assignee || '') + '交了「' + t.title + '」',
      l1: '奖励 ' + (t.reward_text || '') +
        (t.submitted_at ? ' · ' + String(t.submitted_at).slice(5, 16) + ' 交' : ''),
      l2: '48 小时没处理，系统自己确认发奖',
      btn: { t: 'task-ok', id: t.id, label: '发奖' },
      alt: { t: 'task-no', id: t.id, label: '退回' },
    });
  });
  // 挂起的心愿：条件没定，它就一直不算进度。别让它挂着
  pendW.items.forEach(x => {
    items.push({
      key: 'wish', ico: 'i-wish', tone: 'var(--orange)', id: x.id,
      title: (x.who || '') + '想要' + wishTitleOnly(x.title),
      l1: '还没定条件 · 挂起 ' + holdDays(x.created_at) + ' 天',
      l2: '条件定下就占一个进行中名额',
      btn: { t: 'wcfg', id: x.id, label: '定条件' },
    });
  });
  // 加时申请
  ot.items.filter(x => x.status === 'pending').forEach(x => {
    items.push({
      key: 'ot', ico: 'i-hourglass', tone: 'var(--orange)', id: x.id,
      title: (x.name || '') + ' 申请加时 ' + num(x.minutes) + ' 分钟',
      l1: (x.reason || '没写理由') + ' · 花 ' + num(x.cost) + ' 星尘',
      l2: '加时是花自己的星尘买时长，批了立刻算数',
      btn: { t: 'ot-ok', id: x.id, label: '同意' },
      alt: { t: 'ot-no', id: x.id, label: '拒绝' },
    });
  });
  // 零花钱兑换：同意就等于发放，当场扣星尘、记流水
  cash.items.filter(x => x.status === 'pending').forEach(x => {
    items.push({
      key: 'cash', ico: 'i-shop', tone: 'var(--orange)', id: x.id,
      title: x.name + ' 想换 ' + num(x.est_cash) + ' 元',
      l1: '扣 ' + num(x.stardust) + ' 星尘' + (x.note ? ' · 用途：' + x.note : ''),
      l2: '同意就等于发放，掏钱的时候顺手把现金给他',
      btn: { t: 'cash-ok', id: x.id, label: '同意' },
      alt: { t: 'cash-no', id: x.id, label: '不同意' },
    });
  });
  // 求助
  hlp.items.filter(x => !x.verified_at).forEach(x => {
    items.push({
      key: 'help', ico: 'i-check-circle', tone: 'var(--purple)', id: x.id,
      title: (x.name || '') + ' 说卡住了',
      l1: x.detail,
      l2: '核实了发 1 星尘 —— 说「我卡住了」本身就值得记一笔',
      btn: { t: 'help-ok', id: x.id, label: '核实发星尘' },
    });
  });
  // 待兑现的卡：这些卡从库存里已经扣掉了，效果却要靠大人去办。
  // 没有这一栏，用掉的卡就等于凭空消失，孩子下次就不愿意再攒。
  rdm.items.forEach(x => {
    items.push({
      key: 'rd', ico: 'i-chest', tone: 'var(--gold-deep)', id: x.id,
      title: x.item_name + ' · ' + x.member_name,
      l1: x.desc + (x.note ? ' · 他说：' + x.note : ''),
      l2: String(x.created_at || '').slice(0, 16) + ' 用掉的，卡已经不退了',
      btn: { t: 'rd-ok', id: x.id, label: '做到了' },
      alt: { t: 'rd-no', id: x.id, label: '这次没兑现' },
    });
  });
  // 设置改动待确认
  if (dash.todo && dash.todo.settings) {
    items.push({
      key: 'set', ico: 'i-gear', tone: 'var(--ink-2)', id: 0,
      title: '有 ' + dash.todo.settings + ' 条设置改动等你点头',
      l1: '改的是价格、门槛、额度这类东西',
      l2: '这几项改完对所有孩子立刻生效，所以要第二个人点头',
      btn: { t: 'set-look', id: 0, label: '看看' },
    });
  }
  return { dash: dash, items: items, tasks: tasks, calib: calib, pendW: pendW,
    cash: cash, ot: ot, hlp: hlp, rdm: rdm, subs: subs, tk: tk };
}

/* 待办卡的分类词。首页那张「待审核」的副标就从这同一串 item 上数出来 ——
   手写一句「券 1 · 任务 2」的话，它迟早会跟旁边的数字说的是两件事。 */
const TODO_LABEL = {
  tk: '券', fix: '修复', claim: '心愿', task: '任务', wish: '心愿',
  ot: '加时', cash: '零花钱', help: '求助', rd: '兑现卡', set: '设置',
};
function pTodoBreakdown(TD) {
  const cnt = {};
  TD.items.forEach(x => {
    const k = TODO_LABEL[x.key] || x.key;
    cnt[k] = (cnt[k] || 0) + 1;
  });
  const parts = Object.keys(cnt).map(k => k + ' ' + cnt[k]);
  return parts.length ? parts.join(' · ') : '今天没有要审的';
}

/* 一张待办卡。每张只有**一个主行动按钮** —— 多个并列的主按钮会让家长犹豫
   「这几个哪个才是真的」，而这类动作本来就互斥。需要一条退路的地方
   （不同意 / 退回 / 不算）给一个描边的次按钮，视觉上明显轻一级。 */
function pTodoCard(it) {
  const btn = it.btn
    ? '<button type="button" class="btn btn--primary btn--sm" data-td="' + it.btn.t +
      '" data-id="' + it.btn.id + '">' + esc(it.btn.label) + '</button>' : '';
  const alt = it.alt
    ? '<button type="button" class="btn btn--ghost btn--sm" data-td="' + it.alt.t +
      '" data-id="' + it.alt.id + '">' + esc(it.alt.label) + '</button>' : '';
  return '<div class="card" data-tdid="' + it.key + '">' +
    '<div style="display:flex;align-items:center;gap:10px">' +
    pic(it.ico, 20, '', it.tone) +
    '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px">' +
    '<span class="card-title">' + esc(it.title) + '</span>' +
    (it.l1 ? '<span class="caption--warm" style="font-size:11px">' + esc(it.l1) + '</span>' : '') +
    (it.l2 ? '<span class="caption">' + esc(it.l2) + '</span>' : '') +
    '</div>' + (btn || alt ? '<div class="act-row">' + btn + alt + '</div>' : '') +
    '</div></div>';
}

/* 说「不」的弹层。拒绝必须写理由：这句话孩子看得见，写「不行」他下次还是
   不知道怎么做才行。措辞按事情分开，不用一句万能的。 */
function pRejectSheet(o) {
  sheet('<h3>' + esc(o.title) + '</h3><p class="muted">' + esc(o.hint) + '</p>' +
    '<div class="field"><textarea id="pn" placeholder="' + esc(o.placeholder) + '"></textarea></div>' +
    '<button class="btn wide btn--primary" id="go">' + esc(o.ok) + '</button>', box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          const body = Object.assign({}, o.body, { reject_note: $('#pn', box).value });
          await api('POST', o.path, body);
          closeSheet(); toast(o.toast); await render();
        } catch (e) { err(e); }
      });
    });
}
function tkRejectSheet(id) {
  pRejectSheet({
    title: '不同意这次核销',
    hint: '拒绝必须写理由，孩子能看到。别只写「不行」，写清楚为什么，他下次才知道怎么才行。',
    placeholder: '例如：今天作业还没写完，写完再说', ok: '拒绝',
    path: '/api/tickets/resolve', body: { request_id: id, approve: false }, toast: '拒了',
  });
}
function taskReturnSheet(id) {
  sheet('<h3>退回</h3><p class="muted">退回不加重罚，但要写清哪里没做到</p>' +
    '<div class="field"><textarea id="pn" placeholder="例如：第三层没归位"></textarea></div>' +
    '<button class="btn wide btn--primary" id="go">退回</button>', box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          await api('POST', '/api/tasks/' + id + '/return', { note: $('#pn', box).value });
          closeSheet(); toast('退回了'); await render();
        } catch (e) { err(e); }
      });
    });
}
function otRejectSheet(id) {
  pRejectSheet({
    title: '拒绝加时', hint: '拒绝必须写理由，孩子能看到',
    placeholder: '例如：今天作业还没写完', ok: '拒绝',
    path: '/api/overtime/' + id + '/resolve', body: { approve: false }, toast: '拒了',
  });
}
function cashRejectSheet(id) {
  pRejectSheet({
    title: '不同意这次兑换',
    hint: '写一句为什么，他看得到。额度是设置里定死的，这里拒的应该是「时机」' +
      '或者「想买的东西」，不是额度。',
    placeholder: '例如：这个月的已经换过了，下周再来', ok: '不同意',
    path: '/api/cash/requests/' + id + '/resolve', body: { approve: false }, toast: '记下了',
  });
}
function redeemFailSheet(id) {
  pRejectSheet({
    title: '这次没能兑现',
    hint: '写一句原因，孩子能看到。卡已经扣掉了，不退回。',
    placeholder: '例如：这周末爸妈都要加班，下周补上', ok: '记下来',
    path: '/api/cards/redeems/' + id + '/done', body: { done: false }, toast: '记下了',
  });
}

/* 「看看」：孩子交上来的那一条，原话和两个动作都在同一个弹层里。
   确认和驳回是同一件事的两面，分摆在两个地方，家长点完「看看」会以为
   还得回列表再点一次。 */
function claimSheet(x) {
  if (!x) return;
  sheet('<h3>' + esc(x.who) + '说做到了</h3>' +
    '<p class="muted">心愿《' + esc(x.title) + '》</p>' +
    '<div class="callout-line">这一条：' + esc(x.cond_text || x.cond_key) + '</div>' +
    (x.note ? '<div class="callout-line">他说：' + esc(x.note) + '</div>' : '') +
    '<div class="muted" style="margin-top:8px">' +
    esc(String(x.created_at || '').slice(5, 16)) + ' 提交</div>' +
    '<div class="field" style="margin-top:10px"><label>要走驳回这条路，先写清差在哪</label>' +
    '<textarea id="pn" placeholder="例如：第 25 页空着没写"></textarea></div>' +
    '<div class="act-row">' +
    '<button class="btn btn--primary" id="ok">确认做到了</button>' +
    '<button class="btn btn--ghost" id="no">这一条还不算</button></div>',
    box => {
      $('#ok', box).addEventListener('click', () => {
        askSheet({
          title: (x.who || '') + '说「' + (x.cond_text || x.cond_key) + '」做到了',
          hint: '这一条计入且不能收回；驳回要写清差在哪',
          ok: '确认做到了',
        }, async () => {
          const r = await api('POST', '/api/wishes/claims/' + x.id, { approve: true });
          closeSheet();
          toast(r && r.done ? '确认了，这条心愿够了' : '确认了这一条');
          await render();
        }, () => claimSheet(x));      // 取消退回刚才那一张，不是把弹层全关掉
      });
      $('#no', box).addEventListener('click', async () => {
        try {
          await api('POST', '/api/wishes/claims/' + x.id,
            { approve: false, reject_note: $('#pn', box).value });
          closeSheet(); toast('退回去了'); await render();
        } catch (e) { err(e); }
      });
    });
}

/* 待办卡上的动作。一处实现，首页和审核页共用 —— 同一件事在两个页面
   绑定两遍，改一处漏一处的时候，就会出现「首页点得动、审核页点不动」。 */
function bindTodoActions(TD) {
  const done = async msg => { toast(msg); await render(); };
  $$('#view button[data-td]').forEach(b => b.addEventListener('click', async () => {
    const t = b.dataset.td, id = +b.dataset.id;
    try {
      if (t === 'tk-no') return tkRejectSheet(id);
      if (t === 'tk-ok') {
        const x = TD.tk.items.filter(y => y.id === id)[0] || {};
        return askSheet({
          title: (x.who || '') + ' 想用 ' + num(x.qty) + ' 张' + (x.item || ''),
          hint: '点完这 ' + num(x.qty) + ' 张券立刻生效，倒计时开始走。',
          ok: '同意，扣他 ' + num(x.qty) + ' 张券',
        }, async () => {
          await api('POST', '/api/tickets/resolve', { request_id: id, approve: true });
          closeSheet(); await done('同意了');
        });
      }
      if (t === 'task-no') return taskReturnSheet(id);
      if (t === 'task-ok') {
        const x = TD.tasks.items.filter(y => y.id === id)[0] || {};
        const repair = x.kind === 'repair';
        return askSheet({
          title: repair ? '修复任务 · ' + (x.title || '')
            : (x.assignee || '') + '交了「' + (x.title || '') + '」',
          hint: repair
            ? '奖励立刻到账且不能收回；不对就点「退回」并写理由'
            : '奖励：' + (x.reward_text || '') + '。点完奖励立刻进他账上；放着不管 48 小时后系统自己发',
          ok: repair ? '确认完成' : '发奖，奖励现在给他',
        }, async () => {
          await api('POST', '/api/tasks/' + id + '/confirm');
          closeSheet(); await done('确认了');
        });
      }
      if (t === 'claim-look') {
        return claimSheet(TD.subs.items.filter(x => x.id === id)[0]);
      }
      if (t === 'wcfg') {
        const w = TD.pendW.items.filter(x => x.id === id)[0];
        if (w) wishConfigureSheet(w, () => render());
        return;
      }
      if (t === 'ot-no') return otRejectSheet(id);
      if (t === 'ot-ok') {
        const x = TD.ot.items.filter(y => y.id === id)[0] || {};
        return askSheet({
          title: (x.name || '') + ' 申请加时 ' + num(x.minutes) + ' 分钟',
          hint: '点完星尘立刻扣，换 ' + num(x.minutes) + ' 分钟。',
          line: (x.reason || '没写理由') + ' · 花 ' + num(x.cost) + ' 星尘',
          ok: '同意，扣他 ' + num(x.cost) + ' 星尘',
        }, async () => {
          await api('POST', '/api/overtime/' + id + '/resolve', { approve: true });
          closeSheet(); await done('同意了');
        });
      }
      if (t === 'cash-no') return cashRejectSheet(id);
      if (t === 'cash-ok') {
        const x = TD.cash.items.filter(y => y.id === id)[0] || {};
        return askSheet({
          title: (x.name || '') + ' 想换 ' + num(x.est_cash) + ' 元',
          hint: '批了就当场扣 ' + num(x.stardust) + ' 星尘，你把 ' +
            num(x.est_cash) + ' 元现金给他。',
          ok: '同意，扣 ' + num(x.stardust) + ' 星尘',
        }, async () => {
          const r = await api('POST', '/api/cash/requests/' + id + '/resolve', { approve: true });
          closeSheet();
          return done('批了 ' + num(r.cash) + ' 元，把现金给他');
        });
      }
      if (t === 'help-ok') {
        const x = TD.hlp.items.filter(y => y.id === id)[0] || {};
        return askSheet({
          title: (x.name || '') + ' 说卡住了',
          hint: '他肯说自己卡住就值得记一笔，点完给他 1 星尘。',
          line: x.detail || '',
          ok: '核实，发 1 星尘',
        }, async () => {
          await api('POST', '/api/help/' + id + '/verify', { approved: true });
          closeSheet(); await done('发了 1 星尘');
        });
      }
      if (t === 'rd-no') return redeemFailSheet(id);
      if (t === 'rd-ok') {
        const x = TD.rdm.items.filter(y => y.id === id)[0] || {};
        return askSheet({
          title: x.item_name + ' · ' + x.member_name,
          hint: '从待兑现列表里划掉，卡片不退回，他能看到你点了。',
          ok: '确认已兑现',
        }, async () => {
          await api('POST', '/api/cards/redeems/' + id + '/done', { done: true, note: '' });
          closeSheet(); await done('记下了');
        });
      }
      if (t === 'set-look') return openQA('settings');
    } catch (e) { err(e); }
  }));
}

/* ================================================================== 家长端 · 总览 */
/* 家长打开这一页要回答三件事：现在正在发生什么、今晚我还要办几件、
   两个孩子各自怎么样。顺序就按这个来，「最近发生」压在最下面。
   家长端不显示星球等级 —— 等级只在孩子端出现，这里一个数字都不给。 */
async function renderAdminHome(v) {
  const TD = await pTodoData();
  const r = await Promise.all([
    pg('/api/kids/overview', { items: [] }),
    pg('/api/tickets/playing', { items: [] }),
    pg('/api/feed?limit=10&recent=6', { items: [], recent: [], total: 0 }),
  ]);
  const ov = r[0], pl = r[1], fd = r[2];
  const kids = (ov.items || []);
  const n = TD.items.length;

  // 还没打分的孩子。首页那句「今天还没给小满打分」和速览里的「未打」说的是同一件事，
  // 说法必须一样 —— 一个写「还没打」、一个写「0/7」，家长会以为孩子真的拿了 0 分。
  // 「0 分」和「没打分」在规则里本来就是两件事。
  const unscored = kids.filter(k => k.today && !k.today.scored && !k.today.transition);

  let h = '<div class="page-head">' +
    '<div class="left"><div class="head-line">' +
    '<span class="heading-page">' + esc(pHello()) + '</span>' +
    '<span class="badge-pilot">领航员</span></div>' +
    '<span class="caption--warm">' + esc(pDayLine()) + ' · ' +
    (unscored.length
      ? '今天还没给' + unscored.map(k => esc(k.name)).join('、') + '打分'
      : '今天的分都记上了') + '</span></div>' +
    '<button class="bell" type="button" data-go="review">' + pic('i-bell', 20) +
    (n ? '<span class="dot">' + n + '</span>' : '') + '</button>' +
    '</div>';

  // 正在玩：有时效，家长晚看两分钟那一段就过去了，所以排在最前面
  h += playingHTML(pl.items);

  h += '<div class="stack"><div class="sec-head"><span class="sec-title">今晚要办的事</span>' +
    '<span class="sec-link" data-go="review">全部 ' + n + ' 件</span></div>' +
    '<div class="grid2">' +
    '<div class="card" style="cursor:pointer" data-go="score">' +
    '<div class="kv" style="margin-bottom:6px">' + pic('i-card-a', 15, '', 'var(--orange)') +
    '<span class="caption--warm" style="font-size:11px">今日打分</span></div>' +
    '<div class="num num--sm">' + (unscored.length ? '还没打' : '都打过') + '</div>' +
    '<div class="caption" style="margin-top:4px">' +
    (unscored.length ? unscored.map(k => esc(k.name)).join('、') + ' · 点一下就能打'
      : '今天没有再要打的了') + '</div></div>' +
    '<div class="card" style="cursor:pointer" data-go="review">' +
    '<div class="kv" style="margin-bottom:6px">' + pic('i-card-b', 15, '', 'var(--orange)') +
    '<span class="caption--warm" style="font-size:11px">待审核</span></div>' +
    '<div class="num num--sm">' + n + ' 件</div>' +
    '<div class="caption" style="margin-top:4px">' + esc(pTodoBreakdown(TD)) + '</div></div>' +
    '</div></div>';

  // 孩子速览：一人一行，永远列全，不受「现在看的是谁」影响 ——
  // 家长想扫一眼「今天俩孩子各自怎么样」，不该还得先切两次人。
  h += '<div class="stack"><div class="sec-head"><span class="sec-title">孩子速览</span>' +
    '<span class="sec-link" data-go="family">全部 ' + kids.length + ' 位</span></div>' +
    '<div class="card" style="padding:12px 16px;display:flex;flex-direction:column;gap:12px">';
  if (!kids.length) h += '<div class="empty">还没有孩子账号</div>';
  kids.forEach((k, i) => {
    const cyc = k.cycle;
    const full = cyc && cyc.tier ? cyc.tier.threshold : 49;
    h += '<div style="display:flex;align-items:center;gap:12px;cursor:pointer" data-kid="' +
      k.member_id + '"' +
      (i ? ';' : '') + '>' +
      pAvatar(k, 44, i) +
      '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px">' +
      '<span style="font-size:16px;font-weight:700;color:var(--ink-title)">' +
      esc(k.name) + '</span>' +
      '<span class="caption--warm">本周能量 ' + num(cyc ? cyc.energy : 0) + '/' + num(full) +
      ' · 星尘 ' + num(k.stardust) + '</span></div>' +
      '<div style="text-align:right;flex:none">' +
      (k.today && k.today.transition
        ? '<div class="num--state" style="color:var(--ink-3)">过渡日</div>'
        : (k.today && k.today.scored
          ? '<div class="num num--lg" style="font-size:17px">' + num(k.today.score) + '/' +
            num(k.today.full) + '</div>'
          : '<div class="num--state">未打</div>')) +
      '<div class="caption">今天</div></div></div>';
  });
  h += '</div></div>';

  // 最近发生：只放两条，其余的点进日志页。首页要的是「看一眼有事没事」，
  // 而不是把账本摊在第一屏上。
  const recent = (fd.recent || []).slice(0, 2);
  h += '<div class="stack"><div class="sec-head"><span class="sec-title">最近发生</span>' +
    '<span style="display:flex;align-items:center;gap:8px">' +
    '<span class="pill" style="font-size:11px;color:var(--orange-deep);cursor:pointer" ' +
    'data-go="logs">筛选 ▾</span>' +
    '<span class="sec-link" data-go="logs">查看全部 ' +
    num(fd.total || recent.length) + ' 条</span></span></div>';
  if (!recent.length) h += '<div class="card"><div class="empty">这会儿没有新记录</div></div>';
  recent.forEach(x => {
    h += '<div class="log-item" style="background:#fff">' + pic('i-log-chest', 20) +
      '<div class="body"><span class="txt">' +
      (x.who ? '<b>' + esc(x.who) + '</b>　' : '') + esc(x.text) + '</span></div>' +
      '<span class="time">' + esc(String(x.ts || '').slice(11, 16)) + '</span></div>';
  });
  h += '</div>';

  v.innerHTML = h;
  bindTodoActions(TD);
  $$('#view [data-go]').forEach(el => el.addEventListener('click', () => pGo(el.dataset.go)));
  $$('#view [data-kid]').forEach(el => el.addEventListener('click', () => {
    S.kidId = +el.dataset.kid; pGo('kid');
  }));
}

/* 「我的」页原来有一行「更多」，里面装着通知、假期日历、备份、家人账号、
   改密码。它和设置页撞车：设置页本来就有「通知与推送」「周期与假期」两组，
   假期日历和推送设备又各在另一处 —— 同一件事两个入口，改了一处另一处不动。
   v41 整行撤掉：
     · 通知与推送、假期日历 → 收进设置页对应的那一组（组里给一个按钮）
     · 备份与导出、家人账号、改我的密码 → 提到「我的」页，各自一行
   家长要找的东西不该先猜它躲在「更多」后面。 */

/* ================================================================== 家长端 · 审核 */
/* 这一页只回答一件事：球在我这边的有几件、每件我该按哪个钮。
   上一版按类型分了七八栏（任务一栏、券一栏、加时一栏、求助一栏……），
   家长得先猜「今天该看哪一栏」；而真正要办的往往只有五件，散在八栏里
   反而看不出总共几件。现在合成一串：最急的排最前面，每张卡一个主按钮。

   分类不再靠栏目标题，靠卡自己的图标与标题 —— 「小朵 想用 1 张娱乐券」
   比「券核销」这四个字更接近家长脑子里那句话。 */
async function renderAdminReview(v) {
  const TD = await pTodoData();
  const mid = kidId();
  const r = await Promise.all([
    pg('/api/tickets/playing', { items: [] }),
    mid ? pg('/api/wishes?member_id=' + mid, { items: [], limit: 0 })
      : Promise.resolve({ items: [], limit: 0 }),
  ]);
  const pl = r[0], wishes = r[1];
  const n = TD.items.length;

  let h = '<div class="page-head" style="flex-direction:column;gap:0">' +
    '<div style="display:flex;align-items:flex-start;justify-content:space-between;width:100%">' +
    '<div class="left"><span class="heading-page">审核</span>' +
    '<span class="caption--warm">' + n + ' 件等你点头 · 最急的排在最上面</span></div>' +
    '<span class="pill pill--orange" style="font-size:13px">' + n + ' 件</span></div></div>';

  h += playingHTML(pl.items);

  h += '<div class="stack"><div class="sec-head"><span class="sec-title">等你点头</span>' +
    '<span class="sec-count">' + esc(pTodoBreakdown(TD)) + '</span></div>';
  if (!n) h += '<div class="card"><div class="empty">这会儿没有要审的</div></div>';
  TD.items.forEach(it => { h += pTodoCard(it); });
  h += '</div>';

  // 已经批过的零花钱。批完不算完 —— 现金还在你口袋里，他那边等着点「收到了」。
  const cashSent = TD.cash.items.filter(x => x.status === 'approved');
  if (cashSent.length) {
    h += '<div class="stack"><div class="sec-head"><span class="sec-title">已发放的零花钱</span>' +
      '<span class="sec-count">等他点「收到了」才算完</span></div>' +
      cashSent.map(x => '<div class="card"><div style="display:flex;align-items:center;gap:10px">' +
        pic('i-shop', 20, '', 'var(--orange)') +
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px">' +
        '<span class="card-title">' + esc(x.name) + ' ' + num(x.cash) + ' 元 ' +
        '<span class="pill pill--gray">已发放</span></span>' +
        '<span class="caption">星尘已经扣了。把现金给他，他点一下「收到了」这一条才算完</span>' +
        '<span class="caption">' + esc(String(x.resolved_at || '').slice(0, 16)) + ' 批的</span>' +
        '</div></div></div>').join('') + '</div>';
  }

  // 心愿单。库里进行中的状态是 active（achieved|claimed|cancelled 是结束态），
  // 这里只列 active，结束的留在记录里。
  const wActive = (wishes.items || []).filter(w => w.status === 'active');
  // 行内只留「达成」，撤心愿收进区块头那一颗。撤是低频动作，
  // 跟每一行复制一遍的话，三行叠着最右边就出现三颗一样的「取消」，
  // 家长扫列表的落点正好压在它上面。
  h += '<div class="stack"><div class="sec-head"><span class="sec-title">进行中的心愿</span>' +
    '<span style="display:flex;align-items:center;gap:8px;margin-left:auto">' +
    '<span class="sec-count">' + esc(mid ? memberName(mid) : '还没有孩子账号') +
    '　最多 ' + num(wishes.limit || 0) + ' 个</span>' +
    '<button class="btn btn--ghost btn--sm" id="wManage">撤心愿</button></span></div>' +
    '<div class="card">' +
    (wActive.length ? wActive.map(w =>
      '<div class="row">' + pic('i-wish', 20) +
      '<div class="row-body"><span class="row-title">' + esc(w.title) + '</span>' +
      '<span class="row-sub">' + esc(w.reward_desc || '') +
      (w.price_note ? '　' + esc(w.price_note) : '') +
      (w.selfpay_stardust ? '　已付 ' + num(w.selfpay_stardust) + ' 星尘' : '') + '</span></div>' +
      '<div class="act-row"><button class="btn btn--primary btn--sm" data-wok="' + w.id +
      '">达成</button></div>' +
      '</div>').join('')
      : '<div class="empty">没有进行中的心愿</div>') + '</div></div>';

  // 校准记录：留档，不催办。它压在最下面，因为它是「已经处理过的事」。
  const calibs = (TD.calib.items || []);
  h += '<div class="stack"><div class="sec-head"><span class="sec-title">最近的校准</span>' +
    '<span class="sec-count">' + esc(mid ? memberName(mid) : '') + '　最近 10 条</span></div>' +
    '<div class="card">' +
    (calibs.length ? calibs.slice(0, 10).map(c =>
      '<div class="row">' + pic('i-fix', 20, '', 'var(--warn)') +
      '<div class="row-body"><span class="row-title">' + esc(c.reason) + '</span>' +
      '<span class="row-sub">' + esc(String(c.created_at || c.ts || '').slice(0, 16)) +
      (c.task_title ? '　修复任务：' + esc(c.task_title) + '（' + esc(c.task_status) + '）' : '') +
      '</span></div>' +
      '<span class="pill pill--gray">' + esc((c.effect && c.effect.type) || '记录') + '</span>' +
      '</div>').join('')
      : '<div class="empty">还没有校准记录</div>') + '</div></div>';

  v.innerHTML = h;

  bindTodoActions(TD);
  $$('#view button[data-wok]').forEach(b => b.addEventListener('click', async () => {
    const w = (wishes.items || []).filter(x => x.id === +b.dataset.wok)[0] || {};
    askSheet({
      title: '心愿《' + (w.title || '') + '》',
      hint: '这条心愿进「已达成」，等下一步兑现。',
      ok: '达成，记下来',
    }, async () => {
      try {
        await api('POST', '/api/wishes/' + b.dataset.wok + '/status', { status: 'achieved' });
        closeSheet(); toast('记下了，不设否决权'); await render();
      } catch (e) { err(e); }
    });
  }));
  // 撤心愿的入口收在区块头那一颗，点开的是心愿总台（wishSheet），
  // 那边每条进行中的心愿都挂着一颗「撤掉这个心愿」。同一个动作只有一套文案。
  const wm = $('#wManage');
  if (wm) wm.addEventListener('click', () => wishSheet());
}

/* ================================================================== 家长端 · 孩子详细 */
/* 二级页的返回条。交付包里它是页头左边那个圆角返回钮，
   不是旧版那条「‹ 返回」横杠 —— 二级页压在 Tab 之上，返回键把人送回入口那一屏。 */
function backBar(to, title, sub) {
  return '<div class="page-head" style="align-items:center">' +
    '<div style="display:flex;align-items:center;gap:10px;min-width:0">' +
    '<button class="back-btn" type="button" data-back="' + to + '">' + pic('i-back', 18) + '</button>' +
    '<div class="left"><span class="heading-sub">' + esc(title) + '</span>' +
    (sub ? '<span class="caption">' + esc(sub) + '</span>' : '') + '</div></div></div>';
}

async function renderKidDetail(v) {
  const mid = S.kidId || targetId();
  const d = await api('GET', '/api/kids/' + mid + '/detail');
  const ev = await api('GET', '/api/events?member_id=' + mid);
  const lv = d.level;
  let h = backBar('home', d.name, lv ? 'LV ' + lv.level + '　' + lv.title : '');

  // 头部：等级、星尘、欠款
  h += '<div class="sec"><div class="card pad">' +
    '<div class="row between"><div class="row" style="gap:10px">' +
    '<div class="kav">' + esc((d.avatar || d.name).slice(0, 2)) + '</div>' +
    '<div><div class="nm" style="font-weight:700;font-size:16px">' + esc(d.name) + '</div>' +
    '<div class="muted">' + (d.today.scored
      ? '今天拿了 ' + num(d.today.score) + '/' + num(d.today.full) + ' 分'
      : (d.today.transition ? '今天是过渡日，不计分' : '今天还没打分')) + '</div></div>' +
    '</div><button class="btn sm" data-ds="' + mid + '">' +
    (d.today.scored ? '改分' : '去打分') + '</button></div>' +
    '<div class="kstats" style="margin-top:11px">' +
    '<div><span>星尘</span><strong>' + num(d.stardust) + '</strong></div>' +
    '<div><span>欠款</span><strong' + (d.debt > 0 ? ' class="no-t"' : '') + '>' + num(d.debt) + '</strong></div>' +
    '<div><span>碎片</span><strong>' + num(d.fragment) + '</strong></div>' +
    '<div><span>累计</span><strong>' + num(lv ? lv.total : 0) + '</strong></div>' +
    '</div>';
  if (lv) {
    h += '<div class="lv-plain"><div class="lv-line"><span class="lv-chip">LV <strong>' + lv.level +
      '</strong></span>' +
      '<span class="lv-title">' + esc(lv.title) + '</span>' +
      '<span class="lv-xp">' + num(lv.total) + ' / ' +
      num(lv.next ? lv.next.threshold : lv.threshold) + '</span></div>' +
      '<div class="xp-track"><i style="width:' + lv.percent + '%"></i></div>' +
      '<div class="hero-note">' + (lv.next
        ? '再攒 ' + num(lv.need) + ' 星尘升到「' + esc(lv.next.title) + '」。'
        : '已经是最高一档了。') + '</div></div>';
  }
  h += '</div></div>';

  // 周期
  if (d.cycle) {
    h += '<div class="sec"><div class="sec-h"><h2>这个周期</h2>' +
      '<span class="sub">' + esc(d.cycle.start_date) + ' 到 ' + esc(d.cycle.end_date) + '</span></div>' +
      cycleCard(d.cycle) + '</div>';
  }

  // 这一周
  if (d.week.length) {
    h += '<div class="sec"><div class="sec-h"><h2>这一周</h2>' +
      '<span class="sub">每天固定 ' + num(d.week[0].full) + ' 分</span></div>' +
      '<div class="card pad"><div class="daystrip">' + d.week.map(x =>
        '<div class="daycell ' + (x.scored ? 'done' : '') + (x.transition ? ' lock' : '') +
        (x.future ? ' lock' : '') + '"><b>' + (x.scored ? num(x.score) : '—') + '</b>' +
        x.day.slice(5) + '</div>').join('') + '</div></div></div>';
  }

  // 手上的东西
  h += '<div class="sec"><div class="sec-h"><h2>拥有</h2>' +
    '<span class="sub">券 ' + d.tickets.length + ' 种、卡 ' + d.cards.length + ' 种</span></div>' +
    '<div class="card pad"><div class="kstats">' +
    '<div><span>券</span><strong>' + num(d.tickets.reduce((a, b) => a + b.qty, 0)) + ' 张</strong></div>' +
    '<div><span>卡</span><strong>' + num(d.cards.reduce((a, b) => a + b.qty, 0)) + ' 张</strong></div>' +
    '<div><span>碎片</span><strong>' + num(d.fragment) + '</strong></div>' +
    '</div>';
  if (d.tickets.length) {
    h += '<div class="hr"></div>' + d.tickets.map(t =>
      '<div class="item"><div class="txt"><div class="nm">' + esc(t.name) +
      ' <span class="tag">' + num(t.qty) + ' 张</span></div>' +
      '<div class="ds">' + esc(t.desc || '') + '</div></div></div>').join('');
  }
  if (d.cards.length) {
    h += '<div class="hr"></div>' + d.cards.map(c =>
      '<div class="item"><div class="txt"><div class="nm">' + esc(c.name) +
      ' <span class="tag ' + (c.rarity === 'diamond' ? 'gold' : '') + '">' +
      esc(RAR[c.rarity] || c.rarity) + '</span>' +
      (c.qty > 1 ? ' <span class="tag">×' + num(c.qty) + '</span>' : '') + '</div>' +
      '<div class="ds">' + esc(c.desc || '') +
      (c.days_left != null ? '　还剩 ' + c.days_left + ' 天' : '') + '</div></div></div>').join('');
  }
  if (!d.tickets.length && !d.cards.length) h += '<div class="empty">手上还没有券和卡</div>';
  h += '</div></div>';

  // 在做的事
  h += '<div class="sec"><div class="sec-h"><h2>在做的事</h2>' +
    '<span class="sub">任务 ' + d.tasks.length + '、求助 ' + d.helps.length +
    '、心愿 ' + d.wishes.length + '</span></div><div class="card pad">';
  if (!d.tasks.length && !d.helps.length && !d.wishes.length) {
    h += '<div class="empty">手上没有没做完的事</div>';
  }
  d.tasks.forEach(t => {
    h += '<div class="item">' + glyph(t.icon, t.kind === 'repair' ? 'repair' : 'task', 28) +
      '<div class="txt"><div class="nm">' + esc(t.title) +
      ' <span class="tag">' + (TASK_STATE[t.status] || t.status) + '</span></div>' +
      '<div class="ds">' + esc(t.std) + '</div>' +
      '<div class="ds">奖励 ' + esc(t.reward_text) + '</div></div></div>';
  });
  d.helps.forEach(x => {
    h += '<div class="item"><div class="txt"><div class="nm">求助 <span class="tag">等确认</span></div>' +
      '<div class="ds">' + esc(x.detail) + '　' + esc(String(x.ts).slice(5, 16)) + '</div></div></div>';
  });
  d.wishes.forEach(x => {
    h += '<div class="item">' + glyph(x.icon, 'wish', 28) +
      '<div class="txt"><div class="nm">心愿：' + esc(x.title) +
      ' <span class="tag">进行中</span></div>' +
      '<div class="ds">' + esc(x.reward_desc || '') + '</div></div></div>';
  });
  h += '</div></div>';

  // 两个独立事件通道（第 09 / 10 章）。刻意不进打分表：一旦跟每日得分挂钩，
  // 孩子会倾向隐藏而不是改善。
  h += '<div class="sec"><div class="sec-h"><h2>事件</h2>' +
    '<span class="sub">不算分数、不罚钱</span></div><div class="card pad">';
  if (ev.state && ev.state.active) {
    h += '<div class="notice warn">设备降级中，还有 ' + ev.state.days_left + ' 天到期' +
      (ev.state.reason ? '：' + esc(ev.state.reason) : '') + '</div>';
  }
  if (!ev.device.length && !ev.hw.length) {
    h += '<div class="empty">还没有记录</div>';
  }
  ev.device.forEach(x => {
    h += '<div class="item"><div class="txt"><div class="nm">设备降级 ' + x.days + ' 天 ' +
      '<span class="tag ' + (x.status === 'active' ? 'warn' : '') + '">' +
      (x.status === 'active' ? '生效中' : '已恢复') + '</span></div>' +
      '<div class="ds">' + esc(x.start_date) + ' → ' + esc(x.end_date) +
      (x.reason ? '　' + esc(x.reason) : '') + '</div></div></div>';
  });
  ev.hw.forEach(x => {
    h += '<div class="item"><div class="txt"><div class="nm">作业复核 ' +
      '<span class="tag">撤 ' + num(x.revoked) + ' 分</span></div>' +
      '<div class="ds">' + esc(x.day) + (x.subject ? '　' + esc(x.subject) : '') +
      (x.note ? '　' + esc(x.note) : '') + '</div></div></div>';
  });
  h += '<div class="hr"></div>' +
    '<div class="row"><button class="btn sm line" data-ev="steal">记一次偷玩</button>' +
    '<button class="btn sm line" data-ev="hw">作业复核</button></div>' +
    '</div></div>';

  h += '<div class="sec"><button class="btn wide line" data-kh="' + mid + '">打分记录 →</button></div>';

  v.innerHTML = h;
  $$('#view button[data-back]').forEach(b => b.addEventListener('click', () => {
    S.view = b.dataset.back; renderTabs(); render();
  }));
  $$('#view button[data-kh]').forEach(b => b.addEventListener('click', () => goHistory()));
  $$('#view button[data-ds]').forEach(b => b.addEventListener('click', () => {
    S.target = mid; S.day = todayStr(); S.view = 'score'; renderTabs(); render();
  }));
  $$('#view button[data-ev]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.ev === 'steal') stealGameSheet(mid); else homeworkSheet(mid);
  }));
}

function goHistory() {
  S.view = 'history'; renderTabs(); render();
}

/* ================================================================== 家长端 · 打分记录 */
async function renderKidHistory(v) {
  const mid = S.kidId || targetId();
  const range = S.histDays || 30;
  const d = await api('GET', '/api/score/history?member_id=' + mid + '&days=' + range);
  const kid = memberOf(mid);
  let h = backBar('kid', (kid ? kid.name : '') + ' 的打分记录',
    d.start + ' 到 ' + d.end + '　合计 ' + num(d.total.score) + '/' + num(d.total.full) +
    '（' + Math.round(d.total.rate * 100) + '%）');

  // 范围切换
  h += '<div class="sec"><div class="rangepick">' +
    [[7, '本周'], [30, '近 30 天'], [90, '近 90 天']].map(r =>
      '<button data-rg="' + r[0] + '" class="' + (range === r[0] ? 'on' : '') + '">' +
      r[1] + '</button>').join('') + '</div></div>';

  // 天 × 维度 矩阵
  const cols = d.dims;
  h += '<div class="sec"><div class="sec-h"><h2>每天拿了哪些分</h2>' +
    '<span class="sub">打勾=拿到了，横杠=当天打了分但这项没做到，空白=这天没打分。点一行看为什么扣</span></div>' +
    '<div class="card pad"><div class="mx-wrap"><table class="mx"><thead><tr><th>日期</th>' +
    cols.map(c => '<th title="' + esc(c.name) + '">' +
      glyph(c.icon, 'dim', 22, 'mx-ic') + '</th>').join('') +
    '<th>合计</th></tr></thead><tbody>';
  d.days.forEach(it => {
    const cls = it.transition ? 'trans' : (it.future ? 'fut' : '');
    const why = it.reason.lost.length || it.reason.note;
    h += '<tr class="' + cls + (why ? ' haswhy' : '') + '" data-day="' + it.day + '">' +
      '<td class="mx-day">' + it.day.slice(5) + '</td>' +
      it.cells.map(c => '<td class="mx-c ' + (c.got ? 'yes' : (c.value != null ? 'no' : '')) + '">' +
        (c.got ? '✓' : (c.value != null ? '–' : '')) + '</td>').join('') +
      '<td class="mx-sum">' + (it.scored ? num(it.score) : '—') + '</td></tr>' +
      (why ? '<tr class="mx-why" data-why="' + it.day + '" hidden><td colspan="' +
        (cols.length + 2) + '">' +
        (it.reason.lost.length ? '缺：' + esc(it.reason.lost.join('、')) : '') +
        (it.reason.note ? (it.reason.lost.length ? '　' : '') + '备注：' + esc(it.reason.note) : '') +
        '</td></tr>' : '');
  });
  h += '</tbody></table></div></div></div>';

  // 各维度达成率
  h += '<div class="sec"><div class="sec-h"><h2>各维度达成率</h2>' +
    '<span class="sub">只算这段里打过分的 ' + d.total.days + ' 天</span></div><div class="card pad">' +
    cols.map(c => '<div class="rate-row"><div class="rr-h">' + glyph(c.icon, 'dim', 18) +
      '<span>' + esc(c.name) + '</span><b>' + c.hit + '/' + c.total + '</b></div>' +
      '<div class="bar"><i style="width:' + Math.round(c.rate * 100) + '%"></i></div></div>').join('') +
    '</div></div>';

  v.innerHTML = h;
  $$('#view button[data-back]').forEach(b => b.addEventListener('click', () => {
    S.view = b.dataset.back; renderTabs(); render();
  }));
  $$('#view button[data-rg]').forEach(b => b.addEventListener('click', () => {
    S.histDays = +b.dataset.rg; render();
  }));
  // 点一行展开「为什么不是满分」。默认收着，30 天全展开太长了
  $$('#view tr.haswhy[data-day]').forEach(tr => tr.addEventListener('click', () => {
    const r = $('#view tr.mx-why[data-why="' + tr.dataset.day + '"]');
    if (r) r.hidden = !r.hidden;
  }));
}

/* ================================================================== 家长端 · 任务 */
const TASK_STATE = { open: '等人领', pending: '待做', claimed: '在做', submitted: '等确认',
  confirmed: '已完成', returned: '退回过', archived: '已撤销', abandoned: '放回去了' };

/* ================================================================== 家长端 · 发布 */
/* 发布这一格回答的是「我手上这件事想让谁去做、做到什么程度算完」。
   上一版这里叫「任务」，第一屏是两个弹层入口（发一个任务 / 挂到大厅），
   家长得先点开弹层才知道有哪些选项。现在把表单摊在页面上：
   标题、完成标准、给什么、几个人接、接取时限，一眼看全再发。

   「完成标准」不是可选项。空着发出去的活，最后一定变成
   「你到底做没做」的争论 —— 所以它跟标题并列摆在同一张卡里。 */
let P_PUBSEG = 'new';          // 'new' 写任务 / 'mine' 我发出的

function pPubRewards() {
  const opts = [['stardust', '星尘', 5], ['energy', '周能量', 1],
    ['ticket', '娱乐券', 1], ['box', '银箱', 3]];
  return '<div class="field" style="gap:7px"><span class="field-label">奖励</span>' +
    '<div class="chips">' + opts.map((o, i) =>
      '<button type="button" class="chip' + (i ? '' : ' on') + '" data-r="' + o[0] +
      '" data-d="' + o[2] + '">' + esc(o[1]) + '</button>').join('') + '</div></div>';
}

/* 数量用步进器，不用数字输入框：手机上那个框会顶起数字键盘，还容易留成
   0 或者空着 —— 孩子领了活才发现奖励是空的。点加减，最小 1，改不错。 */
function amtStepper(id, val) {
  return '<div class="stepper">' +
    '<button type="button" class="st-btn" data-st="-1" data-for="' + id +
    '" aria-label="少一个">−</button>' +
    '<input id="' + id + '" class="st-val" value="' + val +
    '" inputmode="numeric" autocomplete="off">' +
    '<button type="button" class="st-btn" data-st="1" data-for="' + id +
    '" aria-label="多一个">+</button></div>';
}
/* 每行底下那句小注跟着所选的按钮走。写死的那一句只对一种选择成立，
   家长换了按钮，那句就成了错的话。 */
const REWARD_TIP = {
  stardust: '星尘一周合计不超过 20 · 花掉不掉等级',
  energy: '周能量只在这一个周期里有效，周末结算清零',
  ticket: '娱乐券发出去就开始计时，用掉才算',
  box: '宝箱只发到银箱 · 稀有卡不发',
};
const TO_TIP = {
  hall: '谁先点谁拿 · 时限内没人接自动下线',
  kid: '直接派给他，不用抢，也不会自动下线',
};
const SLOT_TIP = {
  1: '一个人接走，别人就领不到了',
  2: '两个人都能领到，各一份',
};

/* 「写校准」这一格用的几张表。校准原来是一层弹窗，现在它是发布胶囊的第三格。 */
const CALIB_TPL = [
  ['apology', '道歉修复（24 小时）'],
  ['redo', '行为重做（当天）'],
  ['goods', '实物修复（48 小时）'],
  ['relation', '关系补偿（48 小时）'],
];
const CALIB_HINT = {
  task: '让他去做一件弥补的事，做完由你点确认。',
  fine: '罚的钱进家庭许愿池，不进任何人的口袋。',
  ticket_min: '从这一轮的娱乐时间里扣，不是扣以后。',
  none: '只留一条记录，不动分也不动钱。',
};
/* 三档定在哪一层。原来写死 level 3（契约校准），界面上一个旋钮都不给；
   但规则表里「挂一条修复任务」是第 2 层（联动校准），只有违约罚金才是第 3 层 ——
   一律记成 3，记录跟真正做的事对不上。
   这个字段只写不读：报告不看、统计不看、界面上也不显示。所以也不该做成一个
   选了却什么都不改变的旋钮。按家长选的处理方式自动定档，家长一道题都不用多答。 */
const CALIB_LEVEL = { task: 2, fine: 3, ticket_min: 3, none: 1 };

async function renderAdminPublish(v) {
  const seg = P_PUBSEG;
  const all = await pg('/api/tasks', { items: [] });
  const mine = (all.items || []).filter(t => t.kind !== 'repair' && t.created_by === S.me.id);

  let h = pHead({ title: '发布', sub: '发个任务，谁做到谁拿' });
  // 三格做成真胶囊（底衬 + 选中橙底白字），数字单独一个小牌，
  // 数变了只换牌上的字，整格宽度不跟着抖。
  h += '<div class="seg seg--pill">' +
    '<button type="button" class="seg-item' + (seg === 'new' ? ' on' : '') +
    '" data-pseg="new">写任务</button>' +
    '<button type="button" class="seg-item' + (seg === 'calib' ? ' on' : '') +
    '" data-pseg="calib">写校准</button>' +
    '<button type="button" class="seg-item' + (seg === 'mine' ? ' on' : '') +
    '" data-pseg="mine">我发出的<span class="seg-n">' + mine.length +
    '</span></button></div>';

  if (seg === 'new') {
    /* 两张卡，卡里不再写「① 什么事」这种编号标题 —— 标题占一行、说明又占一行，
       说明比输入框还高，一屏装不下。现在每张卡第一行就是能填的东西。 */
    h += '<div class="card card--lg" style="display:flex;flex-direction:column;gap:12px">' +
      '<div class="field"><span class="field-label">标题</span>' +
      '<input id="pT" placeholder="例如：整理书架"></div>' +
      '<div class="field"><span class="field-label">完成标准</span>' +
      '<input id="pS" placeholder="例如：书按高低排好、台面没灰"></div>' +
      '<p class="caption">写成能核对的样子 —— 「整理房间」和「书按高低排好」不是一件事</p>' +
      '</div>';

    h += '<div class="card card--lg" style="display:flex;flex-direction:column;gap:12px">' +
      pPubRewards() +
      '<div class="field" id="pAmtBox"><span class="field-label">数量</span>' +
      amtStepper('pAmt', 5) + '</div>' +
      '<p class="caption" id="pRwTip">' + esc(REWARD_TIP.stardust) + '</p>' +
      iconField('pIcon', '', 'task', '配一张图') +
      '<p class="caption">他在大厅里先看见的就是这张图。不挑也行，系统会按类型给默认的。</p>' +
      // 给谁：原来分两层（先选挂大厅还是派给孩子，再选哪个孩子），
      // 一层就够 —— 点孩子名字就是派给他，点挂大厅就是谁都能接。
      '<div class="field" style="gap:7px"><span class="field-label">给谁</span>' +
      '<div class="chips">' +
      '<button type="button" class="chip on" data-to="hall">挂大厅</button>' +
      KIDS().map(m => '<button type="button" class="chip" data-to="' + m.id + '">' +
        esc(m.name) + '</button>').join('') + '</div></div>' +
      '<p class="caption" id="pToTip">' + esc(TO_TIP.hall) + '</p>' +
      // 这两问只对挂大厅有意义：派给某个孩子就没有「谁来抢」和「多久下线」
      '<div id="pHallOnly" style="display:flex;flex-direction:column;gap:12px">' +
      '<div class="field" style="gap:7px"><span class="field-label">接取</span>' +
      '<div class="chips">' +
      '<button type="button" class="chip on" data-s="1">单人接取</button>' +
      '<button type="button" class="chip" data-s="2">多人接取</button></div></div>' +
      '<div class="field" style="gap:7px"><span class="field-label">时限</span>' +
      '<div class="chips">' +
      '<button type="button" class="chip on" data-dl="1">今天内</button>' +
      '<button type="button" class="chip" data-dl="2">24 小时</button></div></div>' +
      '<p class="caption" id="pSlotTip">' + esc(SLOT_TIP[1]) + '</p>' +
      '</div></div>';

    /* 「发出去」贴在屏幕底边：这一屏填的东西多，按钮压在最下面要滚到底才
       看得见，填完还得往回滚确认一遍。 */
    h += '<div class="pub-foot">' +
      '<button class="btn btn--primary btn--block" id="pSend">发出去</button>' +
      '<p class="caption" style="text-align:center">挂出去就进任务大厅 · ' +
      '时限内没人接会自动下线，不罚任何人</p></div>';

    v.innerHTML = h;
    bindPublishForm();
  } else if (seg === 'calib') {
    h += '<p class="caption" style="margin-top:2px">校准是让他承担后果，不是罚得越重越好。' +
      '选「挂一条修复任务」的，系统会自己把修复清单挂到他的任务上，做完由你确认。</p>';
    h += '<div class="card card--lg" style="display:flex;flex-direction:column;gap:12px">' +
      '<div class="field"><span class="field-label">谁的事</span>' +
      '<div class="chips">' + KIDS().map((m, i) =>
        '<button type="button" class="chip' + (i ? '' : ' on') + '" data-ckid="' + m.id + '">' +
        esc(m.name) + '</button>').join('') + '</div></div>' +
      '<div class="field"><span class="field-label">哪件事</span>' +
      '<input id="cWhy" placeholder="例如：说好 8 点回家，9 点半才回"></div>' +
      '<div class="field" style="gap:7px"><span class="field-label">怎么处理</span>' +
      '<div class="chips">' +
      '<button type="button" class="chip on" data-ce="task">挂一条修复任务</button>' +
      '<button type="button" class="chip" data-ce="fine">罚款（进许愿池）</button>' +
      '<button type="button" class="chip" data-ce="ticket_min">扣娱乐时间</button>' +
      '<button type="button" class="chip" data-ce="none">只记下来</button></div>' +
      '<p class="caption" id="cHint">' + esc(CALIB_HINT.task) + '</p></div>' +
      '<div class="field" id="cTplBox"><span class="field-label">修复类型</span>' +
      '<select id="cTpl">' + CALIB_TPL.map(t => '<option value="' + t[0] + '">' +
      esc(t[1]) + '</option>').join('') + '</select></div>' +
      '</div>' +
      '<button class="btn btn--primary btn--block" id="cGo">记下来</button>' +
      '<p class="footnote">金额、扣几分钟、负库存下限都在设置「校准与钱」那一组里，' +
      '四条红线改不了。</p>';
    v.innerHTML = h;
    bindCalibForm();
  } else {
    const t = await pTasksHTML();
    h += t.h;
    v.innerHTML = h;
    bindTaskPage(t.d);
  }

  $$('#view .seg-item').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.pseg === seg) return;
    P_PUBSEG = b.dataset.pseg; render();
  }));
}

function bindPublishForm() {
  let rt = 'stardust', defaultAmt = 5, slots = 1, dl = 1;
  // 'hall' 挂大厅谁都能接；其余是孩子的 id —— 点谁的名字就是派给谁。
  // 原来分两层（先选挂大厅还是派人，再选哪个孩子），一层就够。
  let to = 'hall';
  // 选图面板的交互（开合 / 挑图 / 换组 / 搜索）是委托绑在 #view 上的，
  // bindIconField 自己认门牌去重：这个容器不重画，绑一次就够。
  bindIconField($('#view'));
  const tip = (id, s) => { const t = $(id); if (t) t.textContent = s; };
  const amtEl = () => $('#pAmt');

  $$('#view .chip[data-r]').forEach(c => c.addEventListener('click', () => {
    rt = c.dataset.r;
    defaultAmt = +c.dataset.d;
    $$('#view .chip[data-r]').forEach(x => x.classList.remove('on'));
    c.classList.add('on');
    amtEl().value = defaultAmt;
    // 银箱是整档的，填数量没有意义
    $('#pAmtBox').style.display = rt === 'box' ? 'none' : '';
    tip('#pRwTip', REWARD_TIP[rt] || '');
  }));
  $$('#view .st-btn').forEach(b => b.addEventListener('click', () => {
    const inp = $('#' + b.dataset.for);
    if (!inp) return;
    inp.value = Math.max(1, (parseInt(inp.value, 10) || 0) + (+b.dataset.st));
  }));
  $$('#view .st-val').forEach(inp => inp.addEventListener('input', () => {
    const v = parseInt(String(inp.value).replace(/[^\d]/g, ''), 10);
    // 打了一半的空值就让它空着，别在人家手底下把内容改掉
    if (v >= 1) inp.value = v;
  }));
  $$('#view .chip[data-to]').forEach(c => c.addEventListener('click', () => {
    to = c.dataset.to;
    $$('#view .chip[data-to]').forEach(x => x.classList.remove('on')); c.classList.add('on');
    // 派给某个孩子之后，没有「谁来抢」和「多久没人领就下线」这两问
    const hall = to === 'hall';
    $('#pHallOnly').style.display = hall ? '' : 'none';
    tip('#pToTip', hall ? TO_TIP.hall : TO_TIP.kid);
  }));
  $$('#view .chip[data-s]').forEach(c => c.addEventListener('click', () => {
    slots = +c.dataset.s;
    $$('#view .chip[data-s]').forEach(x => x.classList.remove('on')); c.classList.add('on');
    tip('#pSlotTip', SLOT_TIP[slots] || '');
  }));
  $$('#view .chip[data-dl]').forEach(c => c.addEventListener('click', () => {
    dl = +c.dataset.dl;
    $$('#view .chip[data-dl]').forEach(x => x.classList.remove('on')); c.classList.add('on');
  }));
  $('#pSend').addEventListener('click', async () => {
    const title = $('#pT').value, std = $('#pS').value;
    if (!title.trim() || !std.trim()) return err({ message: '标题和完成标准都要写' });
    const amt = Math.max(1, parseInt(amtEl().value, 10) || defaultAmt);
    const reward = rt === 'stardust' || rt === 'energy' ? { amount: amt } :
      rt === 'ticket' ? { code: 'ticket_fun', qty: amt } : { tier: 3 };
    const body = {
      title: title, std: std, reward_type: rt, reward: reward,
      icon: ($('#pIcon') || {}).value || '',
    };
    if (to === 'hall') {
      body.open_to_all = true; body.slots = slots;
      body.deadline = dl === 1 ? todayStr() : shiftDay(todayStr(), 1);
    } else {
      body.assignee_id = +to;
    }
    try {
      await api('POST', '/api/tasks', body);
      const who = KIDS().filter(m => m.id === +to)[0];
      toast(to === 'hall' ? '挂到大厅了' : '派给' + (who ? who.name : '') + '了');
      P_PUBSEG = 'mine';
      await render();
    } catch (e) { err(e); }
  });
}

/* 发布胶囊第三格「写校准」的表单。原来是一层弹窗，现在摊平在这一屏。
   level 不再写死 3，按选的处理方式从 CALIB_LEVEL 取，理由写在那个常数上。 */
function bindCalibForm() {
  let eff = 'task';
  let kid = (KIDS()[0] || {}).id || 0;
  const hint = $('#cHint'), tplBox = $('#cTplBox'), go = $('#cGo');
  $$('#view .chip[data-ckid]').forEach(c => c.addEventListener('click', () => {
    kid = +c.dataset.ckid;
    $$('#view .chip[data-ckid]').forEach(x => x.classList.remove('on')); c.classList.add('on');
  }));
  $$('#view .chip[data-ce]').forEach(c => c.addEventListener('click', () => {
    eff = c.dataset.ce;
    $$('#view .chip[data-ce]').forEach(x => x.classList.remove('on')); c.classList.add('on');
    if (hint) hint.textContent = CALIB_HINT[eff] || '';
    if (tplBox) tplBox.hidden = eff !== 'task';
    if (go) go.textContent = eff === 'fine' ? '罚款并入许愿池' : '记下来';
  }));
  $('#cGo').addEventListener('click', async () => {
    const reason = $('#cWhy').value.trim();
    if (!reason) return err({ message: '写清楚是哪件事，空着记不下来' });
    try {
      const r = await api('POST', '/api/calibration', {
        member_id: kid, level: CALIB_LEVEL[eff] || 1, reason: reason,
        effect_type: eff, template: ($('#cTpl') || {}).value || 'apology',
      });
      toast(r.task_id ? '记下了，修复任务已进他的清单' : '记下了');
      P_PUBSEG = 'mine';
      await render();
    } catch (e) { err(e); }
  });
}

/* ---------------------------------------------------------------- 发出的活 */
/* 三堆分开摆，是按「下一步该谁动」分的，不是按状态名分的：
   等人领 —— 谁都没动，家长可以直接撤；
   进行中 —— 有人接着了，家长撤不掉，要等他自己放开；
   等你确认 —— 他交上来了，球在家长这边。
   撤销按钮在「有人领」那一堆里一律是禁用的：孩子接了活，家长一句话
   抽走，等于告诉他「你做的这件事随时可以被抹掉」。 */
async function pTasksHTML() {
  const d = await api('GET', '/api/tasks/hall');
  const submitted = d.doing.filter(t => t.status === 'submitted');
  const doing = d.doing.filter(t => t.status !== 'submitted');
  let h = '';

  h += '<div class="stack"><div class="sec-head"><span class="sec-title">等你确认</span>' +
    '<span class="sec-count">' + submitted.length + ' 件</span></div><div class="card">';
  if (!submitted.length) h += '<div class="empty">没有交上来的</div>';
  submitted.forEach(t => {
    h += '<div class="row task-row">' + pic('i-task-flag', 20) +
      '<div class="row-body"><span class="row-title">' + esc(t.who || '') + ' · ' +
      esc(t.title) + '</span>' +
      '<span class="row-sub">' + esc(t.std) + '</span>' +
      '<span class="row-sub">奖励 ' + esc(t.reward_text) +
      (t.submitted_at ? '　' + esc(String(t.submitted_at).slice(5, 16)) + ' 交的' : '') +
      (t.hall_id ? '　<span class="pill pill--gray">大厅</span>' : '') + '</span></div>' +
      '<div class="act-row">' +
      '<button class="btn btn--primary btn--sm" data-tc="' + t.id + '">确认</button>' +
      '<button class="btn btn--ghost btn--sm" data-trr="' + t.id + '">退回</button>' +
      '</div></div>';
  });
  h += '</div></div>';

  h += '<div class="stack"><div class="sec-head"><span class="sec-title">进行中</span>' +
    '<span class="sec-count">这些撤不掉，要孩子先放开</span></div><div class="card">';
  if (!doing.length) h += '<div class="empty">没有在做的事</div>';
  doing.forEach(t => {
    h += '<div class="row task-row">' + pic('i-task-flag', 20) +
      '<div class="row-body"><span class="row-title">' + esc(t.who || '') + ' · ' +
      esc(t.title) + ' <span class="pill pill--gray">' +
      (TASK_STATE[t.status] || t.status) + '</span>' +
      (t.hall_id ? ' <span class="pill pill--gray">大厅</span>' : '') + '</span>' +
      '<span class="row-sub">' + esc(t.std) + '</span>' +
      '<span class="row-sub">奖励 ' + esc(t.reward_text) +
      (t.claimed_at ? '　' + esc(String(t.claimed_at).slice(5, 16)) + ' 领的' : '') +
      '</span></div>' +
      '<button class="btn btn--ghost btn--sm" data-tv="' + t.id + '" disabled title="' +
      '得让孩子自己点「我不做了」">撤不掉</button></div>';
  });
  h += '</div></div>';

  h += '<div class="stack"><div class="sec-head"><span class="sec-title">等人领</span>' +
    '<span class="sec-count">' + d.hall.length + ' 件挂在大厅</span></div>';
  if (!d.hall.length) h += '<div class="card"><div class="empty">大厅是空的</div></div>';
  d.hall.forEach(x => {
    const who = x.claims.filter(c => c.status !== 'abandoned');
    h += '<div class="card"><div class="sec-head">' + pic('i-task-flag', 20) +
      '<span class="card-title" style="flex:1;min-width:0">' + esc(x.title) + '</span>' +
      '<span class="pill pill--gray">' + (x.slots === 1 ? '先到先得' : '每人一份') + '</span>' +
      (x.full ? ' <span class="pill pill--orange">已满</span>' : '') + '</div>' +
      '<span class="caption--warm" style="display:block;margin-top:6px">' + esc(x.std) + '</span>' +
      '<span class="caption" style="display:block;margin-top:4px">奖励 ' + esc(x.reward_text) +
      (x.deadline ? '　截止 ' + esc(x.deadline) : '') +
      '　' + esc(String(x.created_at).slice(5, 16)) + ' 发的</span>' +
      (who.length ? '<span class="caption" style="display:block;margin-top:4px">' +
        who.map(c => esc(c.who) + (c.status === 'submitted' ? '（已交）' : '（在做）')).join('、') +
        ' 领了</span>' : '') +
      (x.quit ? '<span class="caption" style="display:block">有 ' + x.quit + ' 次被放回来</span>' : '') +
      '<div class="sec-head" style="margin-top:9px"><span class="caption">' +
      (x.can_revoke ? '没人领，可以直接撤' : '有人在做，撤不掉') + '</span>' +
      '<button class="btn btn--ghost btn--sm" data-tv="' + x.id + '"' +
      (x.can_revoke ? '' : ' disabled') + '>撤销</button></div></div>';
  });
  h += '</div>';

  if (d.done.length) {
    h += '<div class="stack"><div class="sec-head"><span class="sec-title">已结束</span>' +
      '<span class="sec-count">' + d.done.length + ' 件</span></div><div class="card">' +
      d.done.map(x => '<div class="row">' + pic('i-task-flag', 20) +
        '<div class="row-body"><span class="row-title">' + esc(x.title) +
        ' <span class="pill pill--gray">' + (x.state === 'done' ? '做完了' : '撤销了') +
        '</span></span>' +
        '<span class="row-sub">' + (x.done ? x.done + ' 人交了' : '没人交') +
        (x.quit ? '　' + x.quit + ' 次被放回' : '') +
        '　' + esc(String(x.archived_at || x.created_at).slice(5, 16)) + '</span></div>' +
        '</div>').join('') + '</div></div>';
  }
  return { h: h, d: d };
}

/* d 是 pTasksHTML() 取回来的那份 /api/tasks/hall。
   原来是直接引用它的局部量 submitted，作用域外根本取不到 ——
   点一次「确认」或「退回」就 ReferenceError，确认层根本弹不出来。 */
function bindTaskPage(d) {
  $$('#view button[data-tc]').forEach(b => b.addEventListener('click', async () => {
    const t = d.doing.filter(x => x.status === 'submitted' && x.id === +b.dataset.tc)[0] || {};
    askSheet({
      title: (t.who || '') + '交了「' + (t.title || '') + '」',
      hint: '奖励 ' + (t.reward_text || '') +
        '。奖励立刻到账且不能收回；不对就点「退回」并写理由',
      ok: '确认完成',
    }, async () => {
      try {
        await api('POST', '/api/tasks/' + b.dataset.tc + '/confirm');
        closeSheet(); toast('确认了'); render();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-trr]').forEach(b => b.addEventListener('click', () => {
    const tid = +b.dataset.trr;
    sheet('<h3>退回</h3><p class="muted">说清哪一点没达到，不然孩子不知道该改什么</p>' +
      '<div class="field"><textarea id="trNote" placeholder="例如：桌面擦了，抽屉里还是乱的"></textarea></div>' +
      '<button class="btn wide btn--primary" id="trGo" style="margin-top:10px">退回</button>',
      box => {
        $('#trGo', box).addEventListener('click', async () => {
          try {
            await api('POST', '/api/tasks/' + tid + '/return', { note: $('#trNote', box).value });
            closeSheet(); toast('退回了'); render();
          } catch (e) { err(e); }
        });
      });
  }));
  $$('#view button[data-tv]').forEach(b => b.addEventListener('click', async () => {
    const tid = +b.dataset.tv;
    sheet('<h3>撤回这个任务</h3><p class="muted">撤回不留记录可恢复；已经交过的奖励不会追回。' +
      '已经有人领着的撤不掉，要等他自己点「我不做了」。</p>' +
      '<button class="btn wide btn--primary" id="rvGo" style="margin-top:10px">确认撤回</button>',
      box => {
        $('#rvGo', box).addEventListener('click', async () => {
          try {
            await api('POST', '/api/tasks/' + tid + '/revoke');
            closeSheet(); toast('撤销了'); render();
          } catch (e) { err(e); closeSheet(); }
        });
      });
  }));
}

/* ================================================================== 家长端 · 打分 */

/* ---------------------------------------------------------------- 月度统计 */
/* 打分页底部那张日历。数据直接复用 /api/score/history：一次拿一整个月，
   天 × 维度的明细都在里面，点某一天不用再跑一趟接口。
   列固定周一到周日，跟学校课表一个读法。 */
const CAL_WD = ['一', '二', '三', '四', '五', '六', '日'];
let CAL = null;   // 当前渲染出来的那一个月，供点格子弹层用

const ymOf = day => day.slice(0, 7);

function ymShift(ym, n) {
  const d = new Date(+ym.slice(0, 4), +ym.slice(5) - 1 + n, 1);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
}
function daysInMonth(ym) { return new Date(+ym.slice(0, 4), +ym.slice(5), 0).getDate(); }

async function monthData(target, ym) {
  const n = daysInMonth(ym);
  const until = ym + '-' + String(n).padStart(2, '0');
  const d = await api('GET', '/api/score/history?member_id=' + target +
    '&until=' + until + '&days=' + n);
  return { ym: ym, rows: d.days, total: d.total };
}

/* 点某一天弹出的明细。数据就在 CAL 里，不再跑接口。 */
function calDaySheet(r) {
  const p = r.day.split('-');
  let h = '<h3>' + p[0] + ' 年 ' + (+p[1]) + ' 月 ' + (+p[2]) + ' 日 周' + wd(r.day) + '</h3>';
  if (r.transition) h += '<p class="muted">这两天是假期过渡日，不计分。</p>';

  if (r.scored) {
    h += '<div class="dr-sum">得分 <b>' + num(r.score) + '</b> / ' + num(r.full) + '</div>' +
      '<div class="dr-list">' + r.cells.map(c =>
        '<div class="dr-row">' + glyph(c.icon, 'dim', 24, 'dr-ic') +
        '<span class="dr-nm">' + esc(c.name) +
        (c.revision_count ? ' <span class="tag">改过</span>' : '') + '</span>' +
        '<span class="dr-v ' + (c.value > 0 ? 'yes' : 'no') + '">' +
        (c.value > 0 ? '✓' : '✗') + '</span></div>').join('') + '</div>';
    if (r.reason && r.reason.note) {
      h += '<div class="callout-line"><b>备注</b>　' + esc(r.reason.note) + '</div>';
    } else if (r.reason && r.reason.lost.length) {
      h += '<div class="callout-line">扣的是　' + esc(r.reason.lost.join('、')) + '</div>';
    } else {
      h += '<div class="callout-line">这天七项都拿到了。</div>';
    }
  } else {
    h += '<p class="muted">这天没有打分记录。没记录不等于没做到，' +
      '所以它不算进达成率。</p>';
  }

  if (!r.transition && r.day <= todayStr()) {
    h += '<button class="btn wide" id="calGo" style="margin-top:12px">翻到这天</button>';
  }
  if (r.day > todayStr()) h += '<p class="muted">这天还没到。</p>';

  sheet(h, box => {
    const b = $('#calGo', box);
    if (b) b.addEventListener('click', () => {
      S.day = r.day;         // 月份不动，只换上面那张打分卡
      closeSheet(); render();
    });
  });
}

/* 月历这一块的事件绑定。
   翻月只换 #pCalBox 里面那一段，不整页 render：月历在打分页最底部，
   整页重绘会把滚动位置顶回最上面，每翻一次月都要重新往下滚一遍，
   等于没法连着看几个月。翻月不影响上面那张打分卡，本来就没必要重画。
   点日期条和切孩子反过来 —— 上面那张卡要跟着变，那才走整页 render。

   容器 id 由调用方给（rf 画出来的是什么，就换什么），翻月的按钮在
   .cal-nav 里 —— 交付包那张图里 .cal-nav 是个壳，按钮是它里面那两个，
   所以禁用要落到 button 上，落在壳上一点用都没有（壳没有 disabled）。 */
function bindCal(target, day, rf, boxId) {
  const box = $(boxId || '#pCalBox');
  if (!box) return;
  $$('[data-mv]', box).forEach(b => b.addEventListener('click', async () => {
    const mv = +b.dataset.mv;
    if (!CAL) return;
    const ym = ymShift(CAL.ym, mv);
    $$('.cal-nav button', box).forEach(x => { x.disabled = true; });
    try {
      const m = await monthData(target, ym);
      S.month = ym;
      CAL = m;
      box.innerHTML = rf(m, day);
      bindCal(target, day, rf, boxId);
    } catch (e) {
      $$('[data-mv]', box).forEach(x => { x.disabled = false; });
      err(e);
    }
  }));
  $$('#view button[data-cd]').forEach(b => b.addEventListener('click', () => {
    const r = CAL && CAL.rows.find(x => x.day === b.dataset.cd);
    if (r) calDaySheet(r);
  }));
}

/* 打分两屏（今日 / 月度）共用一个页头：孩子切换 + 今日分 + 两段器。
   交付包里这两段是「同一个页头下的分段器」，不是两个独立的 Tab ——
   底栏「打分」那一格永远亮着，切段不换格。 */

/* 七维那一行。做到是实心圆勾，没做到是空描边 + 划掉的名字。
   可编辑时点一下切换；锁死的那一天点不动（光标不是手型，点了也不变）。

   v37：可编辑分两种。没打分的日子（未打 / 补卡）点一项记一项，不用保存；
   打过的日子要先点「修改」才动得了，改完按保存，或者按取消退回去。
   以前一律点一下就生效，改错了只能靠「24 小时内再改回来」兜底 ——
   那句话在结算前是对的，但在已经打完分的那一屏上，一点就改等于没有确认。 */
function pDimRow(d, editable) {
  const off = d.value === 0;
  return '<div class="dim-row' + (off ? ' is-off' : '') +
    (editable ? '' : ' is-locked') + '" data-code="' + d.code + '">' +
    '<span class="dim-check">' + pic('i-check', 14) + '</span>' +
    '<div class="dtxt"><div class="dname">' + esc(d.name) +
    (d.renamed ? ' <span class="pill pill--gray">假期版</span>' : '') + '</div>' +
    '<div class="dm">' + esc(d.meaning) + '</div></div>' +
    '<div class="dval">' + (d.value === null ? '—' : num(d.value)) + '</div></div>';
}
function pDimPaint(el, d) {
  el.classList.toggle('is-off', d.value === 0);
  $('.dval', el).textContent = d.value === null ? '—' : num(d.value);
}
/* 家长端打分页头上那个孩子小胶囊。跟宝箱页的全宽 .seg 是两套，
   别混用 —— 一个是顺手切一下，一个是这一整屏看的是谁。 */
function pKidSwitch(target) {
  const kids = KIDS();
  if (kids.length < 2) return '';
  return '<span class="kid-switch">' + kids.map(k =>
    '<button type="button" data-kid="' + k.id + '"' + (k.id === target ? ' class="on"' : '') +
    '>' + esc(k.name) + '</button>').join('') + '</span>';
}
function pScoreHead(title, target, day, tail, sub2) {
  const kids = KIDS();
  return pHead({
    title: title, sub: pDayLine() + ' · ' + (sub2 || '改完就生效') +
      (day === todayStr() ? '' : '　' + day.slice(5)),
    right: pKidSwitch(target) +
      '<span class="num num--lg" style="font-size:15px">' + (kids.length ? tail : '—') + '</span>',
  });
}

async function renderAdminScore(v) {
  const kids = KIDS();
  if (!kids.length) {
    v.innerHTML = pHead({ title: '打分', sub: '还没有孩子账号' }) +
      '<div class="card"><div class="empty">先开一个孩子的账号，再回来打分</div></div>';
    return;
  }
  const target = kidId();
  const day = S.day || todayStr();
  const sc = await api('GET', '/api/score/day?member_id=' + target + '&day=' + day);
  // 这一天站在哪一格，只认后端那个 state（engine.score_day_state）。
  // 老库或者还没升级的后端不给这个字段，退回用 scored / can_edit 猜一个，
  // 猜错也只是标签不对，不会把锁死的那天放开。
  const state = sc.state ||
    (!sc.can_edit ? (sc.scored ? 'locked' : 'overdue') : (sc.scored ? 'modify' : 'unscored'));
  // 正在改的那一屏。点「修改」才进，进去之前这一格是只读的。
  const editing = P_EDIT && state === 'modify';
  // 未打分 / 补卡：点一项记一项，不用保存。改：只动界面，等保存。
  const tapNow = state === 'unscored' || state === 'backfill';
  const editable = tapNow || editing;
  // 未打分的日子，维度默认算完成（value 由 null 归一成 1），
  // 否则界面上七项都显示「开」，合计却算成 0。只在这天动得了时归一，
  // 翻看历史时保留 null，显示成「—」。
  const dims = editable
    ? sc.dims.map(d => (d.value === null ? Object.assign({}, d, { value: 1 }) : d))
    : sc.dims.slice();
  S.score = { day: day, target: target, dims: dims, can_edit: sc.can_edit, state: state,
    reason: sc.reason, scored: sc.scored, deadline: sc.deadline || '', editing: editing };
  const sum = () => dims.reduce((a, x) => a + (x.value || 0), 0);

  let h = pScoreHead('打分', target, day, num(sum()) + '/' + num(sc.full), pStateSub(state, editing));
  h += '<div class="seg">' +
    '<button type="button" class="seg-item on" data-seg="score">今日打分</button>' +
    '<button type="button" class="seg-item" data-seg="month">月度统计</button></div>';

  h += pStateBand(state, sc, editing);
  if (S.data.holiday) {
    h += '<div class="notice info">现在是' + esc(S.data.holiday.name) + '，维度换成了假期版</div>';
  }

  // 七天日期条：先挑哪天，再挑哪几项没做到
  h += '<div class="card" style="padding:10px"><div class="daystrip">';
  for (let i = -6; i <= 0; i++) {
    const dd = shiftDay(todayStr(), i);
    h += '<button type="button" class="daycell' + (dd === day ? ' on' : '') +
      '" data-day="' + dd + '"><div class="dw">' + wd(dd) + '</div>' +
      '<div class="dd">' + (+dd.slice(8)) + '</div></button>';
  }
  h += '</div></div>';

  h += '<div class="card" style="padding:12px 14px">' +
    '<div class="sec-head" style="margin-bottom:6px">' +
    '<span class="card-title">' + (day === todayStr() ? '今天做到的吗' : '这天做到的吗') + '</span>' +
    '<span class="caption">' + pDimHint(state, editing) + '</span></div>' +
    '<div id="pDimList">' + dims.map(d => pDimRow(d, editable)).join('') + '</div>' +
    '<div class="hr"></div>' +
    '<div class="sec-head"><span class="caption">合计</span>' +
    '<span><span class="num num--lg" id="pSum">' + num(sum()) + '</span>' +
    '<span class="caption"> / ' + num(sc.full) + '</span></span></div>' +
    pScoreBtns(state, editing) +
    '</div>';

  // 额外表现。走「发星星时刻」那一套：必须附一句话，每天最多 2 次。
  h += '<div class="card" style="display:flex;align-items:center;gap:10px;cursor:pointer" ' +
    'id="pBonus">' + pic('i-plus', 20, '', 'var(--orange-deep)') +
    '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px">' +
    '<span class="card-title">今天有额外表现</span>' +
    '<span class="caption">填一句话，加 1 分 · 每天最多 2 次</span></div>' +
    '<span class="chev">›</span></div>';

  h += '<p class="footnote footnote--left">' + pScoreFoot(state, sc, editing) + '</p>';

  v.innerHTML = h;

  $$('#view .daycell').forEach(b => b.addEventListener('click', () => {
    P_EDIT = false; S.day = b.dataset.day; S.month = null; render();
  }));
  $$('#view button[data-kid]').forEach(b => b.addEventListener('click', () => {
    P_EDIT = false; S.target = +b.dataset.kid; S.month = null; render();
  }));
  $$('#view .seg-item').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.seg === 'month') { P_EDIT = false; pGo('month'); }
  }));
  $$('#view .dim-row').forEach(el => el.addEventListener('click', () => pScoreTap(el)));
  const be = $('#pEdit');
  if (be) be.addEventListener('click', () => pScoreEdit());
  const bc = $('#pCancel');
  if (bc) bc.addEventListener('click', () => { P_EDIT = false; render(); });
  const bs = $('#pSave');
  if (bs) bs.addEventListener('click', () => pScoreSave());
  const bn = $('#pBonus');
  if (bn) bn.addEventListener('click', () => exploreSheet());
}

/* ------------------------------------------------ 打分页的四个状态标签 */
/* 四个标签说的是同一件事的两面：这天有没有分、现在还动不动得了。
   颜色只做区分（灰=还没轮到、琥珀=还能补、蓝=能改、红=锁死），
   判断全靠旁边那句话 —— 光靠颜色，红和琥珀在暖色板里分不开。 */
let P_EDIT = false;        // 打分页是不是停在「改」这一屏
const P_STATE_TAG = {
  unscored: ['未打', 'pill--gray'], backfill: ['补卡', 'pill--tag'],
  modify: ['修改', 'pill--blue'], overdue: ['超时', 'pill--warn'],
  locked: ['锁死', 'pill--gray'],
};
function pDeadlineText(s) {
  if (!s) return '';
  const p = s.slice(0, 10).split('-');
  return (+p[1]) + '月' + (+p[2]) + '日 ' + s.slice(11, 16);
}
function pStateSub(state, editing) {
  if (state === 'modify') return editing ? '改完按保存' : '打过了';
  if (state === 'unscored') return '还没打分';
  if (state === 'backfill') return '补卡';
  if (state === 'overdue') return '超时，锁死了';
  if (state === 'locked') return '已锁定';
  return '';
}
function pStateBand(state, sc, editing) {
  const t = P_STATE_TAG[state];
  const dl = pDeadlineText(sc.deadline);
  let tone = '', txt = '';
  if (state === 'unscored') {
    tone = ''; txt = '今天还没打分。' + (dl ? dl + ' 之前补上都算数，' : '') +
      '过点系统按满分补记，并从许愿池罚一笔星尘。';
  } else if (state === 'backfill') {
    tone = 'is-warn'; txt = '这天还空着，' + (dl ? dl + ' 之前还能补，' : '还能补，') +
      '过点系统按满分补记并从许愿池罚一笔星尘，之后就锁死了。';
  } else if (state === 'modify') {
    tone = 'is-info'; txt = editing
      ? '改完按保存才算数，按取消就退回刚才那样。'
      : '打过了，24 小时内还能改。先点下面的「修改」，改完按保存。';
  } else if (state === 'overdue') {
    tone = 'is-bad'; txt = esc(sc.reason || '过了第二天 12:00，这天锁死了') +
      '。要改只能走家长调整。';
  } else if (state === 'locked') {
    tone = ''; txt = esc(sc.reason || '这一天的记录已经锁定了');
  } else {
    return '';                       // 过渡日 / 未来的日子，走下面那条 notice
  }
  return '<div class="sband' + (tone ? ' ' + tone : '') + '">' +
    (t ? '<span class="pill ' + t[1] + '">' + t[0] + '</span>' : '') +
    '<span>' + txt + '</span></div>';
}
function pDimHint(state, editing) {
  if (state === 'unscored' || state === 'backfill') return '没做到的点一下';
  if (state === 'modify') return editing ? '改完按保存' : '点下面的「修改」才能改';
  return '这一天的记录已经锁定了';
}
function pScoreBtns(state, editing) {
  if (state === 'modify' && !editing) {
    return '<button type="button" class="btn btn--ghost" id="pEdit" style="margin-top:12px">修改</button>';
  }
  if (editing) {
    return '<div class="act-row" style="margin-top:12px">' +
      '<button type="button" class="btn btn--primary" style="flex:1" id="pSave">保存</button>' +
      '<button type="button" class="btn btn--ghost" style="flex:1" id="pCancel">取消</button></div>';
  }
  return '';
}
function pScoreFoot(state, sc, editing) {
  if (state === 'unscored' || state === 'backfill') {
    return '点一项记一项，不用保存' +
      (sc.deadline ? '　' + pDeadlineText(sc.deadline) + ' 前补上都算数' : '');
  }
  if (editing) return '改完按保存才算数，按取消就退回刚才那样';
  if (state === 'modify') return '24 小时内的修改会留一条记录，不删原始流水';
  return '锁死的这一天改不了，要改走家长调整';
}

/* 进「改」这一屏。取消不靠存一份快照，直接重拉服务端那一版 ——
   退回的样子必须是库里现在这样，不是进这一屏那一刻我记下的那样。 */
function pScoreEdit() {
  const s = S.score;
  if (!s) return;
  P_EDIT = true;
  render();
}

/* 点一下维度。两种走法：
     · 还没打分的日子（未打 / 补卡）：点一项立刻记一项，不用保存，
       因为那天本来就该赶紧补上，多加一道按钮只会拖。
     · 改这一屏：只改界面，等保存。改错了按取消就回来了。 */
let pScoreBusy = false;
async function pScoreTap(el) {
  const s = S.score;
  if (!s || pScoreBusy) return;
  const tapNow = s.state === 'unscored' || s.state === 'backfill';
  if (!tapNow && !s.editing) return;
  const d = s.dims.filter(x => x.code === el.dataset.code)[0];
  if (!d) return;
  d.value = d.value === 0 ? 1 : 0;
  pDimPaint(el, d);
  pScoreSum();
  if (!tapNow) return;                 // 改这一屏只在本地动，保存时才报
  pScoreBusy = true;
  try {
    await api('POST', '/api/score', { member_id: s.target, day: s.day,
      undone: s.dims.filter(x => x.value === 0).map(x => x.code) });
  } catch (e) {
    d.value = d.value === 0 ? 1 : 0;   // 界面上先亮着、后端其实没记上，
    pDimPaint(el, d);                  // 家长就再也发现不了这一天少了一分
    pScoreSum();
    err(e);
  } finally { pScoreBusy = false; }
}
function pScoreSum() {
  const st = $('#pSum');
  if (st) st.textContent = num(S.score.dims.reduce((a, x) => a + (x.value || 0), 0));
}

/* 保存这一屏的改动。保存不弹确认 —— 七项摆在这儿，改了哪几项一眼看得见，
   再弹一次「确定吗」只是多一次点击。 */
async function pScoreSave() {
  const s = S.score;
  if (!s || pScoreBusy) return;
  const undone = s.dims.filter(x => x.value === 0).map(x => x.code);
  pScoreBusy = true;
  try {
    await api('POST', '/api/score',
      { member_id: s.target, day: s.day, undone: undone });
    P_EDIT = false;
    toast(undone.length ? '改好了，扣掉 ' + undone.length + ' 项' : '改好了，满分');
    await render();
  } catch (e) { err(e); } finally { pScoreBusy = false; }
}

/* ---------------------------------------------------------------- 月度统计 */
/* 月历五态 + 一条自洽铁律：格子上的颜色与下面「本月小结」的三个数字
   必须是同一份数据算出来的。分值色和结论分开算，迟早会出现
   「图上有 5 个满格，下面写完美日 4 天」。 */
function pCalHTML(m, sel) {
  const ym = m.ym, Y = +ym.slice(0, 4), M = +ym.slice(5);
  const lead = (new Date(Y, M - 1, 1).getDay() + 6) % 7;   // 周一排第一列
  const today = todayStr();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  m.rows.forEach(r => cells.push(r));
  while (cells.length % 7) cells.push(null);

  /* 年月和翻月箭头就长在卡片标题这一行（左边），「点一格看当天七项」
     挪到同一行的右边 —— 跟孩子端那张月历一个长相。
     原来年月是卡片外面独立的一行，和标题、说明三层叠着，家长看到的是
     「9 月打分日历」下面又来一个「2026 年 9 月」，同一件事说两遍。 */
  let h = '<div class="card"><div class="cal-bar">' +
    '<span class="cal-nav">' +
    '<button type="button" data-mv="-1" aria-label="上个月">' + pic('i-chevron-left', 16) + '</button>' +
    '<span class="month">' + Y + ' 年 ' + M + ' 月</span>' +
    '<button type="button" data-mv="1"' + (ym >= ymOf(today) ? ' disabled' : '') +
    ' aria-label="下个月">' + pic('i-chevron-right-dead', 16) + '</button></span>' +
    '<span class="caption">点一格看当天七项</span></div>' +
    '<div class="cal-grid" style="margin-top:10px">' +
    CAL_WD.map(d => '<span class="cal-wd">' + d + '</span>').join('');
  cells.forEach(r => {
    if (!r) return h += '<span class="cal-blank"></span>';
    let st;
    if (r.future) st = 'future';
    else if (!r.scored) st = (r.transition ? 'trans' : 'none');
    else if (r.score >= r.full) st = 'full';
    else if (r.score > 0) st = 'part';
    else st = 'zero';
    const cls = 'cal-cell is-' + st + (r.day === today ? ' is-today' : '') +
      (r.day === sel ? ' is-cur' : '');
    // 未来的日子点不开，别给一个点了只会说「还没到」的按钮
    h += r.future
      ? '<span class="' + cls + '">' + (+r.day.slice(8)) + '</span>'
      : '<button type="button" class="' + cls + '" data-cd="' + r.day + '">' +
        (+r.day.slice(8)) + '</button>';
  });
  h += '</div>';
  h += '<div class="cal-legend" style="margin-top:12px;padding-top:10px;' +
    'border-top:1px solid var(--divider)">' +
    '<span><b style="background:var(--gold)"></b>满分</span>' +
    '<span><b style="background:var(--partial)"></b>部分</span>' +
    '<span><b style="border:1.5px dashed var(--dash)"></b>没打分</span>' +
    '<span><b style="background:var(--warn)"></b>0 分</span>' +
    '<span><b style="background:var(--future)"></b>未来</span></div>';
  h += '<div class="muted" style="margin-top:8px">虚线那几天是没打过分的，' +
    '不算进下面那个达成率。「0 分」和「没打分」不是一件事。</div></div>';
  return h;
}

async function renderAdminMonth(v) {
  const kids = KIDS();
  if (!kids.length) {
    v.innerHTML = pHead({ title: '打分', sub: '还没有孩子账号' }) +
      '<div class="card"><div class="empty">先开一个孩子的账号</div></div>';
    return;
  }
  const target = kidId();
  const day = S.day || todayStr();
  const ym = S.month || ymOf(day);
  const sc = await pg('/api/score/day?member_id=' + target + '&day=' + day,
    { scored: false, score: 0, full: 7 });
  const m = await monthData(target, ym);
  CAL = m;

  const total = m.total;
  const today = todayStr();
  const elapsed = m.rows.filter(r => r.day <= today).length;
  const perfect = m.rows.filter(r => r.scored && r.score >= r.full).length;

  let h = pScoreHead('打分', target, day,
    (sc.scored ? num(sc.score) : '未打') + (sc.scored ? '/' + num(sc.full) : ''),
    pStateSub(sc.state || (sc.scored ? 'modify' : 'unscored'), false));
  h += '<div class="seg">' +
    '<button type="button" class="seg-item" data-seg="score">今日打分</button>' +
    '<button type="button" class="seg-item on" data-seg="month">月度统计</button></div>';

  h += '<div id="pCalBox">' + pCalHTML(m, day) + '</div>';

  h += '<div class="card"><div class="sec-head">' +
    '<span class="card-title">本月小结</span>' +
    '<span class="caption">' + esc(m.rows.length ? m.rows[0].day.slice(5) : '') + ' - ' +
    esc(m.rows.length ? m.rows[m.rows.length - 1].day.slice(5) : '') + '</span></div>' +
    '<div class="kpi-row" style="margin-top:12px">' +
    '<div class="kpi"><span class="k">本月固定分</span><span class="v">' +
    num(total.score) + ' / ' + num(total.full) + '</span></div>' +
    '<div class="kpi"><span class="k">完美日</span><span class="v">' + perfect + ' 天</span></div>' +
    '<div class="kpi"><span class="k">打过分的天</span><span class="v">' +
    num(total.days) + ' / ' + elapsed + '</span></div></div></div>';

  h += '<p class="footnote footnote--left">图上的满格数就是「完美日」天数，' +
    '非虚线格数就是「打过分的天」—— 两处对不上说明有一边算错了。</p>';

  v.innerHTML = h;

  bindCal(target, day, pCalHTML);
  $$('#view button[data-kid]').forEach(b => b.addEventListener('click', () => {
    S.target = +b.dataset.kid; S.month = null; render();
  }));
  $$('#view .seg-item').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.seg === 'score') pGo('score');
  }));
}

/* ================================================================== 家长端 · 宝箱 */
/* 家长看宝箱，看的不是「他能拿什么」，而是「这周的门槛在哪一档」。
   学生端那边一屏是开箱与集卡；这一屏只有三样东西：本周攒到哪一格、
   免费那条线到哪、直购那条线多少钱，最后一张七档阶梯表。

   概率只写在**这一页**，别处一句都不写。这句话是硬红线：
   概率散在多处，孩子就会拿着商店里那句去问你为什么没开出来。 */
async function renderParentChest(v) {
  const kids = KIDS();
  if (!kids.length) {
    v.innerHTML = pHead({ title: '宝箱', sub: '还没有孩子账号', back: 'me' }) +
      '<div class="card"><div class="empty">先开一个孩子的账号</div></div>';
    return;
  }
  const target = kidId();
  // 家长端调 /api/boxes 必须带上 member_id：后端 target_child() 对家长
  // 是要显式指定孩子的，不传就直接报「请指定要操作的孩子」——整屏白掉。
  const b = await api('GET', '/api/boxes?member_id=' + target);
  const shop = await pg('/api/shop?member_id=' + target, { boxes: [] });
  const tiers = b.tiers || [];
  const cyc = b.cycle || null;
  const fixed = cyc ? cyc.fixed_score : 0;
  const cur = cyc && cyc.tier ? cyc.tier : null;
  const next = cyc ? cyc.next_tier : null;
  const cycName = cyc ? (cyc.start_date + ' 到 ' + cyc.end_date) : '这个周期还没开';

  let h = pHead({
    title: '宝箱', small: true, back: 'me',
    sub: cycName,
    right: '<span class="pill pill--gold">' + esc(cur ? cur.name : '还没到第一档') + '</span>',
  });

  if (kids.length > 1) {
    h += '<div class="seg">' + kids.map(k =>
      '<button type="button" class="seg-item' + (k.id === target ? ' on' : '') +
      '" data-kid="' + k.id + '">' + esc(k.name) + '</button>').join('') + '</div>';
  }

  // 周期进度走羊皮纸重点卡：和「正在玩」同一语义（正在攒的那一格）
  h += '<div class="card--parch"><div class="sec-head">' +
    '<span class="card-title">本周固定分</span>' +
    '<span><span class="num num--md">' + num(fixed) + '</span>' +
    '<span class="caption--warm" style="font-size:12px"> / ' +
    num(tiers.length ? tiers[tiers.length - 1].threshold : 49) + '</span></span></div>' +
    '<div class="slots" style="margin-top:12px">' + tiers.map((t, i) => {
      const prev = i ? tiers[i - 1].threshold : 0;
      const cls = fixed >= t.threshold ? 'is-full' : (fixed > prev ? 'is-half' : '');
      return '<i' + (cls ? ' class="' + cls + '"' : '') + '></i>';
    }).join('') + '</div>' +
    '<span class="caption--warm" style="display:block;margin-top:10px">' +
    esc(cur ? '已拿 ' + cur.name : '本周还没拿到箱子') +
    (next ? ' · 再 ' + num(next.need) + ' 分就能开 ' + esc(next.name) : ' · 已经拿到最好的了') +
    '</span></div>';

  h += '<div class="grid2">' +
    '<div class="card"><span class="caption--warm" style="font-size:10px">达标免费发</span>' +
    '<div class="num num--sm" style="margin-top:4px">' +
    esc(cur ? cur.name : '还没到') + '</div>' +
    '<span class="caption" style="display:block;margin-top:4px">' +
    (cur ? '到 ' + num(cur.threshold) + ' 分直接发' : '先攒够 ' +
      num(tiers.length ? tiers[0].threshold : 7) + ' 分') + '</span></div>' +
    '<div class="card"><span class="caption--warm" style="font-size:10px">星尘直购</span>' +
    '<div class="num num--sm" style="margin-top:4px;color:var(--orange-deep);font-size:17px">' +
    ((shop.boxes || []).map(x => num(x.price)).join(' / ') || '—') + '</div>' +
    '<span class="caption" style="display:block;margin-top:4px">' +
    ((shop.boxes || []).map(x => esc(x.name.replace('箱', ''))).join(' / ') || '店里没挂') +
    ' · 每周期 ' + num(b.purchase_limit) + ' 次，已买 ' + num(b.purchase_used) + '</span></div>' +
    '</div>';

  h += '<div class="stack"><div class="sec-head"><span class="sec-title">七档阶梯</span>' +
    '<span class="sec-count">概率只在这里写</span></div>' +
    '<div class="card card--flush">' +
    '<div class="tbl-head"><span class="caption c-name">宝箱 / 分</span>' +
    '<span class="caption c-a">保底</span>' +
    '<span class="caption c-b">随机件</span></div>' +
    tiers.map(t => {
      const rate = Math.round((t.random_rate || 0) * 100);
      const extra = rate ? rate + '% ' + (rate >= 40 ? '随机件' : '惊喜') : '无随机件';
      return '<div class="tbl-row' + (cur && cur.tier === t.tier ? ' is-cur' : '') + '">' +
        '<span class="c-name"><b>' + esc(t.name) + '</b><span>' + num(t.threshold) +
        ' 分</span></span>' +
        '<span class="caption--warm c-a">' + num(t.tickets) + ' 张娱乐券' +
        (t.card_count ? ' · 普通卡 ' + num(t.card_count) : '') + '</span>' +
        '<span class="caption--warm c-b"' + (rate ? ' style="color:var(--orange-deep)"' : '') +
        '>' + extra + '</span></div>';
    }).join('') + '</div></div>';

  h += '<p class="footnote footnote--left">木箱、铜箱、银箱没有随机件 —— ' +
    '这三档是每天那七分的直接回报，不该掺运气。直购箱不含随机件、' +
    '也开不出传说与钻石级；直购前置是本周还没拿到那一档。</p>';

  v.innerHTML = h;
  $$('#view button[data-kid]').forEach(b2 => b2.addEventListener('click', () => {
    S.target = +b2.dataset.kid; render();
  }));
  $$('#view [data-back]').forEach(b2 => b2.addEventListener('click', () => pGo(b2.dataset.back)));
}

/* ================================================================== 家长端 · 商店 */
/* 孩子那一屏是「我要买」，家长这一屏是「这东西值多少钱」。
   同一批商品，家长侧多一个折合金额（1 星尘 = 0.5 元）——
   家长批不批一张券，靠的是这句话。

   这一页不含随机件（概率只写在宝箱页），也不卖卡。 */
let P_SHOPSEG = 'ticket';

async function renderParentShop(v) {
  const kids = KIDS();
  if (!kids.length) {
    v.innerHTML = pHead({ title: '券商店', small: true, back: 'me', sub: '还没有孩子账号' }) +
      '<div class="card"><div class="empty">先开一个孩子的账号</div></div>';
    return;
  }
  const target = kidId();
  const shop = await api('GET', '/api/shop?member_id=' + target);
  const cash = await pg('/api/cash', { rate: 0.5, cap: 60, used: 0, hold: 0, left: 60 });
  const rate = cash.rate || 0.5;
  const yuan = st => '¥' + num(Math.round(st * rate * 100) / 100);
  const seg = P_SHOPSEG;
  const tickets = shop.tickets || [];
  const boxes = shop.boxes || [];

  let h = pHead({
    title: '券商店', small: true, back: 'me', sub: '家长侧 · 显示折合金额',
    right: '<span class="num num--lg" style="font-size:15px">' + num(shop.stardust) + ' 星尘</span>',
  });

  h += '<div class="seg">' +
    '<button type="button" class="seg-item' + (seg === 'ticket' ? ' on' : '') +
    '" data-sseg="ticket">券 ' + tickets.length + '</button>' +
    '<button type="button" class="seg-item' + (seg === 'box' ? ' on' : '') +
    '" data-sseg="box">箱子 ' + boxes.length + '</button></div>';

  if (seg === 'ticket') {
    h += '<div class="stack">' + (tickets.length ? tickets.map(t =>
      '<div class="goods"><span class="goods-ic">' + pic(t.code === 'ticket_fun'
        ? 'i-hourglass' : 'i-coupon', 26) + '</span>' +
      '<div class="goods-body"><span class="goods-name">' + esc(t.name) +
      (t.weekly_limit ? ' <span class="pill pill--gray">每周 ' + num(t.weekly_limit) +
        ' 张</span>' : ' <span class="pill pill--gray">不限量</span>') + '</span>' +
      '<span class="goods-desc">' + esc(t.desc || '') +
      // 券表里 shelf_life_days 是空的（NULL=永久）。写「有效期 0 天」会让家长
      // 以为手上那几张今晚就没了 —— 空值在这儿必须翻成一句真话。
      (t.shelf_life_days ? '　有效期 ' + num(t.shelf_life_days) + ' 天，到期折半转星尘'
        : '　不设有效期') + '</span>' +
      '<span class="goods-desc">手上 ' + num(t.owned) + ' 张' +
      (t.bought_this_cycle ? '　这周买过 ' + num(t.bought_this_cycle) + ' 张' : '') +
      '</span></div>' +
      '<span class="goods-price"><span class="p">' + num(t.price) + ' 星尘</span>' +
      '<span class="c">≈ ' + yuan(t.price) + '</span></span></div>').join('')
      : '<div class="card"><div class="empty">店里没有上架的券</div></div>') + '</div>';
  } else {
    h += '<div class="stack">' + (boxes.length ? boxes.map(x =>
      '<div class="goods"><span class="goods-ic">' + pic('i-chest', 26) + '</span>' +
      '<div class="goods-body"><span class="goods-name">' + esc(x.name) +
      ' <span class="pill pill--gray">打出来要 ' + num(x.threshold) + ' 分</span></span>' +
      '<span class="goods-desc">' + num(x.tickets) + ' 张娱乐券' +
      (x.card_count ? ' · 普通卡 ' + num(x.card_count) : '') +
      '　不含随机件</span>' +
      '<span class="goods-desc">每周期 ' + num(x.weekly_limit) + ' 次，本周已买 ' +
      num(x.bought_this_cycle) + '</span></div>' +
      '<span class="goods-price"><span class="p">' + num(x.price) + ' 星尘</span>' +
      '<span class="c">≈ ' + yuan(x.price) + '</span></span></div>').join('')
      : '<div class="card"><div class="empty">店里没有上架的箱子</div></div>') + '</div>';
  }

  h += '<p class="caption">本页不含随机件（概率只写在宝箱页）；' +
    '随机件只在宝箱里出；卡也不卖 —— 卡是攒出来的，摆上货架就不值钱了。' +
    '折合金额按 1 星尘 = ' + num(rate) + ' 元算。</p>';

  // 零花钱兑换的额度条。在审的那几笔也占额度，所以写的是「已用 + 在审」。
  const used = cash.used || 0, hold = cash.hold || 0, cap = cash.cap || 60;
  h += '<div class="card" style="display:flex;flex-direction:column;gap:8px">' +
    '<div class="sec-head"><span class="card-title">零花钱兑换</span>' +
    '<span class="sec-count">本月 ' + num(used) + ' / ' + num(cap) + ' 星尘</span></div>' +
    '<div class="bar bar--orange" style="height:8px"><i style="width:' +
    Math.min(100, Math.round((used + hold) / (cap || 1) * 100)) + '%"></i></div>' +
    '<span class="caption--warm">已换 ' + yuan(used) + ' · 还能换 ' + yuan(cash.left) +
    (hold ? '　' + num(hold) + ' 星尘在审（在审也占额度）' : '') + '</span>' +
    '<span class="caption">1 星尘 = ' + num(rate) + ' 元。审批在「审核」页，' +
    '同意就等于发放，掏钱的时候顺手把现金给他。</span></div>';

  v.innerHTML = h;
  $$('#view .seg-item').forEach(b2 => b2.addEventListener('click', () => {
    if (b2.dataset.sseg === seg) return;
    P_SHOPSEG = b2.dataset.sseg; render();
  }));
  $$('#view [data-back]').forEach(b2 => b2.addEventListener('click', () => pGo(b2.dataset.back)));
}

/* ================================================================== 家长端 · 我的 */
/* 家长这一屏没有分数、没有等级、没有徽章墙 —— 他不在游戏里。
   一张身份卡、一条自己的记录、一串家里的事、一个退出。
   「我的记录」查的是**家长自己**做过什么（我打的分、我审的、我发的），
   和首页那条「最近发生」（全家混排）是同一条流水，只是筛选条件不同。 */
async function renderAdminMe(v) {
  const kids = KIDS();
  const n = kids.length;
  const role = S.me.is_admin ? '管理员' : (S.me.role === 'parent' ? '家长' : '成员');
  const sub = [role, '家里 ' + n + ' 个孩子', '不进计分'].filter(Boolean).join(' · ');

  let h = '<div class="card--parch" style="display:flex;align-items:center;gap:14px">' +
    pAvatar(S.me, 62, 0) +
    '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:4px">' +
    '<div style="display:flex;align-items:center;gap:8px">' +
    '<span style="font-size:18px;font-weight:700;color:var(--ink-title)">' + esc(S.me.name) +
    '</span><span class="badge-pilot">领航员</span></div>' +
    '<span class="caption--warm">' + esc(sub) + '</span></div></div>';

  // 「我的」这一组只装跟**账号**有关的三件事：我看过什么、家里有谁、我的密码。
  // 家人账号与改密码原先躲在「更多」里，那是一条和设置页撞车的死路。
  const mine = [
    ['i-memo', '我的记录', '我打过的分、我审过的、我发过的', 'mine'],
    ['i-nav-user', '家人账号', S.me.is_admin ? '开通账号、重置任何人的密码'
      : '重置孩子的密码，开通账号找管理员', 'members'],
    ['i-nav-stamp', '改我的密码', '账号 ' + (S.me.username || '—'), 'chpw'],
  ];
  h += '<div class="stack--sm" style="display:flex;flex-direction:column;gap:8px">' +
    '<span class="sec-title">我的</span>' +
    '<div class="card card--tight" style="padding:6px">' +
    mine.map(r => '<div class="row" data-act="' + r[3] + '">' + pic(r[0], 20) +
      '<div class="row-body"><span class="row-title">' + esc(r[1]) + '</span>' +
      '<span class="row-sub">' + esc(r[2]) + '</span></div>' +
      '<span class="chev">›</span></div>').join('') + '</div></div>';

  const rows = [
    ['i-family', '家庭页', '全家能量 · 许愿池 · 成员', 'family'],
    ['i-chest', '宝箱与券', '七档门槛 · 直购价 · 概率', 'chest'],
    ['i-shop', '商店与汇率', '六种券 · 折合金额', 'shop'],
    ['i-wishpool', '心愿与许愿池', '两个孩子的愿望各走到哪一步', 'wish'],
  ];
  h += '<div class="stack--sm" style="display:flex;flex-direction:column;gap:8px">' +
    '<span class="sec-title">家里的事</span>' +
    '<div class="card card--tight" style="padding:6px">' +
    rows.map(r => '<div class="row" data-go="' + r[3] + '">' + pic(r[0], 20) +
      '<div class="row-body"><span class="row-title">' + esc(r[1]) + '</span>' +
      '<span class="row-sub">' + esc(r[2]) + '</span></div>' +
      '<span class="chev">›</span></div>').join('') +
    '<div class="row" data-go="settings">' + pic('i-gear', 20) +
    '<div class="row-body"><span class="row-title">设置</span>' +
    '<span class="row-sub">价格 · 门槛 · 额度，改完就生效</span></div>' +
    '<span class="chev">›</span></div></div></div>';

  // 备份单独一行，不并进「家里的事」：它改的不是家里的规矩，是「万一没了
  // 还能不能找回来」。摆在最底下，跟退出登录隔开。
  h += '<div class="card card--tight" style="padding:6px">' +
    '<div class="row" data-act="ops">' + pic('i-log-system', 20) +
    '<div class="row-body"><span class="row-title">备份与导出</span>' +
    '<span class="row-sub">数据库快照 · 导出一份 JSON</span></div>' +
    '<span class="chev">›</span></div></div>';

  h += '<button class="btn btn--block btn--quiet" id="pLogout">退出登录</button>';

  // 版本号与仓库地址。原来挂在设置页最底下，那一页又套在两层弹层里，
  // 出问题要找「跑的是哪一版」时得先记得它在哪儿。挪到「我的」页脚，
  // 不用翻菜单。
  h += '<div class="p-about">' +
    '<div class="p-about-line">家庭积分 v' + esc(S.data.version || '') + '</div>' +
    '<a class="p-about-line p-about-link" href="https://github.com/WW-Ares/FamilyPoints"' +
    ' target="_blank" rel="noopener">github.com/WW-Ares/FamilyPoints</a></div>';

  v.innerHTML = h;
  $$('#view [data-go]').forEach(el => el.addEventListener('click', () => pGo(el.dataset.go)));
  $('#pLogout').addEventListener('click', () => logoutNow());
  $$('#view [data-act]').forEach(el => el.addEventListener('click', () => {
    const k = el.dataset.act;
    if (k === 'members') return membersSheet();
    if (k === 'chpw') return changePwSheet();
    if (k === 'ops') return opsSheet();
    if (k === 'mine') {
      LOG_FILTER.mine = true; LOG_FILTER.group = ''; LOG_FILTER.member_id = '';
      pGo('logs');
    }
  }));
}

/* ================================================================== 家长端 · 家庭页 */
/* 一家人的一张合影。三个数字就够了：这周全家一共攒了多少、
   许愿池走到哪、谁在这个家里。
   全家能量**只做汇总，不做排名** —— 下面那行写明各自多少，是让他知道
   这 59 分是怎么来的，不是让他比。 */
async function renderFamily(v) {
  const ov = await pg('/api/kids/overview', { items: [] });
  const pool = await pg('/api/pool', { pool: null, entries: [], logs: [] });
  const kids = ov.items || [];
  const parents = PARENTS();
  const total = kids.reduce((a, k) => a + ((k.cycle && k.cycle.energy) || 0), 0);
  const rate = 0.5;

  let h = pHead({
    title: '我们家', small: true, back: 'me',
    sub: S.members.map(m => m.name).join(' · '),
    right: '<span class="pill">' + S.members.length + ' 人</span>',
  });

  h += '<div class="card--parch"><span class="card-title">本周全家能量</span>' +
    '<div class="hero-num" style="margin-top:8px">' +
    '<span class="num num--xl">' + num(total) + '</span><span class="u">分</span></div>' +
    '<span class="caption--warm" style="display:block;margin-top:8px">' +
    (kids.length ? kids.map(k => esc(k.name) + ' ' + num((k.cycle && k.cycle.energy) || 0))
      .join(' · ') : '还没有孩子账号') +
    '（本周固定分之和，不做排名）</span></div>';

  const p = pool.pool;
  h += '<div class="card"><div class="sec-head">' +
    '<span class="card-title">全家许愿池</span>' +
    '<span class="caption--warm" style="font-size:11px">' +
    esc(p ? p.title + (p.target_desc ? ' · ' + p.target_desc : '') : '还没有目标') +
    '</span></div>';
  if (p) {
    const saved = p.collected_cash || (p.collected_stardust || 0) * rate;
    const target = (p.target_stardust || 0) * rate;
    // 来源明细：按 entry.source 归堆，系统注入的那几笔单独算
    const src = {};
    (pool.entries || []).forEach(e => {
      src[e.source] = (src[e.source] || 0) + ((e.cash || 0) || (e.stardust || 0) * rate);
    });
    const logs = (pool.logs || []).reduce((a, x) => a + (x.counted ? (x.stardust || 0) * rate : 0), 0);
    const nameOf = { fine: '违约金', selfpay: '孩子投币', task: '任务扣款', penalty: '忘打卡注入' };
    const parts = Object.keys(src).map(k => (nameOf[k] || k) + ' ¥' + num(Math.round(src[k] * 100) / 100));
    if (logs) parts.push('忘打卡注入 ¥' + num(Math.round(logs * 100) / 100));
    h += '<div class="bar bar--orange" style="margin-top:12px"><i style="width:' +
      Math.min(100, Math.round(p.percent || 0)) + '%"></i></div>' +
      '<span class="sec-link" style="display:block;margin-top:10px">已攒 ¥' +
      num(Math.round(saved * 100) / 100) + ' · 还差 ¥' +
      num(Math.round(Math.max(0, target - saved) * 100) / 100) + '</span>' +
      '<p class="caption" style="margin:8px 0 0">' +
      (parts.length ? '来源 · ' + esc(parts.join(' ＋ ')) : '还没有进账') +
      '　（不清零、不退回）</p>';
  } else {
    h += '<div class="empty">还没有全家目标</div>' +
      '<button class="btn btn--ghost wide" id="pPool">去设一个</button>';
  }
  h += '</div>';

  h += '<div class="card" style="display:flex;flex-direction:column;gap:12px">' +
    '<span class="card-title">家庭成员</span>';
  parents.forEach((m, i) => {
    h += '<div style="display:flex;align-items:center;gap:10px">' +
      pAvatar(m, 36, i) +
      '<div style="flex:1;min-width:0"><span class="card-title">' + esc(m.name) + '</span></div>' +
      '<span class="caption--warm" style="font-size:11px">' +
      (m.is_admin ? '管理员 · 不进计分' : '家长 · 只打分') + '</span></div>';
  });
  kids.forEach((k, i) => {
    h += '<div style="display:flex;align-items:center;gap:10px;cursor:pointer" data-kid="' +
      k.member_id + '">' + pAvatar(k, 36, i) +
      '<div style="flex:1;min-width:0"><span class="card-title">' + esc(k.name) + '</span></div>' +
      '<span class="caption--warm" style="font-size:11px">孩子 · 本周 ' +
      num((k.cycle && k.cycle.energy) || 0) + ' 分</span>' +
      '<span class="chev">›</span></div>';
  });
  h += '</div>';

  // 这一条不是「忘了就算」，是「大人漏了，不让孩子少一天分」。摆在这儿，
  // 因为家长第一次看见它会问「系统凭什么替我记满分」。
  h += '<div class="card"><span class="card-title">家长忘打卡</span>' +
    '<p class="caption" style="margin:8px 0 0;line-height:1.6">' +
    '次日 12:00 后仍空白 → 系统自动按满分记这一天，并按自然日注入 100 星尘到许愿池' +
    '（当天只注入一次，必留日志）。起用日当天和之前的日子不补、不罚。' +
    '这是大人漏了，不是孩子没做到 —— 所以不扣分、也不写进孩子的记录里。</p></div>';

  v.innerHTML = h;
  $$('#view [data-back]').forEach(b => b.addEventListener('click', () => pGo(b.dataset.back)));
  $$('#view [data-kid]').forEach(el => el.addEventListener('click', () => {
    S.kidId = +el.dataset.kid; pGo('kid');
  }));
  // 这一颗原来开的是「更多」那条小清单 —— 家长点「去设一个」想设的是许愿池，
  // 弹出来的却是一张入口表，还得再找一遍。直接开许愿池。
  const pb = $('#pPool');
  if (pb) pb.addEventListener('click', () => wishSheet());
}

/* ================================================================== 家长端 · 心愿与许愿池 */
/* 心愿详情。整条心愿里唯一不可改的是「条件原话」—— 孩子知道他改不了，
   才会认真许。所以那句话走羊皮纸，和别的字段分开。

   顺序是：条件原话 → 进度 → 他交上来的那一条（确认区）→ 别忘了。
   确认区必须在「别忘了」**之前**：提醒事项永远压最底，
   否则家长滑到底还以为没事，其实有一件事等他点。 */
let P_WISHKID = null;      // 心愿列表按孩子看

function wishOf(items, id) { return items.filter(x => x.id === id)[0]; }

function pWishConds(x) {
  const p = x.progress || {};
  const subs = p.subs || [];
  const row = (done, text, right, note) =>
    '<div style="display:flex;gap:8px;align-items:flex-start">' +
    pic(done ? 'i-check' : 'i-check-off', 14, '', done ? 'var(--ok)' : 'var(--ink-line)') +
    '<div style="flex:1;min-width:0"><span style="font-size:11px;line-height:1.5' +
    (done ? '' : ';color:var(--ink-2)') + '">' + esc(text) + '</span>' +
    (right || note ? '<span class="caption" style="display:block">' +
      esc([right, note].filter(Boolean).join(' · ')) + '</span>' : '') +
    '</div></div>';
  if (subs.length) {
    return subs.map(s => row(s.done, s.text,
      s.percent == null ? (s.manual ? '靠人判' : '—') : s.percent + '%',
      s.pending ? '他交了，等你确认' : (s.rejected ? '上一次没通过：' + (s.reject_note || '')
        : (s.last_reject_note || '')))).join('');
  }
  if (p.manual) return row(p.done, p.text || '', '', p.where || '');
  return row(!!p.done, p.text || '', p.percent == null ? '' : p.percent + '%', p.where || '');
}

async function renderParentWish(v) {
  const kids = KIDS();
  if (!kids.length) {
    v.innerHTML = pHead({ title: '心愿与许愿池', small: true, back: 'me', sub: '还没有孩子账号' }) +
      '<div class="card"><div class="empty">先开一个孩子的账号</div></div>';
    return;
  }
  const kid = P_WISHKID || kidId();
  const r = await Promise.all([
    pg('/api/wishes?member_id=' + kid, { items: [], limit: 0, pending_limit: 3 }),
    pg('/api/wishes/pending', { items: [] }),
    pg('/api/wishes/submissions', { items: [] }),
    pg('/api/pool', { pool: null, entries: [], logs: [] }),
  ]);
  const wishAll = r[0], pend = r[1], subs = r[2], pool = r[3];
  const items = wishAll.items || [];
  const mine = items.filter(w => w.status !== 'cancelled');
  const w = S.wishId ? wishOf(mine, S.wishId) : null;

  /* ---------------------------------------------------------- 列表 */
  if (!w) {
    let h = pHead({
      title: '心愿与许愿池', small: true, back: 'me',
      sub: memberName(kid) + '　进行中最多 ' + num(wishAll.limit) + ' 个',
      right: kids.length > 1 ? '<span class="kid-switch">' + kids.map(k =>
        '<button type="button" data-kid="' + k.id + '"' +
        (k.id === kid ? ' class="on"' : '') + '>' + esc(k.name) + '</button>').join('') +
        '</span>' : '',
    });

    const p = pool.pool;
    h += '<div class="card"><div class="sec-head"><span class="card-title">全家许愿池</span>' +
      '<span class="sec-count">' + esc(p ? p.title : '还没有目标') + '</span></div>' +
      (p ? '<div class="bar bar--orange" style="margin-top:10px"><i style="width:' +
        Math.min(100, Math.round(p.percent || 0)) + '%"></i></div>' +
        '<span class="caption--warm" style="display:block;margin-top:8px">已攒 ' +
        num(p.collected_stardust) + ' / ' + num(p.target_stardust) + ' 星尘</span>'
        : '<div class="empty">还没有全家目标</div>') + '</div>';

    const pendMine = (pend.items || []).filter(x => x.member_id === kid);
    h += '<div class="stack"><div class="sec-head"><span class="sec-title">心愿</span>' +
      '<span class="sec-count">' + mine.length + ' 条</span></div>';
    if (!mine.length) h += '<div class="card"><div class="empty">还没有许下的愿</div></div>';
    mine.forEach(x => {
      const st = x.status === 'wished' ? '等你定条件'
        : (x.status === 'achieved' ? '已达成' : '进行中');
      h += '<div class="card" style="cursor:pointer" data-wish="' + x.id + '">' +
        '<div class="sec-head">' + pic('i-wish', 20, '', 'var(--orange)') +
        '<span class="card-title" style="flex:1;min-width:0">' + esc(x.title) + '</span>' +
        '<span class="pill ' + (x.status === 'achieved' ? 'pill--gray' : 'pill--purple') + '">' +
        esc(st) + '</span></div>' +
        '<span class="caption--warm" style="display:block;margin-top:6px">' +
        esc(wishCondText(x) || '条件还没定') + '</span>' +
        (x.progress && x.progress.known
          ? '<div class="bar bar--orange" style="margin-top:8px"><i style="width:' +
            Math.min(100, x.progress.percent || 0) + '%"></i></div>' : '') +
        '</div>';
    });
    h += '</div>';

    if (pendMine.length) {
      h += '<div class="stack"><div class="sec-head">' +
        '<span class="sec-title">挂着等定条件</span>' +
        '<span class="sec-count">不定条件它就不算进度</span></div>' +
        pendMine.map(x => '<div class="card"><div class="sec-head">' +
          pic('i-wish', 20, '', 'var(--ink-3)') +
          '<span class="card-title" style="flex:1;min-width:0">' + esc(x.title) + '</span>' +
          '<button class="btn btn--primary btn--sm" data-td="wcfg" data-id="' + x.id +
          '">定条件</button></div>' +
          '<span class="caption" style="display:block;margin-top:6px">挂起 ' +
          holdDays(x.created_at) + ' 天　' + esc(x.reward_desc || '') + '</span></div>').join('') +
        '</div>';
    }

    v.innerHTML = h;
    bindTodoActions({ pendW: pend, subs: { items: subs.items }, items: [], cash: { items: [] } });
    $$('#view [data-wish]').forEach(el => el.addEventListener('click', () => {
      S.wishId = +el.dataset.wish; render();
    }));
    $$('#view [data-kid]').forEach(el => el.addEventListener('click', () => {
      P_WISHKID = +el.dataset.kid; S.target = +el.dataset.kid; S.wishId = null; render();
    }));
    $$('#view [data-back]').forEach(el => el.addEventListener('click', () => pGo(el.dataset.back)));
    return;
  }

  /* ---------------------------------------------------------- 详情 */
  const p = w.progress || {};
  const by = w.configured_by ? memberName(w.configured_by) : '';
  const setAt = String(w.configured_at || '').slice(5, 16);
  const claims = (subs.items || []).filter(c => c.wish_id === w.id);
  const subs2 = p.subs || [];
  const doneN = subs2.filter(s => s.done).length;
  const needN = p.key === 'any' ? (p.need || subs2.length || 1) : 1;
  const stardustSub = subs2.filter(s => s.key === 'stardust')[0];
  const paid = stardustSub && stardustSub.done ? stardustSub.target : 0;

  let h = pHead({
    title: memberName(w.member_id) + '的心愿', small: true, back: 'wish',
    sub: (setAt ? setAt + ' 点亮' : '还没点亮') + ' · ' +
      (w.status === 'achieved' ? '已达成' : '还在攒'),
    right: '<span class="pill pill--purple">' +
      (w.status === 'achieved' ? '已达成' : '进行中') + '</span>',
  });

  // 条件原话：点亮即锁死。这里是整条心愿唯一不可改的一句话
  h += '<div class="card--parch"><span class="caption--warm" style="font-size:10px">' +
    '条件原话</span>' +
    '<p style="margin:6px 0 0;font-size:15px;font-weight:500;line-height:1.5;' +
    'color:var(--ink-title)">' + esc(wishCondText(w)) + '</p>' +
    '<span class="caption" style="display:block;margin-top:8px">' +
    (by ? esc(by) + ' ' + esc(setAt) + ' 定的 · ' : '') +
    '点亮即锁死条件，之后不能改</span></div>';

  h += '<div class="card"><div class="sec-head"><span class="card-title">进度</span>' +
    '<span class="sec-count">' + (p.key === 'any'
      ? '做到 ' + doneN + ' 条 ÷ 要 ' + needN + ' 条'
      : (p.manual ? '靠人判' : (p.percent == null ? '—' : p.percent + '%'))) +
    '</span></div>' +
    (p.known && !p.manual
      ? '<div class="bar bar--orange" style="margin-top:12px"><i style="width:' +
        Math.min(100, p.percent || 0) + '%"></i></div>' : '') +
    '<div style="display:flex;flex-direction:column;gap:10px;margin-top:12px">' +
    (p.known ? pWishConds(w) : '<span class="caption">条件还没定，进度还算不了</span>') +
    '</div></div>';

  // 他交上来的那一条：确认和驳回是同一件事的两面，摆在一起
  claims.forEach(c => {
    h += '<div class="card" style="display:flex;flex-direction:column;gap:10px">' +
      '<span class="caption">自己写的那条 · ' + esc(memberName(w.member_id)) + ' 已交</span>' +
      '<p style="margin:0;font-size:12px;line-height:1.5">「' +
      esc(c.cond_text || c.cond_key) + '」</p>' +
      (c.note ? '<span class="caption">他说：' + esc(c.note) + '</span>' : '') +
      '<span class="caption">' + esc(String(c.created_at || '').slice(5, 16)) + ' 提交</span>' +
      '<div class="act-row">' +
      '<button class="btn btn--primary" style="flex:1" data-wclaim-ok="' + c.id +
      '">确认做到了</button>' +
      '<button class="btn btn--ghost" style="flex:1" data-wclaim-no="' + c.id +
      '">说不算 · 要写理由</button></div></div>';
  });

  // 别忘了：压最底
  h += '<div class="card card--soft"><span class="card-title">别忘了</span>' +
    '<div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">' +
    '<span class="caption--warm" style="font-size:11px">想要什么 · ' + esc(w.title) + '</span>' +
    (w.price_note ? '<span class="caption--warm" style="font-size:11px">值多少钱 · ' +
      esc(w.price_note) + '</span>' : '') +
    '<span class="caption">已付星尘 · ' + num(paid) +
    (w.selfpay_stardust
      ? '（要自付 ' + num(w.selfpay_stardust) + ' 星尘，这一步得他自己点「付掉」，' +
        '余额够也只算「能付」）' : '') + '</span></div></div>';

  v.innerHTML = h;
  $$('#view [data-back]').forEach(el => el.addEventListener('click', () => {
    if (el.dataset.back === 'wish') { S.wishId = null; render(); return; }
    pGo(el.dataset.back);
  }));
  $$('#view button[data-wclaim-ok]').forEach(b => b.addEventListener('click', async () => {
    askSheet({
      title: '这一条算做到了',
      hint: '这一条计入且不能收回；驳回要写清差在哪',
      ok: '确认做到了',
    }, async () => {
      try {
        const rr = await api('POST', '/api/wishes/claims/' + b.dataset.wclaimOk, { approve: true });
        closeSheet();
        toast(rr && rr.done ? '确认了，这条心愿够了' : '确认了这一条');
        await render();
      } catch (e) { err(e); }
    });
  }));
  $$('#view button[data-wclaim-no]').forEach(b => b.addEventListener('click', () => {
    pRejectSheet({
      title: '这一条还不算',
      hint: '要写清差在哪，这句话孩子看得见，他改好了能再交一次',
      placeholder: '例如：第 25 页空着没写', ok: '还不算',
      path: '/api/wishes/claims/' + b.dataset.wclaimNo, body: { approve: false }, toast: '退回去了',
    });
  }));
}

async function logoutNow() {
  await api('POST', '/api/logout');
  S.me = null; S.data = {}; S.view = null; await boot();
}

/* ------------------------------------------------------------------ 家长操作面板 */
function openQA(k) {
  if (k === 'explore') return exploreSheet();
  if (k === 'wish') return wishSheet();
  if (k === 'holiday') return holidaySheet();
  // 设置不再是弹层：13 组 90 项压在一层弹窗里翻不完，改成独立页，还能返回。
  if (k === 'settings') return pGo('settings');
  if (k === 'push') return pushSheet();
  if (k === 'ops') return opsSheet();
  if (k === 'settleAll') {
    sheet('<h3>结算全部周期</h3><p class="muted">星尘按本周固定分一次性入账，然后按周能量发宝箱。</p>' +
      '<button class="btn wide" id="go">现在结算</button>', box => {
        $('#go', box).addEventListener('click', async () => {
          try {
            const r = await api('POST', '/api/cycle/settle-all');
            closeSheet();
            toast(r.results.length ? '结算了 ' + r.results.length + ' 个人' : '没有待结算的周期');
            await render();
          } catch (e) { err(e); }
        });
      });
  }
}

function kidPicker(id) {
  const kids = KIDS();
  if (!kids.length) return '<div class="notice warn">还没有孩子账号</div>';
  const cur = kidId();
  return '<div class="field"><label>给谁</label><select id="' + id + '">' +
    kids.map(m => '<option value="' + m.id + '"' + (m.id === cur ? ' selected' : '') + '>' +
      esc(m.name) + '</option>').join('') + '</select></div>';
}

function exploreSheet() {
  sheet('<h3>发一个星星时刻</h3><p class="muted">必须附一句具体的话，写清楚他到底做了什么。这句话会留在他那周的记录里。</p>' +
    kidPicker('kid') +
    '<div class="field"><label>他做了什么</label><textarea id="ph" placeholder="例如：今天主动把弟弟的作业本捡起来了，没说一句抱怨"></textarea></div>' +
    '<div class="field"><label>发什么</label><div class="chips">' +
    '<button type="button" class="chip on" data-k="stardust">星尘 5</button>' +
    '<button type="button" class="chip" data-k="energy">周能量 1 分</button>' +
    '<button type="button" class="chip" data-k="both">星尘 3 + 1 分</button></div></div>' +
    '<button class="btn wide" id="go">发出去</button>', box => {
      let kind = 'stardust';
      $$('.chip', box).forEach(c => c.addEventListener('click', () => {
        kind = c.dataset.k; $$('.chip', box).forEach(x => x.classList.remove('on')); c.classList.add('on');
      }));
      $('#go', box).addEventListener('click', async () => {
        try {
          await api('POST', '/api/explore', { member_id: +$('#kid', box).value, phrase: $('#ph', box).value, kind: kind });
          closeSheet(); toast('发出去了'); await render();
        } catch (e) { err(e); }
      });
    });
}
/* 条件表单：七选一 + 对应的输入区。孩子许愿那条和家长直接建那条共用这一份，
   两处各写一遍迟早会漂。`wish` 非空就是「给这条挂起的定条件」。

   三套输入区，按选中的条件切换：
     固定分 / 星尘 / 任务数 / 连续达标 / 完美日  ->  一个门槛数值
     自己写一条                                  ->  一句话
     多选条件                                    ->  六条里勾几条、每条各填一个数，
                                                    再定「做到其中几条算达成」
   三套都常驻在 DOM 里，靠 hidden 切换，不是重画 —— 重画会把已经填好的
   备注和图标一起清掉，家长切一下条件就得重填一遍。 */
function condFormHTML(wish) {
  // 选图只出现在这一份表单里，孩子的许愿表单（wishNewSheet）刻意不加：
  // 心愿的图由家长点亮时挑，孩子那一删不了也挑不了。
  const iid = wish ? 'wsIcon' : 'wnIcon';
  const title = wish
    ? '<div class="field"><label>他想要的是什么</label>' +
      '<div class="ro">' + esc(wish.title) + '</div>' +
      (wish.reward_desc ? '<div class="ds muted">' + esc(wish.reward_desc) + '</div>' : '') +
      '</div>'
    : '<div class="field"><label>想要什么</label>' +
      '<input id="wt" placeholder="例如：去天文馆"></div>';
  const go = wish
    ? '<button class="btn wide" id="wcfg">就这么定，点亮它</button>'
    : '<button class="btn wide" id="wgo">记下并生效</button>';
  return title +
    '<div class="field"><label>怎么才算够格</label><div class="chips" id="wtype">' +
    Object.keys(WISH_COND).map((k, i) => '<button type="button" class="chip' +
      (i === 0 ? ' on' : '') + '" data-w="' + k + '">' + WISH_COND[k] + '</button>').join('') +
    '</div><div class="ds muted" id="whint" style="margin-top:6px">' +
    WISH_COND_HINT.fixed + '</div></div>' +
    '<div class="field" id="wNum"><label>门槛数值</label><input id="wv" type="number" value="' +
    WISH_DEFAULT.fixed + '"></div>' +
    '<div class="field" id="wText" hidden><label>写成一句话</label>' +
    '<input id="wtxt" maxlength="60" placeholder="例如：把《夏洛的网》读完，讲给我听">' +
    '<div class="ds muted" style="margin-top:6px">系统算不了这句话，所以没有进度条。' +
    '他做完了点一下「我做到了」，你确认就算成 —— 判定权在你，不在机器。</div></div>' +
    '<div class="field" id="wAny" hidden><label>勾几条</label>' +
    '<div id="wAnyList">' + ANY_COND_KEYS.map(k =>
      '<div class="any-row"><label class="ar-chk">' +
      '<input type="checkbox" data-at="' + k + '"' + (k === 'fixed' ? ' checked' : '') + '>' +
      '<span>' + WISH_COND[k] + '</span></label>' +
      (k === 'custom'
        ? '<input class="ar-txt" type="text" maxlength="60" data-atx="custom"' +
          ' placeholder="写成一句话，例如：读完《夏洛的网》">'
        : '<input class="ar-v" type="number" data-an="' + k + '" value="' +
          WISH_DEFAULT[k] + '">') +
      '</div>').join('') + '</div>' +
    '<div class="any-need"><label class="ar-chk">做到其中' +
    '<input id="wNeed" type="number" min="1" max="6" value="' + ANY_COND_NEED + '">' +
    '条算达成</label><span class="ds muted" id="wNeedTip"></span></div>' +
    '<div class="ds muted" style="margin-top:6px">勾上的这几条不用都做到，凑够条数就算成。' +
    '「星尘自付」进来之后，那条只有他自己点一下付掉才算做到 —— 余额够只是「能付」，' +
    '系统不替他付。他也可以不花这笔星尘，靠别的条凑够条数。</div></div>' +
    '<div class="field"><label>备注（可选）</label>' +
    '<input id="wr" placeholder="例如：随时可以去，但要提前一天说"></div>' +
    iconField(iid, '', 'wish', '配一张图') +
    (wish ? '<div class="muted" style="margin-top:-4px">挂在墙上是这张图。不挑就用默认的星星。</div>' : '') +
    go;
}

/* 点哪个条件，就露哪一块输入区。三块都留着，只切显示。 */
function bindCondForm(box, onSubmit) {
  bindIconField(box);
  let ctype = 'fixed';
  const sync = () => {
    $('#wNum', box).hidden = (ctype === 'custom' || ctype === 'any');
    $('#wText', box).hidden = ctype !== 'custom';
    $('#wAny', box).hidden = ctype !== 'any';
    $('#whint', box).textContent = WISH_COND_HINT[ctype] || '';
  };
  $$('.chip[data-w]', box).forEach(c => c.addEventListener('click', () => {
    ctype = c.dataset.w;
    $$('.chip[data-w]', box).forEach(x => x.classList.remove('on'));
    c.classList.add('on');
    if (WISH_DEFAULT[ctype] != null) $('#wv', box).value = WISH_DEFAULT[ctype];
    sync();
  }));
  // 勾选框没勾上的那条，输入框置灰：一眼看出哪几条在算。
  // 同时把「做到其中几条算达成」的上限跟着勾选条数走 —— 勾了 3 条就不能说「做到 5 条」。
  const syncAny = () => {
    const boxes = $$('#wAnyList input[type=checkbox]', box);
    let n = 0;
    boxes.forEach(cb => {
      const k = cb.dataset.at;
      const v = k === 'custom'
        ? $('#wAnyList input[data-atx="custom"]', box)
        : $('#wAnyList input[data-an="' + k + '"]', box);
      if (cb.checked) n += 1;
      if (v) v.disabled = !cb.checked;
    });
    const nd = $('#wNeed', box);
    if (!nd) return;
    nd.max = Math.max(2, n);
    let k = Math.round(+nd.value || 0);
    if (k > n) k = n;
    if (k < 1) k = 1;
    nd.value = k;
    const tip = $('#wNeedTip', box);
    if (tip) tip.textContent = n ? '（勾了 ' + n + ' 条）' : '（一条都没勾）';
  };
  $$('#wAnyList input[type=checkbox]', box).forEach(
    cb => cb.addEventListener('change', syncAny));
  syncAny();
  sync();
  const go = $('#wgo', box) || $('#wcfg', box);
  go.addEventListener('click', async () => {
    const ic = $('#wsIcon', box) || $('#wnIcon', box);
    const cond = collectCond(box, ctype);
    if (cond.__err) { toast(cond.__err); return; }
    await onSubmit(ctype, cond, $('#wr', box).value, ic ? ic.value : '');
  });
}

/* 把当前选中的那套输入区收成一个 cond 对象。三种形态各自长什么样由后端定，
   这里只负责把界面上填的东西原样交出去，不做兜底替换 ——
   填错了要当场看见一句人话，而不是被悄悄改成别的意思存下来。 */
function collectCond(box, ctype) {
  if (ctype === 'custom') {
    const t = ($('#wtxt', box).value || '').trim();
    if (t.length < 2) return { __err: '把自己定的条件写清楚，至少两个字' };
    return { text: t };
  }
  if (ctype === 'any') {
    const items = [];
    $$('#wAnyList input[type=checkbox]', box).forEach(cb => {
      if (!cb.checked) return;
      const k = cb.dataset.at;
      if (k === 'custom') {
        const t = ($('#wAnyList input[data-atx="custom"]', box).value || '').trim();
        if (t.length < 2) { items.push({ __err: '「自己写一条」得写清楚，至少两个字' }); return; }
        items.push({ type: 'custom', text: t });
        return;
      }
      items.push({ type: k, value: +$('#wAnyList input[data-an="' + k + '"]', box).value });
    });
    const bad = items.find(i => i.__err);
    if (bad) return { __err: bad.__err };
    if (items.length < 2) return { __err: '「多选条件」至少勾两条，只有一条就用上面那几种' };
    const need = Math.round(+$('#wNeed', box).value || 0);
    if (need < 1) return { __err: '「做到几条算达成」至少要 1 条' };
    if (need > items.length) {
      return { __err: '勾了 ' + items.length + ' 条，完成条数不能比它多' };
    }
    return { items: items, need: need };
  }
  return { value: +$('#wv', box).value };
}

/* 家长给一条挂起的心愿定条件。这一步就是「点亮」。
   after 是点亮之后回哪儿：从心愿单弹层里点进来的回弹层，
   从审核页那一栏点进来的回审核页 —— 两边都要能就地接着做完下一件事。 */
function wishConfigureSheet(w, after) {
  sheet('<h3>给这条心愿定条件</h3>' +
    '<p class="muted">能定的都在这儿：「固定分、星尘、任务数、连续达标、完美日」这五种系统自己会算，' +
    '写完之后进度条自己会走；「自己写一条」系统算不了，靠他自己说一声、你确认；' +
    '「多选条件」把几条摆一起，你定「做到其中几条算成」。' +
    '条件一旦定下就不能再改，他达成之后也不能反悔 —— 这一条是红线，' +
    '拒一次他不会再往上写第二个。</p>' + condFormHTML(w), box => {
    bindCondForm(box, async (ctype, cond, note, icon) => {
      try {
        await api('POST', '/api/wishes/' + w.id + '/configure', {
          cond_type: ctype, cond: cond, price_note: note, icon: icon,
        });
        closeSheet(); toast('点亮了，他开始看得见进度');
        await (after || wishSheet)();
      } catch (e) { err(e); }
    });
  });
}

async function wishSheet() {
  const mid = kidId();
  let pool = null;
  try { pool = await api('GET', '/api/pool'); } catch (e) { }
  let wishes = { items: [], limit: 2, pending_limit: 3 };
  if (mid) { try { wishes = await api('GET', '/api/wishes?member_id=' + mid); } catch (e) { } }
  const p = pool && pool.pool;
  const who = memberName(mid);
  const pend = wishes.items.filter(x => x.status === 'wished');
  const active = wishes.items.filter(x => x.status === 'active');
  const achieved = wishes.items.filter(x => x.status === 'achieved');

  let h = '<h3>心愿单 · ' + esc(who) + '</h3>' +
    '<p class="muted">三个动作：他写下想要什么，你定怎么才算够格，够了兑现。' +
    '正在算的最多 ' + wishes.limit + ' 个。</p>';

  // 待定那一栏必须放在最上面。它是唯一一条「不处理就一直卡着」的：
  // 孩子那边看到的是一句「等爸爸妈妈定条件」，家长不点它就永远是那句。
  if (pend.length) {
    h += '<div class="card"><div class="pad wband"><b>' + esc(who) +
      ' 许的愿，等你定条件</b><span class="muted">（' + pend.length + ' / ' +
      wishes.pending_limit + '）</span></div>' +
      pend.map(x => '<div class="item">' + glyph(x.icon, 'wish', 30) +
        '<div class="txt"><div class="nm">' + esc(x.title) +
        ' <span class="tag blue">挂起</span></div>' +
        (x.reward_desc ? '<div class="ds">' + esc(x.reward_desc) + '</div>' : '') +
        '<div class="ds muted">' + esc(String(x.created_at || '').slice(0, 16)) + ' 许下</div>' +
        '<div class="wact">' +
        '<button class="btn sm" data-wcfg="' + x.id + '">给它定条件</button>' +
        '<button class="btn sm line" data-wrej="' + x.id + '">驳回</button>' +
        '</div></div></div>').join('') + '</div>';
  } else {
    h += '<div class="card pad"><div class="empty">' + esc(who) +
      ' 还没有许下的愿。他那边写一条，这里就会出现。</div></div>';
  }

  // 进行中：把进度也摆出来，家长在定条件时能看见门槛是不是设高了
  if (active.length) {
    h += '<div class="card" style="margin-top:10px"><div class="pad wband"><b>正在算</b>' +
      '<span class="muted">（' + active.length + ' / ' + wishes.limit + '）</span></div>' +
      active.map(x => '<div class="item">' + glyph(x.icon, 'wish', 30) +
        '<div class="txt"><div class="nm">' + esc(x.title) +
        ' <span class="tag">进行中</span></div>' +
        '<div class="ds">条件　' + esc(wishCondText(x)) + '</div>' +
        wishProgHTML(x) +
        (x.progress && x.progress.can_pay
          ? '<div class="ds muted">星尘已经攒够，等他自己点一下付掉。' +
            '你要替他点也行，但让他自己按这一步更有意义。</div>' +
            '<div class="wact"><button class="btn sm line" data-wselfp="' + x.id +
            '">替他付掉</button></div>'
          : '') +
        '<div class="wact"><button class="btn sm line" data-wdrop="' + x.id +
        '">撤掉这个心愿</button></div>' +
        '</div></div>').join('') + '</div>';
  }

  if (achieved.length) {
    h += '<div class="card" style="margin-top:10px"><div class="pad wband"><b>他说做到了</b>' +
      '<span class="muted">条件满了，等你兑现</span></div>' +
      achieved.map(x => '<div class="item">' + glyph(x.icon, 'wish', 30) +
        '<div class="txt"><div class="nm">' + esc(x.title) +
        ' <span class="tag ok">已达成</span></div>' +
        '<div class="ds">条件　' + esc(wishCondText(x)) + '</div>' +
        '<div class="ds muted">' + esc(String(x.achieved_at || '').slice(0, 10)) + ' 达成</div>' +
        '<div class="wact"><button class="btn sm" data-wpay="' + x.id +
        '">兑现了</button></div>' +
        '</div></div>').join('') + '</div>';
  }

  // 历史：结束的都在这儿。家长得看得见「这条被驳回过、那条他自己放弃了」，
  // 才谈得下去 —— 否则孩子记得的只是「我提过，后来它就不见了」。
  const hist = wishes.items.filter(x => x.status === 'cancelled' || x.status === 'claimed');
  if (hist.length) {
    h += '<div class="card" style="margin-top:10px"><div class="fband">历史心愿（' +
      hist.length + '）</div>' + hist.slice(0, 10).map(wishHistRow).join('') +
      (hist.length > 10 ? '<div class="pad muted">只列最近 10 条</div>' : '') + '</div>';
  }

  // 家长自己一步到位建一个
  h += '<div class="hr"></div><h3>你直接定一个</h3>' +
    '<p class="muted">不经过「挂起」这一步，条件和心愿一起给，当场生效。' +
    '用于你想主动推的那件事。</p>' + condFormHTML(null);

  // 许愿池只放全家一起的体验型目标，所以这里是「挑一个」不是「写一个」。
  // 归某一个人的东西走心愿单 —— 否则被罚的那个人的钱就变成了别人的礼物，
  // 这在兄弟姐妹之间是最锋利的一种怨气。
  const tpls = (pool && pool.templates) || [];
  let tplIdx = 0;
  h += '<div class="hr"></div><h3>许愿池</h3>' +
    (p ? '<p class="muted">' + esc(p.title) + '　已攒 ' + num(p.collected_stardust) + ' / ' + num(p.target_stardust) +
      ' 星尘（' + p.percent + '%）</p>' +
      '<div class="bar"><i class="gold" style="width:' + Math.min(100, p.percent) + '%"></i></div>' +
      '<div class="hr"></div><button class="btn wide ghost" id="pdone">这个愿望达成了</button>'
      : '<p class="muted">还没有目标。许愿池是全家一起攒的东西，只能从下面几个里挑一个：' +
      '归某一个人的东西走心愿单，不走这里。</p>' +
      '<div class="chips" id="ptpl">' + tpls.map((t, i) =>
        '<button type="button" class="chip' + (i === 0 ? ' on' : '') + '" data-tpl="' + i + '">' +
        esc(t.title) + '</button>').join('') + '</div>' +
      '<div class="field"><label>具体一点</label><input id="pdd" value="' +
      esc(tpls[0] ? tpls[0].target_desc : '') + '"></div>' +
      '<div class="field"><label>要攒多少星尘</label><input id="pa" type="number" value="400"></div>' +
      '<button class="btn wide" id="go">设为目标</button>');

  sheet(h, box => {
    const go = $('#go', box), done = $('#pdone', box);
    $$('.chip[data-tpl]', box).forEach(c => c.addEventListener('click', () => {
      tplIdx = +c.dataset.tpl;
      $$('.chip[data-tpl]', box).forEach(x => x.classList.remove('on'));
      c.classList.add('on');
      const dd = $('#pdd', box);
      if (dd && tpls[tplIdx]) dd.value = tpls[tplIdx].target_desc;
    }));

    $$('[data-wcfg]', box).forEach(b => b.addEventListener('click', async () => {
      const w = wishes.items.filter(x => x.id === +b.dataset.wcfg)[0];
      await wishConfigureSheet(w);
    }));
    $$('[data-wrej]', box).forEach(b => b.addEventListener('click', async () => {
      try {
        await api('POST', '/api/wishes/' + b.dataset.wrej + '/status', { status: 'cancelled' });
        closeSheet(); toast('驳回了。跟他说清楚为什么，不然他不会写第二条'); await wishSheet();
      } catch (e) { err(e); }
    }));
    $$('[data-wdrop]', box).forEach(b => b.addEventListener('click', async () => {
      const x = (wishes.items || []).filter(y => y.id === +b.dataset.wdrop)[0] || {};
      askSheet({
        title: '撤掉《' + (x.title || '') + '》',
        hint: '心愿进历史且不能恢复，他那边立刻能看到。',
        ok: '确认取消',
      }, async () => {
        try {
          await api('POST', '/api/wishes/' + b.dataset.wdrop + '/status', { status: 'cancelled' });
          closeSheet(); toast('撤掉了'); await wishSheet();
        } catch (e) { err(e); }
      }, () => wishSheet());
    }));
    $$('[data-wselfp]', box).forEach(b => b.addEventListener('click', async () => {
      const x = (wishes.items || []).filter(y => y.id === +b.dataset.wselfp)[0] || {};
      const pay = x.progress && x.progress.selfpay_stardust ? x.progress.selfpay_stardust
        : (x.selfpay_stardust || 0);
      askSheet({
        title: '替 ' + (who || '') + ' 付 ' + num(pay) + ' 星尘',
        hint: '立刻从他账上扣 ' + num(pay) + ' 星尘；这一步本来该他自己按。',
        ok: '确认支付',
      }, async () => {
        try {
          const r = await api('POST', '/api/wishes/' + b.dataset.wselfp + '/pay', {});
          closeSheet(); toast('付掉了，还剩 ' + num(r.balance) + ' 星尘'); await wishSheet();
        } catch (e) { err(e); }
      }, () => wishSheet());
    }));
    $$('[data-wpay]', box).forEach(b => b.addEventListener('click', async () => {
      const x = (wishes.items || []).filter(y => y.id === +b.dataset.wpay)[0] || {};
      askSheet({
        title: '兑现《' + (x.title || '') + '》',
        hint: '心愿进历史且不能改回去，这一步之前先把东西给他。',
        ok: '确认已兑现',
      }, async () => {
        try {
          await api('POST', '/api/wishes/' + b.dataset.wpay + '/status', { status: 'claimed' });
          closeSheet(); toast('记下了'); await wishSheet();
        } catch (e) { err(e); }
      }, () => wishSheet());
    }));

    bindCondForm(box, async (ctype, cond, note, icon) => {
      const title = ($('#wt', box) || {}).value ? $('#wt', box).value.trim() : '';
      if (!title) { toast('先写想要什么'); return; }
      try {
        await api('POST', '/api/wishes', {
          member_id: mid, title: title, cond_type: ctype,
          cond: cond, price_note: note, icon: icon,
        });
        closeSheet(); toast('记下了，' + memberName(mid) + ' 那边能看见'); await render();
      } catch (e) { err(e); }
    });

    if (go) go.addEventListener('click', async () => {
      const t = tpls[tplIdx];
      if (!t) { toast('先挑一个目标'); return; }
      try {
        await api('POST', '/api/pool', { title: t.title, target_desc: $('#pdd', box).value, target_stardust: +$('#pa', box).value });
        closeSheet(); toast('设好了'); await render();
      } catch (e) { err(e); }
    });
    if (done) done.addEventListener('click', async () => {
      askSheet({
        title: '全家这个目标达成了',
        hint: '点完这个目标归档，池子里的 ' +
          num(((p && p.collected_cash) || ((p && p.collected_stardust) || 0) * 0.5)) + ' 元算数了。',
        ok: '记下，全家达成',
      }, async () => {
        try { await api('POST', '/api/pool/achieve'); closeSheet(); toast('记下了'); await render(); }
        catch (e) { err(e); }
      });
    });
  });
}

async function holidaySheet() {
  const d = await api('GET', '/api/holidays');
  sheet('<h3>假期日历</h3><p class="muted">填一次管一年。假期里维度换成假期版，每天还是 7 分；卡片到期撞上假期会自动顺延，不会在假期开头把东西收走。</p>' +
    (d.items.length ? d.items.map(x => '<div class="kv"><span class="k">' + esc(x.name) + '</span><span class="v">' +
      esc(x.start_date) + ' → ' + esc(x.end_date) + '</span></div>').join('') + '<div class="hr"></div>' : '') +
    '<div class="field"><label>名字</label><input id="hn" placeholder="例如：寒假"></div>' +
    '<div class="grid2"><div class="field"><label>开始</label><input id="hs" type="date"></div>' +
    '<div class="field"><label>结束</label><input id="he" type="date"></div></div>' +
    '<button class="btn wide" id="go">加上去</button>', box => {
      $('#go', box).addEventListener('click', async () => {
        try {
          const r = await api('POST', '/api/holidays', { name: $('#hn', box).value, start_date: $('#hs', box).value, end_date: $('#he', box).value });
          closeSheet();
          toast(r.delayed && r.delayed.length ? '加上了，顺延了 ' + r.delayed.length + ' 张卡' : '加上了');
          await render();
        } catch (e) { err(e); }
      });
    });
}

/* 给七维度、宝箱七档、23 张卡 6 种券换图标。
   任务和心愿的图不在这儿改：它们是一次性的东西，图是在发布当时定的。
   这里改的都是「长期存在、反复出现」的那些。 */
async function iconSheet() {
  const d = await api('GET', '/api/icon/list');
  const mk = (kind, id, cur, name, sub) => '<div class="item">' + glyph(cur, kind, 30) +
    '<div class="txt"><div class="nm">' + esc(name) + '</div>' +
    '<div class="ds">' + esc(sub || '') + '</div>' +
    '<div style="margin-top:6px">' + iconField(id, cur, kind, '') + '</div></div></div>';
  let h = '<h3>给它们换张图</h3><p class="muted">改完立刻生效，不用重新部署。' +
    '这里的图只是显示用，不影响任何分数、价格、门槛。</p>';
  h += '<div class="sec"><div class="sec-h"><h2>七个维度</h2>' +
    '<span class="sub">打分页面上就是这七个</span></div><div class="card">' +
    d.dims.map(x => mk('dim', 'ic-d-' + x.key, x.icon, x.name, 'code ' + x.key)).join('') +
    '</div></div>';
  h += '<div class="sec"><div class="sec-h"><h2>宝箱七档</h2></div><div class="card">' +
    d.boxes.map(x => mk('box', 'ic-b-' + x.key, x.icon, x.name, '')).join('') + '</div></div>';
  h += '<div class="sec"><div class="sec-h"><h2>券与卡</h2>' +
    '<span class="sub">商店、图鉴、手上持有的地方都跟着变</span></div><div class="card">' +
    d.items.map(x => mk('item', 'ic-i-' + x.key, x.icon, x.name, 'code ' + x.key)).join('') +
    '</div></div>';
  sheet(h, box => {
    bindIconField(box);
    // 每份 field 改完立刻存，不等最后的保存按钮：
    // 一项一项改的时候，中途关掉不至于全丢，而「保存」会把 36 个开关按成两个
    box.addEventListener('click', async e => {
      const cell = e.target.closest && e.target.closest('[data-ipv]');
      if (!cell) return;
      const id = cell.dataset.ipv;
      let kind = 'item', key = '';
      if (id.indexOf('ic-d-') === 0) { kind = 'dimension'; key = id.slice(5); }
      else if (id.indexOf('ic-b-') === 0) { kind = 'box'; key = +id.slice(5); }
      else if (id.indexOf('ic-i-') === 0) { kind = 'item'; key = id.slice(5); }
      try {
        await api('POST', '/api/icon', { kind: kind, key: key, icon: cell.dataset.v || '' });
        toast('换好了');
      } catch (er) { err(er); }
    });
  });
}

/* 两条不进规则的约定，写在设置页对应分组的说明里。
   它们说的是「系统不做什么」，比任何一条数值都重要：数值能改，
   这两句改不了，因为它们划的是边界。
   独处券那条防的是一个很伤人的推论（「我没攒够星尘，妈妈就不会单独陪我」）；
   假期那条防的是「放假了东西要被收走」这个每年都会冒出来的担心。
   分组名是 seed 里的固定值，家长改不了，所以按名字对得上。 */
const GRP_NOTE = {
  '券与道具':
    '每个月，家长主动安排一次一对一的独处时间，不需要任何券。' +
    '独处券买的是「这次出门做什么由我说了算」，不是「爸妈的两小时」——' +
    '这张券必须是额外的，不能是唯一一条能单独出门的路。',
  '假期':
    '系统里没有任何一条规则会在假期开始时收走孩子的东西。' +
    '会到期的是卡片（普通 90 天 / 传说 120 天），而且有保护窗兜着；' +
    '娱乐券不设有效期，周期末清掉的是「负数库存」那笔欠账，孩子是受益的一方；' +
    '星尘、称号、守护灵永久。',
};

/* ---------------------------------------------------------------- 设置页 */
/* 原来 90 项按 grp 一股脑压在一层弹窗里，两个毛病：
   ① 顺序是乱的。接口 ORDER BY grp（`api/auth.py`），SQLite 对中文按 UTF-8
      字节序排，于是「周期」排第 4、「成员与打分」排第 7，中间还夹着一条改不得的
      四条红线。组本身没有排序键，接口只能拿组名当排序用。
   ② 一屏摊 90 项，家长找不到要改的那个数。
   改成分两级：先按七件事列组（带项数），点进去才看见这一组的项。
   下面这张表兼任顺序 —— 组的次序不再由汉字决定，也不动任何一个 key、一个默认值，
   所以库不用迁移。 */
const GRP_TREE = [
  { n: '每天的七分', sub: '满分、维度、星探、修正窗口、求助、忘打卡', grps: ['成员与打分'] },
  // qa = 这一组里除了数字之外还有一个要单独开的东西。原先它们挂在「我的 →
  // 更多」，跟设置页这两组说的是同一件事，两个入口各自漂。
  { n: '周期与假期', sub: '一周从哪天起、多长、假期模式与顺延', grps: ['周期', '假期'],
    qa: ['i-hourglass', '假期日历', '填一次管一年', 'holiday'] },
  { n: '任务与心愿', sub: '奖励上限、自动确认、心愿单件数', grps: ['两套系统'] },
  { n: '奖励与道具', sub: '娱乐券、加时、卡到期、七档门槛、等级表',
    grps: ['券与道具', '宝箱', '星球等级'] },
  { n: '校准与钱', sub: '后果怎么落地、罚款与扣分钟、星尘兑零花钱、许愿池',
    grps: ['校准与修复', '汇率与基金'] },
  { n: '红线与运维', sub: '四条改不得的规则、快照保留、双人确认',
    grps: ['四条红线', '运维与权限'] },
  { n: '通知与推送', sub: '提醒时间、Bark、免打扰', grps: ['通知', '通知与推送'],
    qa: ['i-bell', '家人的手机与推送', '谁收通知、收到哪台设备', 'push'] },
];
let P_SETGRP = '';   // 空 = 一级（列七组）；非空 = 正在看这一组

async function renderAdminSettings(v) {
  const d = await api('GET', '/api/settings');
  // 双人确认默认关，所以这里平时是空的。开了之后必须有地方能点「同意」，
  // 否则提改动那个人会一直等一个永远不来的确认 —— 那不是谨慎，是死锁。
  const labelOf = k => {
    for (const g of d.groups) for (const it of g.items) if (it.key === k) return it.label;
    return k;
  };
  const node = P_SETGRP ? GRP_TREE.filter(x => x.n === P_SETGRP)[0] : null;

  // 二级页的返回不走 pGo：两级共用同一个 S.view，这里只是把分组状态清掉重画。
  // 走 pGo('settings') 会因为目标就是当前屏而被判成「重画」，状态留在原地。
  let h = node
    ? '<div class="page-head"><div style="display:flex;align-items:center;gap:10px;min-width:0">' +
      '<button class="back-btn" type="button" id="pSetBack">' + pic('i-back', 18) + '</button>' +
      '<div class="left"><span class="heading-page">' + esc(node.n) + '</span>' +
      '<span class="caption--warm">' + esc(node.sub) + '</span></div></div></div>'
    : pHead({ title: '设置', back: 'me', sub: '改完立刻生效，不用重新部署' });

  if (d.pending.length && !node) {
    h += '<div class="sec"><div class="sec-h"><h2>等着确认的改动</h2>' +
      '<span class="sub">' + d.pending.length + ' 项</span></div><div class="card">' +
      d.pending.map(x => {
        const mine = x.actor_id === S.me.id;
        return '<div class="item"><div class="txt"><div class="nm">' + esc(labelOf(x.key)) + '</div>' +
          '<div class="ds">' + esc(String(x.old_value).slice(0, 20)) + ' → ' +
          esc(String(x.new_value).slice(0, 20)) + '</div>' +
          '<div class="ds muted">' + esc(String(x.ts || '').slice(0, 16)) + '　' +
          (mine ? '你提的，等另一位家长点头' : '另一位家长提的') + '</div></div>' +
          (mine ? '' : '<button class="btn sm" data-ap="' + x.id + '">同意</button>') + '</div>';
      }).join('') + '</div></div>';
  }

  if (!node) {
    h += '<p class="caption">改哪一项都是立刻生效。默认一个人改就算；' +
      '打开「设置变更双人确认」之后才要另一位家长点一下。</p>';
    h += '<div class="card card--tight" style="padding:6px">' +
      GRP_TREE.map(g => {
        const n = d.groups.filter(x => g.grps.indexOf(x.grp) >= 0)
          .reduce((a, x) => a + x.items.length, 0);
        return '<div class="row" data-setgrp="' + esc(g.n) + '">' +
          '<div class="row-body"><span class="row-title">' + esc(g.n) + '</span>' +
          '<span class="row-sub">' + esc(g.sub) + '</span></div>' +
          '<span class="sub">' + n + ' 项</span><span class="chev">›</span></div>';
      }).join('') + '</div>';
    h += '<button class="btn btn--block btn--quiet" id="iconBtn" style="margin-top:10px">' +
      '给它们换张图</button>';
  } else {
    // 这一组里那个「不是数字、得单独开一屏」的东西，摆在分组最上面：
    // 家长点进「通知与推送」先看到的应该是配设备，而不是四个时间框。
    if (node.qa) {
      h += '<div class="card card--tight" style="padding:6px;margin-bottom:10px">' +
        '<div class="row" data-grpqa="' + esc(node.qa[3]) + '">' + pic(node.qa[0], 20) +
        '<div class="row-body"><span class="row-title">' + esc(node.qa[1]) + '</span>' +
        '<span class="row-sub">' + esc(node.qa[2]) + '</span></div>' +
        '<span class="chev">›</span></div></div>';
    }
    const gs = d.groups.filter(x => node.grps.indexOf(x.grp) >= 0);
    gs.forEach(g => {
      if (!g.items.length) return;
      h += '<div class="sec"><div class="sec-h"><h2>' + esc(g.grp) + '</h2>' +
        '<span class="sub">' + g.items.length + ' 项</span></div>';
      if (GRP_NOTE[g.grp]) {
        h += '<div class="notice info" style="margin:0 0 8px">' + esc(GRP_NOTE[g.grp]) + '</div>';
      }
      h += '<div class="card">' + g.items.map(pSetItem).join('') + '</div></div>';
    });
  }

  v.innerHTML = h;
  const ib = $('#iconBtn', v);
  if (ib) ib.addEventListener('click', iconSheet);
  $$('#view [data-back]').forEach(b2 => b2.addEventListener('click', () => pGo(b2.dataset.back)));
  const bk = $('#pSetBack', v);
  if (bk) bk.addEventListener('click', () => { P_SETGRP = ''; render(); });
  $$('#view [data-setgrp]').forEach(el => el.addEventListener('click', () => {
    P_SETGRP = el.dataset.setgrp; render();
  }));
  $$('#view [data-grpqa]').forEach(el => el.addEventListener('click', () => {
    openQA(el.dataset.grpqa);
  }));
  $$('#view button[data-ap]').forEach(b => b.addEventListener('click', async () => {
    try {
      await api('POST', '/api/settings/changes/' + b.dataset.ap + '/approve', {});
      toast('生效了'); render();
    } catch (e) { err(e); }
  }));
  $$('#view button[data-set]').forEach(b => b.addEventListener('click', async () => {
    try {
      const val = b.dataset.t === 'bool' ? (b.dataset.v === '1') : b.dataset.v;
      const r = await api('POST', '/api/settings', { key: b.dataset.set, value: val });
      toast(r.message); render();
    } catch (e) { err(e); }
  }));
  $$('#view button[data-edit]').forEach(b => b.addEventListener('click', () => {
    const key = b.dataset.edit, cur = b.dataset.v;
    pEditSheet(key, cur, () => render());
  }));
}

function pSetItem(it) {
  const val = typeof it.value === 'object' ? JSON.stringify(it.value) : it.value;
  const ro = it.locked || !it.editable;
  let h = '<div class="item"><div class="txt"><div class="nm">' + esc(it.label) +
    (it.locked ? ' <span class="tag warn">红线</span>' : '') + '</div>' +
    '<div class="ds">' + esc(it.note) + '</div>' +
    (ro ? '<div class="ds">当前：' + esc(String(val)) + '</div>' : '') + '</div>';
  if (!ro) {
    if (it.vtype === 'bool') {
      h += '<button class="btn sm ' + (it.value ? '' : 'line') + '" data-set="' + it.key +
        '" data-t="bool" data-v="' + (it.value ? '0' : '1') + '">' + (it.value ? '开' : '关') +
        '</button>';
    } else if (it.vtype === 'json') {
      h += '<span class="muted">' + (Array.isArray(it.value) ? it.value.length + ' 条' : 'JSON') +
        '</span>';
    } else {
      h += '<button class="btn sm line" data-edit="' + it.key + '" data-v="' + esc(String(val)) +
        '">' + esc(String(val).slice(0, 10)) + '</button>';
    }
  }
  return h + '</div>';
}

/* 改一个数。原来写在设置弹层的回调里，现在弹层与页面都要用它，
   抽出来 —— 两处各写一遍，改数值的地方迟早会对不上。 */
function pEditSheet(key, cur, after) {
  sheet('<h3>改一个数</h3><div class="field"><label>' + esc(key) + '</label>' +
    '<input id="nv" value="' + esc(cur) + '"></div><button class="btn wide" id="go">提交</button>',
    b2 => {
      $('#go', b2).addEventListener('click', async () => {
        let val = $('#nv', b2).value;
        if (/^-?\d+(\.\d+)?$/.test(val)) val = parseFloat(val);
        try {
          const r = await api('POST', '/api/settings', { key: key, value: val });
          closeSheet(); toast(r.message); after();
        } catch (e) { err(e); }
      });
    });
}

/* ---------------------------------------------------------------- 通知与推送 */
/* 推送这块有一条贯穿到底的取舍：网页是主场，手机是副本。
   所有消息本来就写在 notification 表里，推送只是把没发过的捡起来再发一份。
   device key 是密钥级的东西，页面上从头到尾只显示后四位，
   改备注的时候也不回填明文 —— 宁可让人重新粘一次，也不把它摆在屏幕上。 */
async function pushSheet() {
  const d = await api('GET', '/api/push');
  const g = d.globals || {};
  const on = !!g['push.enabled'];

  let h = '<h3>通知与推送</h3><p class="muted">每一条通知都先落在网页上，再往手机推一份。' +
    '推送掉线只会让手机安静下来，不会漏事。</p>';

  h += '<div class="card pad"><div class="row between"><div><div class="nm">推送总开关</div>' +
    '<div class="ds">' + (on ? '开着' : '关着。先把人的设备配上，再打开这里') + '</div></div>' +
    '<button class="btn sm ' + (on ? '' : 'line') + '" id="pen">' + (on ? '关掉' : '打开') +
    '</button></div></div>';

  h += '<div class="sec"><div class="sec-h"><h2>家人的手机</h2>' +
    '<span class="sub">各推各的，互不打扰</span></div><div class="card">';
  d.members.forEach(m => {
    const n = d.items.filter(x => x.member_id === m.id).length;
    h += '<div class="item qa-cell" data-m="' + m.id + '"' +
      ' style="box-shadow:none;border:0;border-radius:0">' +
      '<span class="qi">' + avatarHTML(m, 22) + '</span><span class="qt"><b>' + esc(m.name) + '</b>' +
      '<span>' + (n ? n + ' 台设备' : '还没配') + '</span></span></div>';
  });
  h += '</div></div>';

  h += '<div class="sec"><div class="sec-h"><h2>全局</h2></div><div class="card">';
  [['push.quiet_start', '免打扰开始', '这个点之后不再推普通通知'],
   ['push.quiet_end', '免打扰结束', '免打扰里攒下的，这个点之后一起发'],
   ['push.merge_seconds', '合并窗口', '单位：秒。同一件事攒到一起只响一下'],
   ['site.base_url', '网页地址', '填上你的域名，通知里就带一个能点回来的链接'],
  ].forEach(([k, label, note]) => {
    const v = g[k];
    const shown = (v === '' || v == null) ? '没填' : String(v);
    h += '<div class="item"><div class="txt"><div class="nm">' + esc(label) + '</div>' +
      '<div class="ds">' + esc(note) + '</div></div>' +
      '<button class="btn sm line" data-pset="' + k + '" data-v="' + esc(String(v == null ? '' : v)) +
      '">' + esc(shown.slice(0, 12)) + '</button></div>';
  });
  h += '</div></div>';

  h += '<div class="muted" style="margin-top:10px">带时限的两类通知（有人要用券、有人申请加时）' +
    '不走合并窗口，也不吃免打扰 —— 它们二十分钟不用就作废，压到第二天早上等于没发。</div>';

  sheet(h, box => {
    $('#pen', box).addEventListener('click', async () => {
      try {
        await api('POST', '/api/push/settings', { 'push.enabled': !on });
        pushSheet();
      } catch (e) { err(e); }
    });
    $$('[data-m]', box).forEach(el => el.addEventListener('click', () => {
      pushMemberSheet(+el.dataset.m);
    }));
    $$('[data-pset]', box).forEach(b => b.addEventListener('click', () => {
      const k = b.dataset.pset;
      sheet('<h3>改一项</h3><div class="field"><label>' + esc(k) + '</label>' +
        '<input id="nv" value="' + esc(b.dataset.v) + '"></div>' +
        '<button class="btn wide" id="go">存下</button>', b2 => {
          $('#go', b2).addEventListener('click', async () => {
            let v = $('#nv', b2).value;
            if (k === 'push.merge_seconds' && /^\d+$/.test(v)) v = parseInt(v, 10);
            try {
              await api('POST', '/api/push/settings', { [k]: v });
              closeSheet(); pushSheet();
            } catch (e) { err(e); }
          });
        });
    }));
  });
}

async function pushMemberSheet(mid) {
  const d = await api('GET', '/api/push');
  const m = d.members.find(x => x.id === mid) || { name: '这个人' };
  const list = d.items.filter(x => x.member_id === mid);

  let h = '<h3>' + esc(m.name) + ' 的手机</h3>' +
    '<p class="muted">手机上装一个 Bark，打开它会直接给你一段 device key。' +
    '要是你手上是一整条链接（https://api.day.app/xxxx），整条粘进来也行，' +
    '会自动把 key 拆出来。这段 key 等于「谁能往这台手机发通知」，跟密码一个级别，' +
    '页面上只显示后四位。</p>';

  if (!list.length) {
    h += '<div class="empty">还没配设备</div>';
  } else {
    list.forEach(t => {
      const state = t.last_err
        ? '<div class="ds" style="color:var(--warn)">上次没发出去：' + esc(t.last_err) + '</div>'
        : (t.last_ok_at ? '<div class="ds">上次发出去了：' + esc(t.last_ok_at) + '</div>' : '');
      h += '<div class="card pad" style="margin-bottom:8px">' +
        '<div class="row between"><b>' + esc(t.label || '设备') + '</b>' +
        '<span class="tag">' + esc(t.masked) + '</span>' +
        (t.enabled ? '' : '<span class="tag warn">停用中</span>') + '</div>' +
        '<div class="ds" style="margin-top:4px">' + esc(t.server) + '</div>' + state +
        '<div class="row" style="margin-top:10px;gap:8px">' +
        '<button class="btn sm line" data-test="' + t.id + '">测一下</button>' +
        '<button class="btn sm line" data-tog="' + t.id + '" data-on="' + (t.enabled ? 1 : 0) +
        '">' + (t.enabled ? '停用' : '启用') + '</button>' +
        '<button class="btn sm line" data-del="' + t.id + '">删掉</button>' +
        '</div></div>';
    });
  }

  const def = d.globals['push.bark_server'] || 'https://api.day.app';
  h += '<div class="hr"></div>' +
    '<div class="field"><label>device key</label>' +
    '<input id="pk" placeholder="device key，或整条 https://api.day.app/xxxx 链接"></div>' +
    '<div class="field"><label>叫什么（只你自己看得见）</label>' +
    '<input id="pl" placeholder="例如：' + esc(m.name) + '的手机"></div>' +
    '<details><summary class="muted" style="cursor:pointer">服务器地址（默认就行，别在后面接 key）</summary>' +
    '<div class="field"><input id="ps" value="' + esc(def) + '"></div></details>' +
    '<button class="btn wide" id="add">先测一下，通了就加上</button>' +
    '<div class="muted" id="perr" style="margin-top:8px;display:none"></div>';

  sheet(h, box => {
    function showErr(msg) {
      const el = $('#perr', box);
      if (!el) return;
      el.style.display = msg ? '' : 'none';
      el.innerHTML = msg ? '<span class="no-t">' + esc(msg) + '</span>' : '';
    }

    $$('[data-test]', box).forEach(b => b.addEventListener('click', async () => {
      b.disabled = true; b.textContent = '发着呢…';
      try {
        const r = await api('POST', '/api/push/test', { id: +b.dataset.test });
        b.textContent = r.ok ? '发出去了' : '没成';
        showErr(r.ok ? '' : (r.error || '没发出去'));
        toast(r.ok ? '看一眼手机' : (r.error || '没发出去'));
      } catch (e) { b.textContent = '没成'; err(e); }
      setTimeout(() => { b.disabled = false; b.textContent = '测一下'; }, 1500);
    }));
    $$('[data-tog]', box).forEach(b => b.addEventListener('click', async () => {
      try {
        await api('POST', '/api/push/target',
          { id: +b.dataset.tog, enabled: b.dataset.on !== '1' });
        pushMemberSheet(mid);
      } catch (e) { err(e); }
    }));
    $$('[data-del]', box).forEach(b => b.addEventListener('click', async () => {
      try {
        await api('DELETE', '/api/push/target/' + b.dataset.del);
        toast('删掉了'); pushMemberSheet(mid);
      } catch (e) { err(e); }
    }));

    $('#add', box).addEventListener('click', async () => {
      const key = $('#pk', box).value.trim();
      const server = $('#ps', box).value.trim() || def;
      const label = $('#pl', box).value.trim();
      if (key.length < 8) return toast('device key 太短了，再检查一下');
      const btn = $('#add', box);
      showErr('');
      btn.disabled = true; btn.textContent = '先试发一条…';
      try {
        // 先测后存：key 抄错一个字符的表现是「一直收不到」，
        // 那种事在手机上没法自查，不如加进来之前就验一次。
        const r = await api('POST', '/api/push/test', { target: key, server: server });
        if (!r.ok) {
          btn.disabled = false; btn.textContent = '先测一下，通了就加上';
          showErr(r.error || '检查一下 key 和服务器');
          return toast('发不出去：' + (r.error || '检查一下 key 和服务器'));
        }
        const sv = await api('POST', '/api/push/target',
          { member_id: mid, target: key, server: server, label: label });
        toast(sv.from_url
          ? '加上了。整条链接我拆成了 ' + sv.server + ' + ' + sv.masked
          : '加上了，手机上应该已经收到一条');
        pushMemberSheet(mid);
      } catch (e) {
        btn.disabled = false; btn.textContent = '先测一下，通了就加上';
        err(e);
      }
    });
  });
}

async function opsSheet() {
  let snap = { files: [] };
  try { snap = await api('GET', '/api/ops/snapshots'); } catch (e) { }
  sheet('<h3>备份与导出</h3><p class="muted">数据库就是一个文件。每天自动存一份快照，保留 30 天。家庭记录丢了没法重建，隔段时间顺手导一份到别的地方。</p>' +
    '<div class="kv"><span class="k">已有的快照</span><span class="v">' + snap.files.length + ' 份</span></div>' +
    (snap.files.slice(0, 5).map(f => '<div class="kv"><span class="k">' + esc(f.name) + '</span><span class="v">' +
      Math.round(f.size / 1024) + ' KB</span></div>').join('')) +
    '<div class="hr"></div>' +
    '<button class="btn wide ghost" id="snapNow">现在存一份快照</button>' +
    '<button class="btn wide line" id="exp" style="margin-top:8px">导出全部数据（JSON）</button>', box => {
      $('#snapNow', box).addEventListener('click', async () => {
        try { await api('POST', '/api/ops/snapshot'); closeSheet(); toast('存好了'); } catch (e) { err(e); }
      });
      $('#exp', box).addEventListener('click', async () => {
        try {
          const data = await api('GET', '/api/ops/export');
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'family-' + todayStr() + '.json';
          a.click();
          toast('导出好了');
        } catch (e) { err(e); }
      });
    });
}

/* ------------------------------------------------------------------ 启动 */
window.addEventListener('DOMContentLoaded', boot);
