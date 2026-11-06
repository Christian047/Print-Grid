/* preview.js - draws one sheet from the quote's placements (read-only).
   PGPreview.render(host, quote, imageUrls) */
(function (g) {
  const NS = 'http://www.w3.org/2000/svg';
  let idx = 0;
  const mk = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const line = { 'vector-effect': 'non-scaling-stroke', 'stroke-width': 1 };

  function render(host, d, images) {
    const pv = d.preview, s = pv.sheet;
    if (idx >= pv.plans.length) idx = 0;
    const plan = pv.plans[idx];
    host.textContent = '';

    if (pv.plans.length > 1) {                       // switch between different sheets of a multi-design job
      const tabs = document.createElement('div');
      tabs.className = 'btn-group btn-group-sm mb-2';
      pv.plans.forEach((p, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-outline-primary' + (i === idx ? ' active' : '');
        b.textContent = p.repeat > 1 ? 'Sheets ' + p.first_sheet + '–' + (p.first_sheet + p.repeat - 1) : 'Sheet ' + p.first_sheet;
        b.onclick = () => { idx = i; render(host, d, images); };
        tabs.appendChild(b);
      });
      host.appendChild(tabs);
    }

    const svg = mk('svg', { viewBox: '0 0 ' + s.width + ' ' + s.height, role: 'img',
      'aria-label': plan.placements.length + ' stickers fit on this sheet' }, host);
    mk('rect', { width: s.width, height: s.height, fill: '#fff' }, svg);
    // the printable area is amber: whatever the stickers don't cover stays amber = unused paper
    mk('rect', Object.assign({ x: s.margin_left, y: s.margin_top,
      width: s.width - s.margin_left - s.margin_right, height: s.height - s.margin_top - s.margin_bottom,
      fill: '#FFF1CC', stroke: '#E0A100', 'stroke-dasharray': '5 4' }, line), svg);

    plan.placements.forEach((p, i) => {
      const faded = idx === 0 && pv.solid !== null && i >= pv.solid;   // "room for more" beyond the quantity ordered
      const grp = mk('g', faded ? { opacity: 0.4 } : {}, svg);
      mk('title', {}, grp).textContent = 'Design ' + (p.design + 1);
      mk('rect', Object.assign({ x: p.x, y: p.y, width: p.w, height: p.h, rx: 0.8,
        fill: '#DDF3E5', stroke: '#1CAA53' }, line), grp);
      const src = images[p.design];
      if (!src) return;
      const cx = p.x + p.w / 2, cy = p.y + p.h / 2, turn = p.rotation === 90;
      const w = turn ? p.h : p.w, h = turn ? p.w : p.h;               // rotation 90 = clockwise; w/h are the box after turning
      const im = mk('image', { x: cx - w / 2, y: cy - h / 2, width: w, height: h,
        preserveAspectRatio: 'xMidYMid meet' }, grp);
      im.setAttribute('href', src);
      if (turn) im.setAttribute('transform', 'rotate(90 ' + cx + ' ' + cy + ')');
    });

    const lg = document.createElement('div');
    lg.className = 'pv-legend';
    lg.innerHTML = '<span><i class="sw sw-s"></i>Stickers</span><span><i class="sw sw-w"></i>Unused paper</span>' +
      (pv.solid !== null && pv.solid < plan.placements.length ? '<span><i class="sw sw-s faded"></i>Room for more</span>' : '');
    host.appendChild(lg);
  }
  g.PGPreview = { render };
})(window);
