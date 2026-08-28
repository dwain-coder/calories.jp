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

  fileEl.addEventListener('change', function () {
    var f = fileEl.files[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) {
      resultEl.innerHTML = '<p class="analyzer-error">Max 8 MB</p>';
      return;
    }
    startSteps();
    resultEl.innerHTML = '';
    var fd = new FormData();
    fd.append('image', f);
    fetch('/api/meal-analyzer?lang=' + lang, { method: 'POST', body: fd })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
        return r.json();
      })
      .then(renderResult)
      .catch(function (e) {
        resultEl.innerHTML = '<p class="analyzer-error">' + esc(e.message) + '</p>';
      })
      .finally(stopSteps);
  });

  function bar(label, value, unit, dv) {
    var pct = dv ? Math.min(100, Math.round(value / dv * 100)) : 0;
    return '<div class="dv-row"><span class="dv-label">' + esc(label) + '</span>' +
      '<span class="dv-track"><span class="dv-fill' + (pct >= 100 ? ' over' : '') +
      '" style="width:' + pct + '%"></span></span>' +
      '<span class="dv-val">' + fmt(value) + ' ' + unit +
      (dv ? ' <em>' + Math.round(value / dv * 100) + '%</em>' : '') + '</span></div>';
  }

  function renderResult(d) {
    var html = '';

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

    // Foods detected.
    if (d.components.length) {
      html += '<h2 class="report-h">' + esc(I.detected) + '</h2>';
      html += '<table class="nutrition-table"><tbody>';
      d.components.forEach(function (c) {
        var name = lang === 'ja' ? (c.identified.name_ja || c.identified.name_en)
                                 : (c.identified.name_en || c.identified.name_ja);
        html += '<tr><td><a href="' + esc(c.db_match.url) + '">' + esc(name) + '</a><br>' +
          '<span class="badge-db">' + esc(c.db_match.source) + '</span> ' +
          '<span class="badge-ai">' + esc(I.estimate) + ' · ' + esc(I.confidence) + ': ' + esc(c.identified.confidence) + '</span></td>' +
          '<td>' + fmt(c.ai_estimate.estimated_grams) + ' g</td>' +
          '<td>' + (c.calculated ? '<strong>' + fmt(c.calculated.energy_kcal) + ' ' + esc(I.kcal) + '</strong>' : '—') + '</td>' +
          '<td>P:' + (c.calculated ? fmt(c.calculated.protein_g) : '—') + 'g</td></tr>';
      });
      html += '</tbody></table>';
    }
    d.unmatched.forEach(function (u) {
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
