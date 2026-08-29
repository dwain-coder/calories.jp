// AI meal analyzer client: staged progress, then a full report —
// macro bars vs daily values, foods detected, micronutrients, notes.
// All numbers come from the API (DB values x AI grams); labels mark which is which.
(function () {
  var root = document.getElementById('analyzer');
  if (!root) return;
  var lang = root.getAttribute('data-lang');
  var fileEl = document.getElementById('analyzer-file');
  var statusEl = document.getElementById('analyzer-status');
  var resultEl = document.getElementById('analyzer-result');
  var I = window.ANALYZER_I18N;
  var stepTimer = null;
  // Set on the home-page copy of the widget: analysis happens there, the
  // report opens on the analyzer page, where there is room for it.
  var redirectTo = root.getAttribute('data-redirect');
  var HANDOFF = 'analyzer:pending';

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }
  function fmt(v) { return v == null ? '—' : (Math.round(v * 10) / 10); }

  function startSteps() {
    var steps = [I.stepIdentify, I.stepMatch, I.stepCalc];
    var i = 0;
    statusEl.hidden = false;
    statusEl.textContent = steps[0];
    stepTimer = setInterval(function () {
      i = Math.min(i + 1, steps.length - 1);
      statusEl.textContent = steps[i];
    }, 2500);
  }
  function stopSteps() {
    clearInterval(stepTimer);
    statusEl.hidden = true;
  }

  // A view-sized copy of the photo to show above the report. The upload
  // itself is the untouched file; this is only for display, and small enough
  // to survive the handoff to the other page.
  function preview(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        var max = 900;
        var scale = Math.min(1, max / Math.max(img.width, img.height));
        var c = document.createElement('canvas');
        c.width = Math.round(img.width * scale);
        c.height = Math.round(img.height * scale);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        try { resolve(c.toDataURL('image/jpeg', 0.75)); } catch (e) { resolve(null); }
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(null); };
      img.src = url;
    });
  }

  function handOff(data, photo) {
    try {
      sessionStorage.setItem(HANDOFF, JSON.stringify({ data: data, photo: photo }));
      location.href = redirectTo;
      return true;
    } catch (e) {
      return false;      // private mode, or the photo did not fit: render here
    }
  }

  fileEl.addEventListener('change', function () {
    var f = fileEl.files[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) {
      resultEl.innerHTML = '<p class="analyzer-error">Max 8 MB</p>';
      return;
    }
    startSteps();
    resultEl.innerHTML = '';
    try { sessionStorage.removeItem(HANDOFF); } catch (e) { /* nothing stored */ }
    var fd = new FormData();
    fd.append('image', f);
    Promise.all([
      fetch('/api/meal-analyzer?lang=' + lang, { method: 'POST', body: fd })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
          return r.json();
        }),
      preview(f)
    ])
      .then(function (both) {
        var data = both[0], photo = both[1];
        if (redirectTo && handOff(data, photo)) return;   // navigating away
        renderResult(data, photo);
      })
      .catch(function (e) {
        resultEl.innerHTML = '<p class="analyzer-error">' + esc(e.message) + '</p>';
      })
      .finally(stopSteps);
  });

  // Arriving from the home page: the analysis is already done and waiting.
  (function resumeHandoff() {
    if (redirectTo) return;                 // this is the sending page
    var raw = null;
    try { raw = sessionStorage.getItem(HANDOFF); } catch (e) { return; }
    if (!raw) return;
    try {
      var held = JSON.parse(raw);
      renderResult(held.data, held.photo);
    } catch (e) { /* leave the page as it is */ }
  })();

  function bar(label, value, unit, dv) {
    var pct = dv ? Math.min(100, Math.round(value / dv * 100)) : 0;
    return '<div class="dv-row"><span class="dv-label">' + esc(label) + '</span>' +
      '<span class="dv-track"><span class="dv-fill' + (pct >= 100 ? ' over' : '') +
      '" style="width:' + pct + '%"></span></span>' +
      '<span class="dv-val">' + fmt(value) + ' ' + unit +
      (dv ? ' <em>' + Math.round(value / dv * 100) + '%</em>' : '') + '</span></div>';
  }

  function renderResult(d, photo) {
    var html = '';

    // The photograph the figures were read from, so the report stands alone
    // on screen and on paper.
    if (photo) {
      html += '<figure class="analyzed-photo"><img src="' + photo + '" alt="' +
        esc(I.photoAlt) + '"></figure>';
    }

    // Totals + macro bars vs daily values.
    if (d.totals && d.totals.energy_kcal != null) {
      html += '<p class="kcal-hero"><strong>' + Math.round(d.totals.energy_kcal) +
        '</strong> <span class="unit">' + esc(I.kcal) + '</span></p>';
      var dv = d.macro_dv || {};
      html += '<div class="dv-bars">';
      html += bar(I.kcal, d.totals.energy_kcal, I.kcal, dv.energy_kcal);
      html += bar(I.protein, d.totals.protein_g, 'g', dv.protein_g);
      html += bar(I.fat, d.totals.fat_g, 'g', dv.fat_g);
      html += bar(I.carbs, d.totals.carbohydrate_g, 'g', dv.carbohydrate_g);
      if (d.salt_g != null) html += bar(I.salt, d.salt_g, 'g', dv.salt_g);
      html += '</div>';
      html += '<p class="calc-note">' + esc(d.totals_note) + '</p>';
    }

    // Per serving, when the photo holds more than one portion of one dish.
    if (d.per_serving && d.per_serving.energy_kcal != null) {
      html += '<p class="per-serving">' + esc(I.perServing) + ': <strong>' +
        Math.round(d.per_serving.energy_kcal) + '</strong> ' + esc(I.kcal) +
        ' <span class="per-serving-note">(' +
        esc(I.servingsSeen).replace('{n}', d.servings) + ')</span></p>';
    }

    // Dishes, each broken into the ingredients it was costed from.
    var dishes = d.dishes || [];
    if (dishes.length) {
      html += '<h2 class="report-h">' + esc(I.breakdown) + '</h2>';
      dishes.forEach(function (dish, di) {
        var title = lang === 'ja' ? (dish.name_ja || dish.name_en) : (dish.name_en || dish.name_ja);
        html += '<section class="dish-block">';
        if (title) {
          html += '<h3 class="dish-name">' + esc(title);
          if (dish.totals && dish.totals.energy_kcal != null) {
            html += '<span class="dish-kcal">' + Math.round(dish.totals.energy_kcal) +
              ' ' + esc(I.kcal) + '</span>';
          }
          html += '</h3>';
        }
        var meta = [];
        if (dish.grams) meta.push(fmt(dish.grams) + ' g');
        if (dish.per_serving && dish.per_serving.energy_kcal != null) {
          meta.push(esc(I.perServing) + ' ' + Math.round(dish.per_serving.energy_kcal) + ' ' + esc(I.kcal));
        }
        if (dish.n_total && dish.n_matched < dish.n_total) {
          meta.push(esc(I.dishPartial).replace('{n}', dish.n_matched).replace('{m}', dish.n_total));
        }
        if (meta.length) html += '<p class="dish-meta">' + meta.join(' · ') + '</p>';

        html += '<table class="nutrition-table stack-table"><thead><tr>' +
          '<th>' + esc(I.ingredient) + '</th><th>g</th><th>' + esc(I.kcal) + '</th>' +
          '<th>' + esc(I.protein) + '</th><th>' + esc(I.fat) + '</th></tr></thead><tbody>';
        (dish.component_indexes || []).forEach(function (ix) {
          var c = d.components[ix];
          if (!c) return;
          var name = lang === 'ja' ? (c.identified.name_ja || c.identified.name_en)
                                   : (c.identified.name_en || c.identified.name_ja);
          html += '<tr><td>' + esc(name) +
            '<br><a class="db-link" href="' + esc(c.db_match.url) + '">' + esc(c.db_match.title) + '</a> ' +
            '<span class="badge-ai">' + esc(I.confidence) + ': ' + esc(c.identified.confidence) + '</span></td>' +
            '<td data-label="g">' + fmt(c.ai_estimate.estimated_grams) + '</td>' +
            '<td data-label="' + esc(I.kcal) + '">' + (c.calculated ? fmt(c.calculated.energy_kcal) : '—') + '</td>' +
            '<td data-label="' + esc(I.protein) + '">' + (c.calculated ? fmt(c.calculated.protein_g) : '—') + '</td>' +
            '<td data-label="' + esc(I.fat) + '">' + (c.calculated ? fmt(c.calculated.fat_g) : '—') + '</td></tr>';
        });
        // Ingredients the database does not hold: named, never costed.
        (d.unmatched || []).forEach(function (u) {
          if (u.dish_index !== di) return;
          var name = lang === 'ja' ? (u.name_ja || u.name_en) : (u.name_en || u.name_ja);
          html += '<tr class="row-unmatched"><td>' + esc(name) +
            '<br><span class="badge-ai">' + esc(I.unmatchedNote) + '</span></td>' +
            '<td data-label="g">' + (u.estimated_grams ? fmt(u.estimated_grams) : '—') + '</td>' +
            '<td data-label="' + esc(I.kcal) + '">—</td>' +
            '<td data-label="' + esc(I.protein) + '">—</td>' +
            '<td data-label="' + esc(I.fat) + '">—</td></tr>';
        });
        html += '</tbody></table></section>';
      });
    }
    // Anything the model saw outside a dish block.
    (d.unmatched || []).forEach(function (u) {
      if (u.dish_index != null && dishes.length) return;
      var name = lang === 'ja' ? (u.name_ja || u.name_en) : (u.name_en || u.name_ja);
      html += '<p><span class="badge-ai">' + esc(I.unmatched) + '</span> ' + esc(name) + '</p>';
    });

    // Micronutrients.
    if (d.micronutrients && d.micronutrients.length) {
      html += '<h2 class="report-h">' + esc(I.micros) + '</h2>';
      html += '<div class="micro-grid">';
      d.micronutrients.forEach(function (m) {
        var pct = Math.min(100, m.dv_pct);
        html += '<div class="micro-card"><span class="micro-name">' + esc(m.label) + '</span>' +
          '<span class="micro-val">' + fmt(m.amount) + ' <small>' + esc(m.unit) + '</small></span>' +
          '<span class="dv-track"><span class="dv-fill' + (m.dv_pct >= 100 ? ' over' : '') +
          '" style="width:' + pct + '%"></span></span>' +
          '<span class="micro-dv">' + m.dv_pct + '% ' + esc(I.ofDv) + '</span></div>';
      });
      html += '</div>';
      html += '<p class="calc-note">' + esc(I.microsNote).replace('{n}', d.micros_from) + '</p>';
    }

    // Notes.
    if (d.insights && d.insights.length) {
      html += '<h2 class="report-h">' + esc(I.notes) + '</h2>';
      d.insights.forEach(function (n) {
        html += '<p class="insight ' + (n.level === 'warn' ? 'insight-warn' : 'insight-good') + '">' + esc(n.text) + '</p>';
      });
    }

    if (d.components.length) {
      html += '<p class="no-print"><button class="print-btn" onclick="window.print()">' + esc(I.print) + '</button></p>';
    }
    resultEl.innerHTML = html;
  }
})();
