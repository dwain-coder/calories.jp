/* Copy buttons for embed snippets: <button data-copy="id-of-the-pre">.
   The snippet is the product of these boxes, and selecting ten lines out of a
   horizontally scrolling <pre> on a phone is not something anyone will do. */
(function () {
  function fallback(text) {
    /* clipboard.writeText needs a secure context; a plain-http preview or an
       older browser lands here instead of silently doing nothing. */
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* nothing else to try */ }
    document.body.removeChild(ta);
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest("button[data-copy]");
    if (!btn) return;
    var pre = document.getElementById(btn.dataset.copy);
    if (!pre) return;
    var text = pre.innerText;
    var done = function () {
      btn.textContent = btn.dataset.done;
      btn.classList.add("copied");
      setTimeout(function () {
        btn.textContent = btn.dataset.label;
        btn.classList.remove("copied");
      }, 2000);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); });
    } else {
      fallback(text);
      done();
    }
  });
})();
