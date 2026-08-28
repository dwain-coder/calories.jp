// Click-to-sort for .sortable tables. Numeric cells carry data-v.
(function () {
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var dirs = {};
    table.querySelectorAll('th[data-sort]').forEach(function (th, col) {
      th.style.cursor = 'pointer';
      th.setAttribute('role', 'button');
      th.setAttribute('tabindex', '0');
      function sort() {
        var tbody = table.tBodies[0];
        var rows = Array.prototype.slice.call(tbody.rows);
        var dir = dirs[col] = -(dirs[col] || -1);
        var numeric = th.getAttribute('data-sort') === 'num';
        rows.sort(function (a, b) {
          var av, bv;
          if (numeric) {
            av = parseFloat(a.cells[col].getAttribute('data-v'));
            bv = parseFloat(b.cells[col].getAttribute('data-v'));
            return (av - bv) * dir;
          }
          av = a.cells[col].textContent.trim();
          bv = b.cells[col].textContent.trim();
          return av.localeCompare(bv) * dir;
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
        table.querySelectorAll('th[data-sort]').forEach(function (o) { o.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
      }
      th.addEventListener('click', sort);
      th.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); } });
    });
  });
})();
