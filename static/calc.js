// Serving calculator: rescales the per-100g values embedded in the page.
// Mirrors dataset_manager/calc/nutrition.py — exact factors, full precision,
// rounding only at display.
(function () {
  var dataEl = document.getElementById('nutrition-data');
  if (!dataEl) return;
  var per100 = JSON.parse(dataEl.textContent);
  var amountEl = document.getElementById('calc-amount');
  var unitEl = document.getElementById('calc-unit');
  var perEl = document.getElementById('calc-per');
  var UNITS = { g: 1, kg: 1000, oz: 28.349523125, lb: 453.59237 };

  function grams() {
    var amount = parseFloat(amountEl.value);
    if (!isFinite(amount) || amount < 0) return null;
    var u = unitEl.value;
    if (u.indexOf('portion:') === 0) return amount * parseFloat(u.slice(8));
    return amount * UNITS[u];
  }

  function fmt(v, suffix) {
    if (v === null || v === undefined) return '—';
    var r = Math.round(v * 10) / 10;
    return r + ' ' + suffix;
  }

  function update() {
    var g = grams();
    if (g === null) return;
    perEl.textContent = (Math.round(g * 10) / 10) + ' g';
    document.querySelectorAll('#calc-result [data-field]').forEach(function (td) {
      var key = td.getAttribute('data-field');
      var v = per100[key];
      var scaled = v === null || v === undefined ? null : v * g / 100;
      td.textContent = fmt(scaled, key === 'energy_kcal' ? 'kcal' : 'g');
    });
    document.querySelectorAll('#calc-result [data-dv]').forEach(function (td) {
      var key = td.getAttribute('data-dv');
      var base = parseFloat(td.getAttribute('data-dvbase'));
      var v = per100[key];
      if (v === null || v === undefined || !base) { td.textContent = '—'; return; }
      td.textContent = Math.round(v * g / 100 / base * 100) + '%';
    });
  }

  amountEl.addEventListener('input', update);
  unitEl.addEventListener('change', update);

  // The headline kcal figure is the answer the visitor came for, so it counts
  // up once on load to draw the eye there. Server-rendered text is the source
  // of truth — this only replays it.
  var hero = document.querySelector('.kcal-hero strong');
  if (hero && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    var target = parseFloat(hero.textContent);
    if (isFinite(target) && target > 0) {
      var start = null, dur = 420;
      var tick = function (now) {
        if (start === null) start = now;
        var k = Math.min((now - start) / dur, 1);
        hero.textContent = Math.round(target * (1 - Math.pow(1 - k, 3)));
        if (k < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
  }
})();
