// PFC Atlas — every food in the composition table plotted by the share of its
// energy that comes from protein, fat and carbohydrate. Those three shares sum
// to 100, so each food is exactly one point in a triangle (barycentric
// coordinates). Oils pin to the fat corner, sugars to carbohydrate, dried fish
// to protein. Nothing here is decorative: every dot is a measured row.
//
// Raw WebGL, one draw call for ~2,500 points. Falls back to a static message
// if the context is unavailable, and skips the settle animation when the
// viewer prefers reduced motion.
(function () {
  var root = document.getElementById('atlas');
  if (!root) return;
  var canvas = root.querySelector('canvas');
  var tip = root.querySelector('.atlas-tip');
  var legendEl = root.querySelector('.atlas-legend');
  var lang = root.getAttribute('data-lang');
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var gl = canvas.getContext('webgl', { antialias: true, alpha: true });
  if (!gl) { root.classList.add('atlas-unavailable'); return; }

  var VERT = [
    'attribute vec2 aTarget;',
    'attribute vec3 aColor;',
    'attribute float aSeed;',
    'uniform float uT;',        // 0..1 settle progress
    'uniform float uScale;',
    'uniform float uAspect;',   // keeps the triangle equilateral on any canvas
    'uniform vec2 uOffset;',
    'uniform float uDpr;',
    'uniform float uHighlight;', // group index to emphasise, -1 = all
    'attribute float aGroup;',
    'varying vec3 vColor;',
    'varying float vDim;',
    'void main() {',
    '  vec2 start = vec2(0.0, 0.275);',              // spread out from the centroid
    '  float t = clamp(uT * 1.6 - aSeed * 0.6, 0.0, 1.0);',
    '  float e = 1.0 - pow(1.0 - t, 3.0);',           // ease-out cubic
    '  vec2 pos = mix(start, aTarget, e);',
    '  vColor = aColor;',
    '  vDim = (uHighlight < 0.0 || abs(aGroup - uHighlight) < 0.5) ? 1.0 : 0.12;',
    '  vec2 clip = vec2(pos.x * uScale / uAspect, pos.y * uScale) + uOffset;',
    '  gl_Position = vec4(clip, 0.0, 1.0);',
    '  gl_PointSize = (2.6 + 1.4 * vDim) * uDpr;',
    '}'
  ].join('\n');

  var FRAG = [
    'precision mediump float;',
    'varying vec3 vColor;',
    'varying float vDim;',
    'void main() {',
    '  vec2 d = gl_PointCoord - vec2(0.5);',
    '  float r = dot(d, d);',
    '  if (r > 0.25) discard;',                       // round points
    '  float edge = smoothstep(0.25, 0.16, r);',
    '  gl_FragColor = vec4(vColor, edge * (0.30 + 0.70 * vDim));',
    '}'
  ].join('\n');

  function compile(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  }
  var vs = compile(gl.VERTEX_SHADER, VERT), fs = compile(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) { root.classList.add('atlas-unavailable'); return; }
  var prog = gl.createProgram();
  gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { root.classList.add('atlas-unavailable'); return; }
  gl.useProgram(prog);

  var data = null, positions = null, nPoints = 0, highlight = -1;
  var loc = {};
  ['uT', 'uScale', 'uAspect', 'uOffset', 'uDpr', 'uHighlight'].forEach(function (k) {
    loc[k] = gl.getUniformLocation(prog, k);
  });

  function hexToRgb(h) {
    var n = parseInt(h.slice(1), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }

  // Barycentric: protein at the apex, fat lower-left, carbohydrate lower-right.
  function toXY(p, f, c) {
    var s = p + f + c;
    if (s <= 0) return [0, 0];
    p /= s; f /= s; c /= s;
    var x = (c - f) * 0.866;               // cos(30°)
    var y = p - (f + c) * 0.5;
    return [x, y * 1.1];
  }

  function buildBuffers() {
    var n = data.p.length;
    nPoints = n;
    positions = new Float32Array(n * 2);
    var colors = new Float32Array(n * 3);
    var seeds = new Float32Array(n);
    var groupsArr = new Float32Array(n);
    for (var i = 0; i < n; i++) {
      var xy = toXY(data.p[i], data.f[i], data.c[i]);
      positions[i * 2] = xy[0];
      positions[i * 2 + 1] = xy[1];
      var rgb = hexToRgb(data.colors[data.g[i]] || '#8B938D');
      colors[i * 3] = rgb[0]; colors[i * 3 + 1] = rgb[1]; colors[i * 3 + 2] = rgb[2];
      seeds[i] = (i % 97) / 97;
      groupsArr[i] = data.g[i];
    }
    function bind(name, arr, size) {
      var buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
      var a = gl.getAttribLocation(prog, name);
      gl.enableVertexAttribArray(a);
      gl.vertexAttribPointer(a, size, gl.FLOAT, false, 0, 0);
    }
    bind('aTarget', positions, 2);
    bind('aColor', colors, 3);
    bind('aSeed', seeds, 1);
    bind('aGroup', groupsArr, 1);
  }

  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  function resize() {
    var w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  // Triangle bounds in data space: x +/-0.866, y -0.55 (base) .. 1.1 (apex).
  var Y_MID = 0.275, Y_HALF = 0.825, X_HALF = 0.866;

  function view() {
    var aspect = (canvas.clientWidth || 1) / (canvas.clientHeight || 1);
    // Fit vertically, and horizontally too on narrow screens. Dividing x by
    // the aspect ratio is what keeps the triangle equilateral rather than
    // stretched to the canvas.
    var scale = Math.min(0.90 / Y_HALF, (0.95 / X_HALF) * aspect);
    return { aspect: aspect, scale: scale, offsetY: -Y_MID * scale };
  }

  var t0 = null;
  function draw(now) {
    if (t0 === null) t0 = now;
    var t = reduced ? 1 : Math.min((now - t0) / 1400, 1);
    var v = view();
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform1f(loc.uT, t);
    gl.uniform1f(loc.uScale, v.scale);
    gl.uniform1f(loc.uAspect, v.aspect);
    gl.uniform2f(loc.uOffset, 0, v.offsetY);
    gl.uniform1f(loc.uDpr, dpr);
    gl.uniform1f(loc.uHighlight, highlight);
    gl.drawArrays(gl.POINTS, 0, nPoints);
    if (t < 1) requestAnimationFrame(draw);
  }

  var needsFrame = false;
  function redraw() {
    if (needsFrame) return;
    needsFrame = true;
    requestAnimationFrame(function (now) { needsFrame = false; t0 = t0 === null ? now : t0; draw(now); });
  }

  // --- hover: find the nearest point in clip space -------------------------
  function nearest(mx, my) {
    var rect = canvas.getBoundingClientRect();
    var v = view();
    var cx = ((mx - rect.left) / rect.width) * 2 - 1;
    var cy = 1 - ((my - rect.top) / rect.height) * 2;
    var best = -1, bestD = 0.0016;               // ~4% of the view
    for (var i = 0; i < nPoints; i++) {
      var px = positions[i * 2] * v.scale / v.aspect;
      var py = positions[i * 2 + 1] * v.scale + v.offsetY;
      var d = (px - cx) * (px - cx) + (py - cy) * (py - cy);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  }

  var hoverIdx = -1;
  var untranslatedNote = root.getAttribute('data-untranslated') || '';

  function showTip(i, mx, my) {
    if (i < 0) { tip.hidden = true; canvas.style.cursor = ''; return; }
    var rect = root.getBoundingClientRect();
    var navigable = isNavigable(i);
    tip.hidden = false;
    tip.querySelector('.atlas-tip-name').textContent = data.names[i];
    tip.querySelector('.atlas-tip-meta').textContent =
      (data.kcal[i] != null ? data.kcal[i] + ' kcal · ' : '') +
      'P' + data.p[i] + ' / F' + data.f[i] + ' / C' + data.c[i] +
      (navigable ? '' : ' · ' + untranslatedNote);
    tip.classList.toggle('atlas-tip-muted', !navigable);
    tip.style.left = Math.round(mx - rect.left) + 'px';
    tip.style.top = Math.round(my - rect.top) + 'px';
    canvas.style.cursor = navigable ? 'pointer' : 'default';
  }

  canvas.addEventListener('mousemove', function (e) {
    if (!data) return;
    hoverIdx = nearest(e.clientX, e.clientY);
    showTip(hoverIdx, e.clientX, e.clientY);
  });
  canvas.addEventListener('mouseleave', function () { hoverIdx = -1; tip.hidden = true; });
  // Slugs arrive as "<lang>/<slug>". A point whose only page is in the other
  // language is not a link: dropping an English reader onto a Japanese page
  // without warning is worse than nothing happening. These become clickable on
  // their own once the name translations are built.
  function pageLangOf(i) { return data.slugs[i].split('/')[0]; }
  function isNavigable(i) { return i >= 0 && pageLangOf(i) === lang; }

  canvas.addEventListener('click', function () {
    if (!isNavigable(hoverIdx)) return;
    var parts = data.slugs[hoverIdx].split('/');
    window.location.href = '/' + parts[0] + '/food/' + encodeURIComponent(parts.slice(1).join('/'));
  });

  function buildLegend() {
    data.groups.forEach(function (name, i) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'atlas-chip';
      b.style.setProperty('--c', data.colors[i]);
      b.textContent = name;
      b.addEventListener('click', function () {
        highlight = (highlight === i) ? -1 : i;
        Array.prototype.forEach.call(legendEl.children, function (el, j) {
          el.setAttribute('aria-pressed', highlight === j ? 'true' : 'false');
        });
        redraw();
      });
      b.setAttribute('aria-pressed', 'false');
      legendEl.appendChild(b);
    });
  }

  fetch('/api/atlas?lang=' + lang)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      data = d;
      root.classList.add('atlas-ready');
      root.querySelector('.atlas-count').textContent = d.p.length.toLocaleString();
      buildBuffers();
      buildLegend();
      resize();
      requestAnimationFrame(draw);
      window.addEventListener('resize', function () { resize(); t0 = null; requestAnimationFrame(draw); });
    })
    .catch(function () { root.classList.add('atlas-unavailable'); });
})();
