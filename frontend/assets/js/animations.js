/* frontend/assets/js/animations.js
 *
 * GSAP 动画脚本 — 适配三类页面：
 *   1. 门户首页 frontend/index.html         → 粒子背景 + 卡片错落入场 + 滚动视差 + hover 微反馈
 *   2. 阶段页   frontend/pages/stages/*.html → header 入场 + section 滚动揭示 + nav stagger
 *   3. 交互地图 frontend/pages/*.html       → 地图浮层入场 + 小时切换脉冲 + 车辆切换过渡
 *
 * 设计原则（遵循 gsap-core / gsap-performance 规范）：
 *   - 只动画 transform 与 opacity（x/y/scale/rotation/autoAlpha），避免触发 layout
 *   - 入场用 fromTo 明确起止状态，避免依赖当前渲染值
 *   - hover 用 quickTo 复用 tween，避免每次 mouseenter 创建新 tween
 *   - ScrollTrigger 仅用于顶层 timeline / tween，不嵌套
 *   - gsap.matchMedia 处理 prefers-reduced-motion：减动效用户跳过所有动画
 */
(function () {
  'use strict';

  // GSAP 未加载则静默退出
  if (typeof window.gsap !== 'function') {
    console.warn('[animations] GSAP not loaded — skipping animations');
    return;
  }
  if (typeof window.ScrollTrigger === 'object') {
    gsap.registerPlugin(ScrollTrigger);
  }

  var mm = gsap.matchMedia();

  // ── 粒子背景 (仅门户首页) ──────────────────────────────────────────────
  function initParticles() {
    var canvas = document.getElementById('particles-canvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var particles = [];
    var PARTICLE_COUNT = 40;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize);

    for (var i = 0; i < PARTICLE_COUNT; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.5 + 0.5,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        alpha: Math.random() * 0.5 + 0.2
      });
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(77,140,255,' + p.alpha + ')';
        ctx.fill();
      }
      requestAnimationFrame(draw);
    }
    draw();
  }

  mm.add(
    {
      isDesktop: '(min-width: 720px)',
      isMobile: '(max-width: 719px)',
      reduceMotion: '(prefers-reduced-motion: reduce)'
    },
    function (ctx) {
      var conditions = ctx.conditions;
      var reduce = conditions.reduceMotion;
      var isMapPage = !!document.getElementById('map');

      // 减动效：直接显示所有元素最终状态
      if (reduce) {
        gsap.set(['header', '.section', '.demo-card', '.box', '.nav a', '.btn', '.card-link',
          '#title', '#legend', '#info', '#panel', '#header', '#marker-legend'],
          { opacity: 1, y: 0, x: 0, scale: 1, clearProps: 'transform' });
        return function () {};
      }

      // ── 1) 门户首页：粒子背景 ─────────────────────────────────────────
      if (!isMapPage) {
        // 添加粒子 canvas
        var existingCanvas = document.getElementById('particles-canvas');
        if (!existingCanvas) {
          var canvas = document.createElement('canvas');
          canvas.id = 'particles-canvas';
          document.body.prepend(canvas);
        }
        initParticles();
      }

      // ── 2) header 通用入场 ────────────────────────────────────────────
      var headerEl = document.querySelector('header');
      if (headerEl) {
        var headerTL = gsap.timeline({ defaults: { ease: 'power3.out' } });
        headerTL.fromTo(headerEl.querySelector('h1'),
          { y: -40, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: 0.8 }
        );
        var subtitleEl = headerEl.querySelector('.subtitle');
        if (subtitleEl) {
          headerTL.fromTo(subtitleEl,
            { y: -16, autoAlpha: 0 },
            { y: 0, autoAlpha: 1, duration: 0.6 },
            '-=0.3'
          );
        }
        var navEls = headerEl.querySelectorAll('.nav a');
        if (navEls.length) {
          headerTL.fromTo(navEls,
            { y: 12, autoAlpha: 0 },
            { y: 0, autoAlpha: 1, duration: 0.45, stagger: 0.06, ease: 'back.out(1.4)' },
            '-=0.15'
          );
        }
      }

      // ── 3) 门户首页：卡片错落入场 ─────────────────────────────────────
      var demoCards = document.querySelectorAll('.demo-card');
      var boxes = document.querySelectorAll('.box');
      var navLinks = document.querySelectorAll('.nav a');
      var flowEl = document.querySelector('.flow');

      if (flowEl) {
        gsap.fromTo(flowEl,
          { x: -20, autoAlpha: 0 },
          { x: 0, autoAlpha: 1, duration: 0.6, ease: 'power2.out', delay: 0.3 }
        );
      }

      if (demoCards.length) {
        gsap.fromTo(demoCards,
          { y: 36, autoAlpha: 0, scale: 0.96 },
          { y: 0, autoAlpha: 1, scale: 1, duration: 0.65, ease: 'back.out(1.2)',
            stagger: { each: 0.1, from: 'start' }, delay: 0.2 }
        );
      }

      if (boxes.length) {
        gsap.fromTo(boxes,
          { y: 28, autoAlpha: 0, scale: 0.97 },
          { y: 0, autoAlpha: 1, scale: 1, duration: 0.55, ease: 'back.out(1.15)',
            stagger: { each: 0.07, from: 'start' }, delay: 0.3 }
        );
      }

      if (navLinks.length && !headerEl) {
        gsap.fromTo(navLinks,
          { y: 12, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: 0.4, ease: 'power2.out',
            stagger: 0.05, delay: 0.35 }
        );
      }

      // ── 4) 滚动揭示 + 视差 ────────────────────────────────────────────
      var sections = document.querySelectorAll('.section');
      if (sections.length && typeof ScrollTrigger === 'object') {
        sections.forEach(function (sec) {
          // 微视差：滚动时 section 轻微上移
          gsap.fromTo(sec,
            { y: 50, autoAlpha: 0 },
            {
              y: 0, autoAlpha: 1, duration: 0.8, ease: 'power3.out',
              scrollTrigger: {
                trigger: sec,
                start: 'top 88%',
                toggleActions: 'play none none reverse',
                once: false
              }
            }
          );
        });
      }

      // ── 5) hover 微反馈 (quickTo) ─────────────────────────────────────
      var hoverTargets = document.querySelectorAll('.box, .demo-card, .btn, .nav a, .card-link');
      var quickTos = [];
      hoverTargets.forEach(function (el) {
        var yTo = gsap.quickTo(el, 'y', { duration: 0.25, ease: 'power2.out' });
        var scaleTo = gsap.quickTo(el, 'scale', { duration: 0.25, ease: 'power2.out' });
        quickTos.push({ el: el, yTo: yTo, scaleTo: scaleTo });
        var enterY = el.classList.contains('btn') || el.classList.contains('card-link') ? -3 : -5;
        el.addEventListener('mouseenter', function () {
          yTo(enterY);
          scaleTo(1.03);
        });
        el.addEventListener('mouseleave', function () {
          yTo(0);
          scaleTo(1);
        });
      });

      // ── 6) 交互地图页：浮层错落入场 ──────────────────────────────────
      if (isMapPage) {
        var titleEl = document.getElementById('title');
        var legendEl = document.getElementById('legend');
        var infoEl = document.getElementById('info');
        var panelEl = document.getElementById('panel');
        var headerBar = document.getElementById('header');
        var markerLegend = document.getElementById('marker-legend');

        if (headerBar) {
          gsap.fromTo(headerBar, { y: -70, autoAlpha: 0 },
            { y: 0, autoAlpha: 1, duration: 0.7, ease: 'power3.out', delay: 0.05 });
        }
        if (titleEl) {
          gsap.fromTo(titleEl, { y: -30, autoAlpha: 0, scale: 0.95 },
            { y: 0, autoAlpha: 1, scale: 1, duration: 0.65, ease: 'back.out(1.2)', delay: 0.25 });
        }
        if (panelEl) {
          gsap.fromTo(panelEl, { x: -50, autoAlpha: 0 },
            { x: 0, autoAlpha: 1, duration: 0.7, ease: 'power3.out', delay: 0.45 });
        }
        if (legendEl) {
          gsap.fromTo(legendEl, { x: 40, autoAlpha: 0 },
            { x: 0, autoAlpha: 1, duration: 0.6, ease: 'power3.out', delay: 0.55 });
        }
        if (markerLegend) {
          gsap.fromTo(markerLegend, { x: -30, autoAlpha: 0 },
            { x: 0, autoAlpha: 1, duration: 0.55, ease: 'power2.out', delay: 0.6 });
        }
        if (infoEl) {
          gsap.fromTo(infoEl, { y: 16, autoAlpha: 0 },
            { y: 0, autoAlpha: 1, duration: 0.5, ease: 'power2.out', delay: 0.65 });
        }
      }

      return function () {
        // matchMedia revert 清理
        quickTos.forEach(function (qt) {
          qt.el.removeEventListener('mouseenter', null);
          qt.el.removeEventListener('mouseleave', null);
        });
      };
    }
  );

  // ── 7) 页面级增强钩子（供各页面调用）───────────────────────────────────
  window.GSAPPage = {
    /* 热力图：小时切换脉冲 */
    heatmapHourPulse: function (hourElId) {
      if (typeof gsap !== 'function') return;
      gsap.from('#' + hourElId, {
        scale: 1.35,
        duration: 0.35,
        ease: 'power2.out',
        overwrite: 'auto'
      });
    },
    /* 热力图：提示条入场 */
    heatmapToastShow: function (toastEl) {
      if (typeof gsap !== 'function') return;
      gsap.fromTo(toastEl,
        { x: 30, autoAlpha: 0 },
        { x: 0, autoAlpha: 1, duration: 0.3, ease: 'power2.out', overwrite: 'auto' }
      );
    },
    /* 热力图：提示条退场 */
    heatmapToastHide: function (toastEl, callback) {
      if (typeof gsap !== 'function') { if (callback) callback(); return; }
      gsap.to(toastEl, {
        autoAlpha: 0, duration: 0.25, ease: 'power2.in',
        onComplete: callback, overwrite: 'auto'
      });
    },
    /* 轨迹查看器：面板状态刷新脉冲 */
    trajectoryPanelPulse: function (selector) {
      if (typeof gsap !== 'function') return;
      gsap.from(selector, {
        autoAlpha: 0.3, duration: 0.4,
        stagger: 0.04, ease: 'power2.out', overwrite: 'auto'
      });
    },
    /* 轨迹查看器：进度条脉冲 */
    trajectoryProgressPulse: function (progressBarEl) {
      if (typeof gsap !== 'function') return;
      gsap.fromTo(progressBarEl,
        { scaleY: 1.3 },
        { scaleY: 1, duration: 0.3, ease: 'power2.out', overwrite: 'auto' }
      );
    },
    /* 通用：按钮点击反馈 */
    buttonClickFeedback: function (el) {
      if (typeof gsap !== 'function') return;
      gsap.fromTo(el,
        { scale: 0.92 },
        { scale: 1, duration: 0.3, ease: 'elastic.out(1, 0.4)', overwrite: 'auto' }
      );
    },
    /* 路网拥堵：路段渐显 */
    roadFadeIn: function (selector) {
      if (typeof gsap !== 'function') return;
      gsap.fromTo(selector,
        { autoAlpha: 0, scale: 0.98 },
        { autoAlpha: 1, scale: 1, duration: 0.5, stagger: 0.015, ease: 'power2.out' }
      );
    }
  };
})();
