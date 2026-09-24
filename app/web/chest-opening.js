/* 宝箱开箱组件
 * 一套动画通用 7 档：待机浮动 → 抖动 → 白闪光爆 → 开盖 → 光柱粒子 → 卡券飞出（由小变大）→ onDone 回调。
 * 动画只负责开箱表现，不展示具体内容；开出什么由集成方在 onDone 回调里弹窗展示。
 * 零依赖，纯原生 DOM。
 */
(function (global) {
  'use strict';

  // 档位配置：光色 + 飞出卡券数量。要调整只改这里。
  var TIERS = [
    { name: '木箱',   light: '#D9A05B', loot: 2 },
    { name: '铜箱',   light: '#E8A54B', loot: 3 },
    { name: '银箱',   light: '#CFE3F5', loot: 3 },
    { name: '金箱',   light: '#FFD54F', loot: 4 },
    { name: '钻石箱', light: '#7EC3FF', loot: 4 },
    { name: '王者箱', light: '#B78CFF', loot: 5 },
    { name: '完美箱', light: '#FFC1E0', loot: 6 }
  ];

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function el(tag, cls, parent) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (parent) parent.appendChild(e);
    return e;
  }

  function preload(src) { var im = new Image(); im.src = src; return im; }

  function create(container, opts) {
    opts = opts || {};
    var assetPath = (opts.assetPath || 'assets/').replace(/\/?$/, '/');
    var hint = opts.hint !== false;
    var autoDemo = !!opts.autoDemo;

    // ---- 舞台 DOM ----
    var stage = el('div', 'cs-stage', container);
    var beam = el('div', 'cs-beam', stage);
    var fx = el('div', 'cs-fx', stage);
    el('div', 'cs-shadow', stage);
    var chest = el('div', 'cs-chest idle', stage);
    var imgClosed = el('img', '', chest);
    var imgOpen = el('img', '', chest);
    imgOpen.style.display = 'none';
    imgOpen.alt = '';
    // 光芒 / 冲击环 / 白闪爆点都挂在箱子上，以箱子中心为圆心、藏箱子背后
    //（z-index:-1 压到箱图后面）。挂在舞台上的话圆心永远对不准箱子。
    var rays = el('div', 'cs-rays', chest);
    var ring = el('div', 'cs-ring', chest);
    var burst = el('div', 'cs-burst', chest);
    var itemsBox = el('div', 'cs-items', stage);
    var hintEl = null;
    if (hint) {
      hintEl = el('div', 'cs-hint', stage);
      hintEl.textContent = '点击宝箱开启';
    }
    var replay = el('button', 'cs-replay', stage);
    replay.textContent = '再开一次';
    replay.type = 'button';

    var cur = 0;      // 当前档位索引 0-6
    var busy = false;
    var lastOnDone = null;

    function applyTier(i) {
      cur = i;
      var t = TIERS[i];
      stage.style.setProperty('--cs-light', t.light);
      imgClosed.src = assetPath + 'chest' + (i + 1) + '_closed.png';
      imgOpen.src = assetPath + 'chest' + (i + 1) + '_open.png';
      reset();
    }

    function reset() {
      imgOpen.style.display = 'none';
      imgClosed.style.display = '';
      chest.classList.add('idle');
      chest.classList.remove('shaking');
      imgOpen.classList.remove('pop');
      beam.classList.remove('on');
      rays.classList.remove('on');
      ring.classList.remove('on');
      itemsBox.innerHTML = '';
      replay.classList.remove('on');
      if (hintEl) hintEl.classList.remove('off');
    }

    function spawnParticles(color, n) {
      var cx = stage.clientWidth / 2;
      var cy = stage.clientHeight * 0.76;
      for (var k = 0; k < n; k++) {
        var s = el('div', 'cs-spark', fx);
        var size = 4 + Math.random() * 6;
        s.style.cssText =
          'left:' + (cx + (Math.random() * 90 - 45)) + 'px;' +
          'top:' + (cy + (Math.random() * 30 - 15)) + 'px;' +
          'width:' + size + 'px;height:' + size + 'px;' +
          '--pc:' + color + ';' +
          '--dx:' + (Math.random() * 160 - 80) + 'px;' +
          '--dy:' + -(120 + Math.random() * 160) + 'px;' +
          '--dur:' + (0.8 + Math.random() * 0.7) + 's;';
        (function (node, life) { setTimeout(function () { node.remove(); }, life); })(s, 1800);
      }
    }

    // 卡 / 点券剪影：由小变大 + 翻转 + 抛物线飞散，带 ? 暗示未知内容
    function spawnLoot(tier) {
      itemsBox.innerHTML = '';
      var n = tier.loot;
      var fromX = stage.clientWidth / 2;
      var fromY = stage.clientHeight * 0.72;
      for (var i = 0; i < n; i++) {
        var s = el('div', 'cs-loot ' + (Math.random() < 0.5 ? 'card' : 'ticket'), itemsBox);
        s.textContent = '?';
        s.style.setProperty('--pc', Math.random() < 0.65 ? tier.light : '#9EC9FF');
        s.style.left = (fromX - 21) + 'px';
        s.style.top = fromY + 'px';
        var dx = Math.random() * 280 - 140;
        var peak = -(stage.clientHeight * 0.22 + Math.random() * 130);
        var drop = 24 + Math.random() * 40;
        var dur = 950 + Math.random() * 550;
        var rot = Math.random() * 180 - 90;
        var grow = 1.35 + Math.random() * 0.5;
        // fill 用 both：起飞前的 delay 期间也停在第一帧（缩小+透明），
        // 不然道具会在起飞前原样亮在箱口，看着像从箱底冒出来的。
        s.style.opacity = '0';
        s.animate([
          { transform: 'translate(0,0) scale(.12) rotate(0deg)', opacity: 0 },
          { transform: 'translate(' + (dx * 0.5) + 'px,' + peak + 'px) scale(1) rotate(' + (rot * 0.6) + 'deg)', opacity: 1, offset: 0.5 },
          { transform: 'translate(' + dx + 'px,' + (peak + drop) + 'px) scale(' + grow + ') rotate(' + rot + 'deg)', opacity: 0 }
        ], { duration: dur, easing: 'cubic-bezier(.25,.6,.45,1)', delay: i * 120, fill: 'both' });
        (function (node, life) { setTimeout(function () { node.remove(); }, life); })(s, dur + i * 120 + 250);
      }
    }

    async function play(tier, onDone) {
      if (busy) return;
      busy = true;
      if (typeof tier === 'number') {
        var i = Math.min(7, Math.max(1, Math.round(tier))) - 1;
        if (i !== cur) applyTier(i); else reset();
      } else {
        reset();
      }
      if (typeof onDone === 'function') lastOnDone = onDone;
      var t = TIERS[cur];

      if (hintEl) hintEl.classList.add('off');
      replay.classList.remove('on');
      itemsBox.innerHTML = '';

      // 1. 抖动蓄力
      chest.classList.remove('idle');
      chest.classList.add('shaking');
      await sleep(560);
      chest.classList.remove('shaking');

      // 2. 白闪 + 开盖
      burst.classList.add('on');
      await sleep(70);
      imgClosed.style.display = 'none';
      imgOpen.style.display = '';
      imgOpen.classList.add('pop');
      await sleep(260);
      burst.classList.remove('on');

      // 3. 光柱 + 光芒 + 粒子
      beam.classList.add('on');
      rays.classList.remove('on'); void rays.offsetWidth; rays.classList.add('on');
      ring.classList.remove('on'); void ring.offsetWidth; ring.classList.add('on');
      spawnParticles(t.light, 18);

      // 4. 卡券飞出（由小变大）
      await sleep(320);
      spawnLoot(t);
      spawnParticles(t.light, 12);
      await sleep(1100 + t.loot * 120 + 450);

      // 5. 动画结束，交还集成方（在此弹结果窗）
      replay.classList.add('on');
      busy = false;
      if (typeof lastOnDone === 'function') lastOnDone(cur + 1);
    }

    chest.addEventListener('click', function () { play(null, lastOnDone); });
    replay.addEventListener('click', function () { play(null, lastOnDone); });

    // 预加载 14 张图
    for (var i = 1; i <= 7; i++) {
      preload(assetPath + 'chest' + i + '_closed.png');
      preload(assetPath + 'chest' + i + '_open.png');
    }

    applyTier(0);
    if (autoDemo) setTimeout(function () { play(1); }, 700);

    return {
      play: play,
      setTier: function (t) { applyTier(Math.min(7, Math.max(1, Math.round(t))) - 1); },
      reset: reset,
      tiers: TIERS,
      destroy: function () { if (stage.parentNode) stage.parentNode.removeChild(stage); }
    };
  }

  global.ChestOpening = { create: create, TIERS: TIERS };
})(window);
