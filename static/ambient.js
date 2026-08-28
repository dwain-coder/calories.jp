// Start ambient loops only when the viewer welcomes motion. The autoplay
// attribute ignores prefers-reduced-motion, so playback is opt-in here and the
// poster frame stands in otherwise.
(function () {
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  var vids = document.querySelectorAll('video[data-ambient]');
  if (!vids.length) return;

  function apply() {
    vids.forEach(function (v) {
      if (reduced.matches) {
        v.pause();
        v.currentTime = 0;
      } else {
        var p = v.play();
        if (p && p.catch) p.catch(function () { /* blocked by the browser; poster stands */ });
      }
    });
  }
  apply();
  if (reduced.addEventListener) reduced.addEventListener('change', apply);
})();
