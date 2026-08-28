// Live search suggestions for any input with [data-suggest="<lang>"].
// Arrow keys + Enter navigate; Escape closes; plain form submit still works.
(function () {
  document.querySelectorAll('input[data-suggest]').forEach(function (input) {
    var lang = input.getAttribute('data-suggest');
    var box = document.createElement('ul');
    box.className = 'dropdown';
    box.hidden = true;
    box.setAttribute('role', 'listbox');
    input.parentNode.appendChild(box);
    var timer = null, items = [], sel = -1;

    function close() { box.hidden = true; sel = -1; }

    function render() {
      box.innerHTML = '';
      items.forEach(function (it, i) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        var name = document.createElement('span');
        name.textContent = it.title;
        li.appendChild(name);
        if (it.energy_kcal != null) {
          var k = document.createElement('span');
          k.className = 'kcal';
          k.textContent = Math.round(it.energy_kcal) + ' kcal';
          li.appendChild(k);
        }
        li.addEventListener('mousedown', function (e) {  // before input blur
          e.preventDefault();
          window.location.href = it.url;
        });
        box.appendChild(li);
      });
      box.hidden = items.length === 0;
    }

    function highlight() {
      Array.prototype.forEach.call(box.children, function (li, i) {
        li.setAttribute('aria-selected', i === sel ? 'true' : 'false');
      });
    }

    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 1) { close(); return; }
      timer = setTimeout(function () {
        fetch('/api/search?q=' + encodeURIComponent(q) + '&lang=' + lang + '&limit=7')
          .then(function (r) { return r.json(); })
          .then(function (res) { items = res; sel = -1; render(); })
          .catch(close);
      }, 200);
    });

    input.addEventListener('keydown', function (e) {
      if (box.hidden) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, items.length - 1); highlight(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, -1); highlight(); }
      else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); window.location.href = items[sel].url; }
      else if (e.key === 'Escape') { close(); }
    });
    input.addEventListener('blur', function () { setTimeout(close, 150); });
  });
})();
