/* ==========================================================================
   AutoSongs site behaviour — plain vanilla JS, no dependencies.
   Progressive enhancement only: every page works without this file.
   Exposed as AutoSongsUI on the browser global and as a CommonJS module
   so tests/app.test.js can run it under Node with a fake DOM.
   ========================================================================== */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) { module.exports = api; }
  root.AutoSongsUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /* Mobile navigation: button toggles the menu, closes on link click / Escape. */
  function initNav(doc) {
    var btn = doc.getElementById('nav-toggle');
    var nav = doc.getElementById('site-nav');
    if (!btn || !nav) { return false; }

    function setOpen(open) {
      if (open) { nav.classList.add('open'); } else { nav.classList.remove('open'); }
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    btn.addEventListener('click', function () {
      setOpen(!nav.classList.contains('open'));
    });
    nav.addEventListener('click', function (e) {
      if (e.target && e.target.tagName === 'A') { setOpen(false); }
    });
    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && nav.classList.contains('open')) {
        setOpen(false);
        btn.focus();
      }
    });
    return true;
  }

  /* Copy-to-clipboard for command blocks. */
  function copyText(text, clipboard) {
    if (clipboard && typeof clipboard.writeText === 'function') {
      return Promise.resolve()
        .then(function () { return clipboard.writeText(text); })
        .then(function () { return true; }, function () { return false; });
    }
    return Promise.resolve(false);
  }

  function initCopyButtons(doc, clipboard) {
    var buttons = Array.prototype.slice.call(
      doc.querySelectorAll('button.copy-btn[data-copy-target]')
    );
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = doc.getElementById(btn.getAttribute('data-copy-target'));
        if (!target) { return; }
        var label = btn.textContent;
        copyText((target.textContent || '').trim(), clipboard).then(function (ok) {
          if (ok) {
            btn.classList.add('copied');
            btn.textContent = 'Copied';
            setTimeout(function () {
              btn.classList.remove('copied');
              btn.textContent = label;
            }, 1600);
          } else {
            btn.textContent = 'Copy failed';
          }
        });
      });
    });
    return buttons.length;
  }

  /* Footer year. */
  function initYear(doc, year) {
    var stamp = String(year || new Date().getFullYear());
    Array.prototype.slice.call(doc.querySelectorAll('span.year[data-year]'))
      .forEach(function (el) { el.textContent = stamp; });
  }

  /* Reveal-on-scroll; falls back to visible when motion is reduced or
     IntersectionObserver is missing. */
  function initReveal(doc, win) {
    var items = Array.prototype.slice.call(doc.querySelectorAll('.reveal'));
    var reduce = win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || !win.IntersectionObserver) {
      items.forEach(function (el) { el.classList.add('in'); });
      return items.length;
    }
    var io = new win.IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px' });
    items.forEach(function (el) { io.observe(el); });
    return items.length;
  }

  var api = {
    initNav: initNav,
    copyText: copyText,
    initCopyButtons: initCopyButtons,
    initYear: initYear,
    initReveal: initReveal
  };

  /* Auto-start in a real browser only. */
  if (typeof document !== 'undefined' && typeof document.getElementById === 'function') {
    var start = function () {
      document.documentElement.classList.remove('no-js');
      document.documentElement.classList.add('js');
      initNav(document);
      initCopyButtons(document, navigator.clipboard);
      initYear(document);
      initReveal(document, window);
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', start);
    } else {
      start();
    }
  }

  return api;
});
