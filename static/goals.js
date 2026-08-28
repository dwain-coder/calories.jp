// Daily calorie target: Mifflin-St Jeor BMR x activity + goal adjustment.
// Macro split: protein 1.6 g/kg body weight, fat 25% of energy, carbs remainder.
// Deterministic arithmetic; an estimate, not medical advice.
(function () {
  var root = document.getElementById('goals');
  if (!root) return;
  var $ = function (id) { return document.getElementById(id); };

  function update() {
    var age = parseFloat($('g-age').value);
    var sex = $('g-sex').value;
    var h = parseFloat($('g-height').value);
    var w = parseFloat($('g-weight').value);
    var act = parseFloat($('g-activity').value);
    var adj = parseFloat($('g-goal').value);
    if (![age, h, w, act, adj].every(isFinite)) return;

    var bmr = 10 * w + 6.25 * h - 5 * age + (sex === 'm' ? 5 : -161);
    var maintenance = bmr * act;
    var target = Math.max(1000, maintenance + adj);

    var protein = 1.6 * w;                 // g
    var fatKcal = target * 0.25;
    var fat = fatKcal / 9;                 // g
    var carbs = Math.max(0, (target - protein * 4 - fatKcal) / 4);  // g

    $('g-target').textContent = Math.round(target);
    $('g-maint').textContent = window.GOALS_I18N.maintenance + ': ' +
      Math.round(maintenance) + ' ' + window.GOALS_I18N.kcal;
    $('g-p').textContent = Math.round(protein) + ' g';
    $('g-f').textContent = Math.round(fat) + ' g';
    $('g-c').textContent = Math.round(carbs) + ' g';
  }

  root.querySelectorAll('input, select').forEach(function (el) {
    el.addEventListener('input', update);
    el.addEventListener('change', update);
  });
  update();
})();
