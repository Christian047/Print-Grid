/*
 * units.js
 * ========
 * Shared by index2.html and result.html. The server always works in
 * millimetres; this file only converts what is DISPLAYED and TYPED, and
 * converts back to mm before anything is sent to the server.
 *
 * Every length field/element this touches carries the true value in a
 * `data-mm` attribute, set once from the server-rendered (millimetre) value
 * and kept in sync as the customer types. Re-rendering in a different unit
 * always starts from data-mm, never from the currently displayed number, so
 * repeated toggling never drifts.
 */
(function (global) {
  const KEY = 'printgrid-unit';
  const MM_PER = { mm: 1, cm: 10, in: 25.4 };
  const DECIMALS = { mm: 1, cm: 2, in: 2 };
  const LABEL = { mm: 'mm', cm: 'cm', in: 'in' };

  function getUnit() {
    try {
      const u = localStorage.getItem(KEY);
      return (u && MM_PER[u]) ? u : 'in';           // inches by default
    } catch (e) { return 'in'; }
  }
  function setUnit(u) { try { localStorage.setItem(KEY, u); } catch (e) { /* private browsing */ } }

  function toMm(value, unit) { return value * MM_PER[unit]; }
  function fromMm(mmValue, unit) { return mmValue / MM_PER[unit]; }
  function formatMm(mmValue, unit) {
    const d = DECIMALS[unit];
    return (Math.round(fromMm(mmValue, unit) * Math.pow(10, d)) / Math.pow(10, d)).toFixed(d);
  }
  function suffix(unit) { return LABEL[unit]; }

  // ---- <input> fields: value/min/max are read from the DOM once (already in
  // mm, as Django renders them) and displayed in the given unit from then on.
  function primeField(el) {
    if (el.dataset.mm === undefined) el.dataset.mm = el.value === '' ? '' : el.value;
    if (el.dataset.minMm === undefined && el.min !== '') el.dataset.minMm = el.min;
    if (el.dataset.maxMm === undefined && el.max !== '') el.dataset.maxMm = el.max;
  }
  function displayField(el, unit) {
    primeField(el);
    if (el.dataset.mm !== '') el.value = formatMm(parseFloat(el.dataset.mm), unit);
    if (el.dataset.minMm !== undefined) el.min = formatMm(parseFloat(el.dataset.minMm), unit);
    if (el.dataset.maxMm !== undefined) el.max = formatMm(parseFloat(el.dataset.maxMm), unit);
    el.step = unit === 'mm' ? '0.1' : '0.01';
  }
  // Called on every keystroke, so data-mm always reflects what the customer typed.
  function syncFieldToMm(el, unit) {
    el.dataset.mm = el.value === '' ? '' : String(toMm(parseFloat(el.value), unit));
  }

  // ---- read-only display spans (result.html): <span data-mm="63.5">2.50</span>
  function displaySpan(el, unit) {
    const mm = parseFloat(el.dataset.mm);
    if (!isNaN(mm)) el.textContent = formatMm(mm, unit);
  }

  global.PGUnits = { getUnit, setUnit, toMm, fromMm, formatMm, suffix, primeField, displayField, syncFieldToMm, displaySpan };
})(window);
