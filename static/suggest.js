// Live search suggestions for any input with [data-suggest="<lang>"].
// Arrow keys + Enter navigate; Escape closes; plain form submit still works.
//
// With [data-pick="<field>"] the input picks a food instead of navigating to
// it (the embed builders on /embed): choosing one puts its slug in the form's
// hidden <field> input. Without JavaScript the typed text is submitted as
// <field>_q and the server finds the food itself.
(function () {
  document.querySelectorAll('input[data-suggest]').forEach(function (input) {
    var lang = input.getAttribute('data-suggest');
    var pick = input.getAttribute('data-pick');
    var hidden = pick && input.form && input.form.querySelector('input[type=hidden][name="' + pick + '"]');
    var box = document.createElement('ul');
    box.className = 'dropdown';
    box.hidden = true;
    box.setAttribute('role', 'listbox');
    input.parentNode.appendChild(box);
    var timer = null, items = [], sel = -1;

    function close() { box.hidden = true; sel = -1; }

    function choose(it) {
      if (!hidden) { window.location.href = it.url; return; }
      input.value = it.title;
      hidden.value = it.slug;
      // The slug decides now. Sending the text as well would read as text
      // typed over a choice, which the server resolves by searching again.
      input.removeAttribute('name');
      close();
    }

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
          choose(it);
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
      if (hidden) { hidden.value = ''; input.name = pick + '_q'; }
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 1) { close(); return; }
      timer = setTimeout(function () {
        fetch('/api/search?q=' + encodeURIComponent(q) + '&lang=' + lang + '&limit=7')
          .then(function (r) { return r.json(); })
          .then(function (res) {
            // Only foods have widgets; a dish would build code for a 404.
            items = hidden ? res.filter(function (it) { return it.page_type === 'food'; }) : res;
            sel = -1;
            render();
          })
          .catch(close);
      }, 200);
    });

    input.addEventListener('keydown', function (e) {
      if (box.hidden) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, items.length - 1); highlight(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, -1); highlight(); }
      else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); choose(items[sel]); }
      else if (e.key === 'Escape') { close(); }
    });
    input.addEventListener('blur', function () { setTimeout(close, 150); });
  });
})();
