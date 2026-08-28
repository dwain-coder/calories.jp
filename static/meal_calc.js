// Multi-food meal calculator. Deterministic client-side arithmetic over
// per-100g values fetched from /api/foods/{id}/nutrition.
(function () {
  var root = document.getElementById('meal-calc');
  if (!root) return;
  var lang = root.getAttribute('data-lang');
  var input = document.getElementById('meal-search-input');
  var resultsEl = document.getElementById('meal-search-results');
  var rowsEl = document.getElementById('meal-rows');
  var foods = []; // {item_id, title, per_100g, grams}
  var timer = null;

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  input.addEventListener('input', function () {
    clearTimeout(timer);
    var q = input.value.trim();
    if (!q) { resultsEl.hidden = true; return; }
    timer = setTimeout(function () {
      fetch('/api/search?q=' + encodeURIComponent(q) + '&lang=' + lang + '&limit=8')
        .then(function (r) { return r.json(); })
        .then(function (items) {
          resultsEl.innerHTML = '';
          items.filter(function (it) { return it.page_type === 'food'; }).forEach(function (it) {
            var li = document.createElement('li');
            li.innerHTML = esc(it.title) +
              (it.energy_kcal != null ? ' <span class="kcal">' + Math.round(it.energy_kcal) + ' kcal/100g</span>' : '');
            li.addEventListener('click', function () { addFood(it.item_id); });
            resultsEl.appendChild(li);
          });
          resultsEl.hidden = resultsEl.children.length === 0;
        });
    }, 250);
  });
  document.addEventListener('click', function (e) {
    if (!resultsEl.contains(e.target) && e.target !== input) resultsEl.hidden = true;
  });

  function addFood(id) {
    resultsEl.hidden = true;
    input.value = '';
    fetch('/api/foods/' + id + '/nutrition')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        foods.push({
          item_id: d.item_id,
          title: d.name[lang] || d.name.ja || d.name.en,
          source: d.source,
          per_100g: d.per_100g || {},
          grams: 100
        });
        render();
      });
  }

  function fmt(v) { return v == null ? '—' : (Math.round(v * 10) / 10); }

  function rowValues(fd) {
    var g = fd.grams, per = fd.per_100g;
    return {
      kcal: per.energy_kcal != null ? per.energy_kcal * g / 100 : null,
      p: per.protein_g != null ? per.protein_g * g / 100 : null,
      f: per.fat_g != null ? per.fat_g * g / 100 : null,
      c: per.carbohydrate_g != null ? per.carbohydrate_g * g / 100 : null
    };
  }

  function updateRowCells(tr, fd) {
    var v = rowValues(fd);
    var tds = tr.querySelectorAll('td');
    tds[2].textContent = fmt(v.kcal);
    tds[3].textContent = fmt(v.p);
    tds[4].textContent = fmt(v.f);
    tds[5].textContent = fmt(v.c);
  }

  function updateTotals() {
    var tot = { g: 0, kcal: 0, p: 0, f: 0, c: 0 };
    foods.forEach(function (fd) {
      var v = rowValues(fd);
      tot.g += fd.grams;
      if (v.kcal != null) tot.kcal += v.kcal;
      if (v.p != null) tot.p += v.p;
      if (v.f != null) tot.f += v.f;
      if (v.c != null) tot.c += v.c;
    });
    document.getElementById('tot-g').textContent = fmt(tot.g);
    document.getElementById('tot-kcal').textContent = fmt(tot.kcal);
    document.getElementById('tot-p').textContent = fmt(tot.p);
    document.getElementById('tot-f').textContent = fmt(tot.f);
    document.getElementById('tot-c').textContent = fmt(tot.c);
  }

  function render() {
    rowsEl.innerHTML = '';
    foods.forEach(function (fd, i) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td>' + esc(fd.title) + '</td>' +
        '<td><input type="number" min="0" step="any" value="' + fd.grams + '"></td>' +
        '<td></td><td></td><td></td><td></td>' +
        '<td><button class="remove-btn" title="' + esc(window.MEAL_I18N.remove) + '">×</button></td>';
      updateRowCells(tr, fd);
      tr.querySelector('input').addEventListener('input', function (e) {
        var v = parseFloat(e.target.value);
        fd.grams = isFinite(v) && v >= 0 ? v : 0;
        updateRowCells(tr, fd);   // no full re-render: keeps input focus
        updateTotals();
      });
      tr.querySelector('button').addEventListener('click', function () {
        foods.splice(foods.indexOf(fd), 1);
        render();
      });
      rowsEl.appendChild(tr);
    });
    updateTotals();
  }
})();
