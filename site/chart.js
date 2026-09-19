
// Crosshair + tooltip on the price chart. An HTML chart is interactive by
// default; a line you cannot read a value off is a picture, not a chart.
document.querySelectorAll('.chart').forEach(function (fig) {
  var svg = fig.querySelector('svg');
  var tip = fig.querySelector('.tip');
  if (!svg || !tip) return;
  var pts;
  try { pts = JSON.parse(svg.dataset.points); } catch (e) { return; }
  if (!pts || pts.length < 2) return;

  var cross = svg.querySelector('.crosshair');
  var dot = svg.querySelector('.hoverdot');
  var series = svg.querySelector('.series');
  var d = series.getAttribute('d').split(/[ML]/).filter(Boolean).map(function (s) {
    var xy = s.split(','); return { x: parseFloat(xy[0]), y: parseFloat(xy[1]) };
  });

  function show(evt) {
    var box = svg.getBoundingClientRect();
    var vb = svg.viewBox.baseVal;
    var x = (evt.clientX - box.left) / box.width * vb.width;
    var best = 0;
    for (var i = 1; i < d.length; i++) {
      if (Math.abs(d[i].x - x) < Math.abs(d[best].x - x)) best = i;
    }
    var p = d[best], row = pts[best];
    if (!p || !row) return;
    cross.setAttribute('x1', p.x); cross.setAttribute('x2', p.x);
    cross.style.display = ''; dot.style.display = '';
    dot.setAttribute('cx', p.x); dot.setAttribute('cy', p.y);
    var when = new Date(row[0] + 'T00:00:00').toLocaleDateString(undefined,
      { year: 'numeric', month: 'short' });
    tip.textContent = when + '  ·  ' + row[1].toFixed(2) + ' CR';
    tip.hidden = false;
    tip.style.left = (p.x / vb.width * box.width) + 'px';
    tip.style.top = (p.y / vb.height * box.height) + 'px';
  }
  function hide() {
    cross.style.display = 'none'; dot.style.display = 'none'; tip.hidden = true;
  }
  svg.addEventListener('mousemove', show);
  svg.addEventListener('mouseleave', hide);
  svg.addEventListener('touchmove', function (e) {
    if (e.touches[0]) show(e.touches[0]);
  }, { passive: true });
  svg.addEventListener('touchend', hide);
});
