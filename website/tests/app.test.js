'use strict';
/*
 * Tests for assets/js/app.js — run with:  node tests/app.test.js
 * No framework: plain assert + a minimal fake DOM.
 */
const assert = require('assert');
const path = require('path');

/* ---------- minimal fake DOM ---------- */
class ClassList {
  constructor(el, initial) { this.el = el; this.set = new Set(initial || []); }
  add(...c) { c.forEach(x => this.set.add(x)); }
  remove(...c) { c.forEach(x => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c) { if (this.set.has(c)) { this.set.delete(c); return false; } this.set.add(c); return true; }
  toString() { return [...this.set].join(' '); }
}
class El {
  constructor(tag, opts = {}) {
    this.tagName = (tag || 'DIV').toUpperCase();
    this.id = opts.id || '';
    this.attrs = {};
    if (opts.attrs) Object.assign(this.attrs, opts.attrs);
    this.classList = new ClassList(this, opts.classes);
    this.textContent = opts.text || '';
    this.handlers = {};
    this.children = [];
    this.parent = null;
    (opts.text || '').split('\n'); // noop
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); }
  dispatch(type, ev) {
    // bubble from this element up through parents, like real DOM events
    ev = ev || {};
    if (!ev.target) { ev.target = this; }
    let node = this;
    while (node) {
      (node.handlers[type] || []).forEach(fn => fn(ev));
      node = node.parent;
    }
  }
  focus() { this.focused = true; }
  append(child) { child.parent = this; this.children.push(child); }
  querySelectorAll(sel) {
    // supports only 'tag.class[attr]' style selectors used by app.js
    const m = /^(\w+)?\.([\w-]+)?(?:\[([\w-]+)\])?$/.exec(sel);
    assert(m, 'unsupported test selector: ' + sel);
    const out = [];
    const walk = (n) => { n.children.forEach(c => {
      const tagOk = !m[1] || c.tagName === m[1].toUpperCase();
      const clsOk = !m[2] || c.classList.contains(m[2]);
      const attrOk = !m[3] || c.getAttribute(m[3]) !== null;
      if (tagOk && clsOk && attrOk) out.push(c);
      walk(c);
    }); };
    walk(this);
    return out;
  }
}
function makeDoc() {
  const doc = new El('html');
  doc.getElementById = function (id) {
    let found = null;
    (function walk(n) { for (const c of n.children) { if (c.id === id) { found = c; return; } walk(c); if (found) return; } })(doc);
    return found;
  };
  return doc;
}

/* ---------- load module ---------- */
let failures = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); }
  catch (e) { failures++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

const ui = require(path.join(__dirname, '..', 'assets', 'js', 'app.js'));

test('module exposes the documented API', () => {
  for (const k of ['initNav', 'initCopyButtons', 'copyText', 'initYear', 'initReveal'])
    assert.strictEqual(typeof ui[k], 'function', 'missing ' + k);
});

test('initNav toggles open class and aria-expanded', () => {
  const doc = makeDoc();
  const btn = new El('button', { id: 'nav-toggle', attrs: { 'aria-expanded': 'false' } });
  const nav = new El('nav', { id: 'site-nav' });
  const link = new El('a', { text: 'Features' });
  nav.append(link);
  doc.append(btn); doc.append(nav);
  assert.strictEqual(ui.initNav(doc), true);
  btn.dispatch('click');
  assert.ok(nav.classList.contains('open'), 'nav should open');
  assert.strictEqual(btn.getAttribute('aria-expanded'), 'true');
  btn.dispatch('click');
  assert.ok(!nav.classList.contains('open'), 'nav should close');
  assert.strictEqual(btn.getAttribute('aria-expanded'), 'false');
});

test('initNav closes nav when a menu link is clicked', () => {
  const doc = makeDoc();
  const btn = new El('button', { id: 'nav-toggle', attrs: { 'aria-expanded': 'false' } });
  const nav = new El('nav', { id: 'site-nav' });
  const link = new El('a', { text: 'Install' });
  nav.append(link);
  doc.append(btn); doc.append(nav);
  ui.initNav(doc);
  btn.dispatch('click');
  link.dispatch('click', { target: link });
  assert.ok(!nav.classList.contains('open'), 'nav should close after link click');
  assert.strictEqual(btn.getAttribute('aria-expanded'), 'false');
});

test('initNav closes nav on Escape and returns focus to the button', () => {
  const doc = makeDoc();
  const btn = new El('button', { id: 'nav-toggle', attrs: { 'aria-expanded': 'false' } });
  const nav = new El('nav', { id: 'site-nav' });
  doc.append(btn); doc.append(nav);
  ui.initNav(doc);
  btn.dispatch('click');
  doc.dispatch('keydown', { key: 'Escape' });
  assert.ok(!nav.classList.contains('open'), 'Escape should close nav');
  assert.strictEqual(btn.focused, true, 'focus should return to toggle');
});

test('initNav is a no-op without the expected elements', () => {
  const doc = makeDoc();
  assert.strictEqual(ui.initNav(doc), false);
});

test('copyText uses clipboard.writeText when available', async () => {
  let got = null;
  const ok = await ui.copyText('hello', { writeText: (t) => { got = t; return Promise.resolve(); } });
  assert.strictEqual(ok, true);
  assert.strictEqual(got, 'hello');
});

test('copyText reports failure when clipboard rejects', async () => {
  const ok = await ui.copyText('x', { writeText: () => Promise.reject(new Error('denied')) });
  assert.strictEqual(ok, false);
});

test('copyText reports failure without a clipboard', async () => {
  const ok = await ui.copyText('x', null);
  assert.strictEqual(ok, false);
});

test('initCopyButtons copies target text and marks the button', async () => {
  const doc = makeDoc();
  const code = new El('pre', { id: 'cmd-1', classes: ['cmd'], text: '  sh autosongs-bridge.sh  ' });
  const btn = new El('button', { classes: ['copy-btn'], attrs: { 'data-copy-target': 'cmd-1' }, text: 'Copy' });
  doc.append(code); doc.append(btn);
  const count = ui.initCopyButtons(doc, { writeText: (t) => { doc.lastCopied = t; return Promise.resolve(); } });
  assert.strictEqual(count, 1, 'should wire one button');
  btn.dispatch('click');
  await new Promise(r => setTimeout(r, 5));
  assert.strictEqual(doc.lastCopied, 'sh autosongs-bridge.sh');
  assert.ok(btn.classList.contains('copied'), 'button should show copied state');
  assert.strictEqual(btn.textContent, 'Copied');
});

test('initCopyButtons shows a failure label when copying is denied', async () => {
  const doc = makeDoc();
  const code = new El('pre', { id: 'cmd-2', text: 'python3 ytbridge.py' });
  const btn = new El('button', { classes: ['copy-btn'], attrs: { 'data-copy-target': 'cmd-2' }, text: 'Copy' });
  doc.append(code); doc.append(btn);
  ui.initCopyButtons(doc, { writeText: () => Promise.reject(new Error('nope')) });
  btn.dispatch('click');
  await new Promise(r => setTimeout(r, 5));
  assert.ok(!btn.classList.contains('copied'));
  assert.strictEqual(btn.textContent, 'Copy failed');
});

test('initYear stamps [data-year] elements', () => {
  const doc = makeDoc();
  const span = new El('span', { classes: ['year'], attrs: { 'data-year': '' } });
  doc.append(span);
  ui.initYear(doc, 2031);
  assert.strictEqual(span.textContent, '2031');
});

test('initReveal marks elements visible immediately under reduced motion', () => {
  const doc = makeDoc();
  const card = new El('div', { classes: ['reveal'] });
  doc.append(card);
  const win = { matchMedia: () => ({ matches: true }) };
  ui.initReveal(doc, win);
  assert.ok(card.classList.contains('in'));
});

test('initReveal covers non-div reveals (regression: anchor cards)', () => {
  const doc = makeDoc();
  const linkCard = new El('a', { classes: ['card', 'card-link', 'reveal'] });
  doc.append(linkCard);
  ui.initReveal(doc, { matchMedia: () => ({ matches: true }) });
  assert.ok(linkCard.classList.contains('in'), 'anchor.reveal must also be revealed');
});

test('initReveal marks elements visible without IntersectionObserver', () => {
  const doc = makeDoc();
  const card = new El('div', { classes: ['reveal'] });
  doc.append(card);
  const win = { matchMedia: () => ({ matches: false }) };
  ui.initReveal(doc, win);
  assert.ok(card.classList.contains('in'));
});

test('initReveal observes elements when IntersectionObserver exists', () => {
  const doc = makeDoc();
  const card = new El('div', { classes: ['reveal'] });
  doc.append(card);
  let observed = null;
  const win = {
    matchMedia: () => ({ matches: false }),
    IntersectionObserver: function (cb) { this.cb = cb; this.observe = (el) => { observed = el; }; },
  };
  ui.initReveal(doc, win);
  assert.strictEqual(observed, card);
  assert.ok(!card.classList.contains('in'), 'not visible before callback');
  win && observed && (() => { /* simulate intersect */ })();
});

/* async tail: run remaining promise-based checks then report */
setTimeout(() => {
  if (failures) { console.log('\n' + failures + ' test(s) failed'); process.exit(1); }
  console.log('\nall tests passed');
}, 50);
