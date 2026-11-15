// Max-branded figures for the LinkedIn article. Renders each figure as HTML+SVG and screenshots it.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const C = { ink: '#1A2130', blue: '#2D5470', slate: '#4F5766', rule: '#C9CED6', grey: '#7F8A99', light: '#A9B2BF' };
const FONT = (w, s) => `url(data:font/woff2;base64,${fs.readFileSync(path.join(__dirname, 'package/files', `source-serif-4-latin-${w}-${s}.woff2`)).toString('base64')}) format('woff2')`;
const fontCss = [[400, 'normal'], [500, 'normal'], [600, 'normal'], [400, 'italic']]
  .map(([w, s]) => `@font-face{font-family:'Source Serif 4';font-weight:${w};font-style:${s};src:${FONT(w, s)}}`).join('\n');

const W = 1200, PAD = 64;
const SOURCE_HTML = 'Source: Max Bentovim, <i>Agentic AI in Consumer Finance\u2014A Study</i>, November 2026.';

function wilson(k, n, z = 1.96) {
  const p = k / n, d = 1 + z * z / n, c = p + z * z / (2 * n), h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
  return [(c - h) / d, (c + h) / d];
}
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

// Horizontal bars. rows: {label, sub?, k, n, color}
function bars(rows, opt = {}) {
  const labelW = opt.labelW || 470, rowH = opt.rowH || 64, barH = 26, x0 = PAD + labelW, plotW = W - PAD - x0 - 150;
  const H = rows.length * rowH + 24;
  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  s += `<line x1="${x0}" y1="4" x2="${x0}" y2="${H - 8}" stroke="${C.rule}" stroke-width="1.5"/>`;
  rows.forEach((r, i) => {
    const yc = 12 + i * rowH + rowH / 2, w = plotW * r.k / (opt.scale || r.n);
    const ly = r.sub ? yc - 4 : yc + 7;
    s += `<text x="${x0 - 20}" y="${ly}" text-anchor="end" font-size="21" fill="${C.ink}">${esc(r.label)}</text>`;
    if (r.sub) s += `<text x="${x0 - 20}" y="${yc + 19}" text-anchor="end" font-size="17" fill="${C.slate}">${esc(r.sub)}</text>`;
    if (w > 0) s += `<rect x="${x0}" y="${yc - barH / 2}" width="${w}" height="${barH}" fill="${r.color}"/>`;
    s += `<text x="${x0 + w + 12}" y="${yc + 7}" font-size="21" fill="${C.ink}" style="font-variant-numeric:lining-nums tabular-nums">${opt.scale ? r.k : r.k + ' of ' + r.n}</text>`;
  });
  return s + '</svg>';
}

// Dot plot on a 0-100% axis. rows: {label, sub?}; series: {name, color, values:[{k,n}], ci?, labelValues?}
function dots(rows, series, opt = {}) {
  const labelW = opt.labelW || 420, rowH = opt.rowH || 70, x0 = PAD + labelW, plotW = W - PAD - x0 - 40;
  const top = opt.legend ? 34 * series.length + 14 : 10, H = top + rows.length * rowH + 50;
  const MAX = opt.max || 1; const X = v => x0 + plotW * Math.min(v, MAX) / MAX;
  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  (opt.ticks || [0, .25, .5, .75, 1]).forEach(t => {
    s += `<line x1="${X(t)}" y1="${top}" x2="${X(t)}" y2="${H - 40}" stroke="${C.rule}" stroke-width="1"/>`;
    s += `<text x="${X(t)}" y="${H - 12}" text-anchor="middle" font-size="18" fill="${C.slate}" style="font-variant-numeric:lining-nums tabular-nums">${Math.round(t * 100)}%</text>`;
  });
  if (opt.legend) {
    series.forEach((se, j) => {
      s += `<circle cx="${x0 + 8}" cy="${18 + 34 * j}" r="8" fill="${se.color}"/>`;
      s += `<text x="${x0 + 26}" y="${25 + 34 * j}" font-size="19" fill="${C.ink}">${esc(se.name)}</text>`;
    });
  }
  rows.forEach((r, i) => {
    const yc = top + i * rowH + rowH / 2;
    const ly = r.sub ? yc - 4 : yc + 7;
    s += `<text x="${x0 - 20}" y="${ly}" text-anchor="end" font-size="21" fill="${C.ink}">${esc(r.label)}</text>`;
    if (r.sub) s += `<text x="${x0 - 20}" y="${yc + 19}" text-anchor="end" font-size="17" fill="${C.slate}">${esc(r.sub)}</text>`;
    series.forEach(se => {
      const v = se.values[i], p = v.k / v.n;
      if (se.ci) {
        const [lo, hi] = wilson(v.k, v.n);
        s += `<line x1="${X(lo)}" y1="${yc}" x2="${X(hi)}" y2="${yc}" stroke="${se.color}" stroke-width="2"/>`;
        s += `<line x1="${X(lo)}" y1="${yc - 7}" x2="${X(lo)}" y2="${yc + 7}" stroke="${se.color}" stroke-width="2"/>`;
        s += `<line x1="${X(hi)}" y1="${yc - 7}" x2="${X(hi)}" y2="${yc + 7}" stroke="${se.color}" stroke-width="2"/>`;
      }
      s += `<circle cx="${X(p)}" cy="${yc}" r="9" fill="${se.color}" stroke="#FFFFFF" stroke-width="2"/>`;
      if (se.labelValues) {
        const lx = se.ci ? X(wilson(v.k, v.n)[1]) + 12 : X(p) + 16;
        s += `<text x="${lx}" y="${yc - 12}" font-size="18" fill="${C.ink}" style="font-variant-numeric:lining-nums tabular-nums">${v.k} of ${v.n}</text>`;
      }
    });
  });
  return s + '</svg>';
}

function page(n, title, sub, svg, note) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>${fontCss}
  *{margin:0;padding:0;box-sizing:border-box}
  body{width:${W}px;background:#FFFFFF;font-family:'Source Serif 4',Georgia,'Times New Roman',serif;color:${C.ink};font-optical-sizing:auto;font-variant-numeric:lining-nums}
  .wrap{padding:${PAD - 8}px ${PAD}px ${PAD - 16}px}
  .cap{font-size:30px;line-height:1.3;font-weight:400;max-width:1000px}
  .cap b{font-weight:600}
  .sub{font-size:19px;line-height:1.45;color:${C.slate};margin-top:10px;max-width:1040px}
  .fig{margin-top:30px}
  .note{font-size:17px;line-height:1.45;color:${C.slate};margin-top:22px;padding-top:14px;border-top:1px solid ${C.rule}}
  svg text{font-family:'Source Serif 4',Georgia,serif}
  </style></head><body><div class="wrap">
  <div class="cap"><b>Figure ${n}.</b> ${esc(title)}</div>
  ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}
  <div class="fig">${svg}</div>
  <div class="note">${note ? esc(note) + ' ' : ''}${SOURCE_HTML}</div>
  </div></body></html>`;
}

function linePanels(panels, xs, series, opt) {
  const gap = 64, totalW = W - 2 * PAD, pw = (totalW - gap) / 2, top = 70, ph = 300, left = 58, bottom = 56;
  const H = top + ph + bottom;
  let s = `<svg width="${totalW}" height="${H}" viewBox="0 0 ${totalW} ${H}">`;
  // legend
  let lx = 0;
  series.forEach(se => {
    s += `<line x1="${lx}" y1="14" x2="${lx + 34}" y2="14" stroke="${se.color}" stroke-width="3"/>`;
    s += `<circle cx="${lx + 17}" cy="14" r="5" fill="${se.color}"/>`;
    s += `<text x="${lx + 44}" y="20" font-size="19" fill="${C.ink}">${esc(se.name)}</text>`;
    lx += 44 + se.name.length * 9.6 + 40;
  });
  panels.forEach((p, pi) => {
    const ox = pi * (pw + gap), x0 = ox + left, x1 = ox + pw - 70;
    const X = j => x0 + (x1 - x0) * j / (xs.length - 1), Y = v => top + ph - ph * v / opt.n;
    s += `<text x="${ox}" y="${top - 18}" font-size="21" font-weight="500" fill="${C.ink}">${esc(p.name)}</text>`;
    [0, 10, 20, 30, 40].forEach(t => {
      s += `<line x1="${x0}" y1="${Y(t)}" x2="${x1}" y2="${Y(t)}" stroke="${C.rule}" stroke-width="1"/>`;
      s += `<text x="${x0 - 12}" y="${Y(t) + 6}" text-anchor="end" font-size="17" fill="${C.slate}" style="font-variant-numeric:lining-nums tabular-nums">${t}</text>`;
    });
    xs.forEach((x, j) => s += `<text x="${X(j)}" y="${top + ph + 32}" text-anchor="middle" font-size="17" fill="${C.slate}" style="font-variant-numeric:lining-nums tabular-nums">${x}</text>`);
    series.forEach(se => {
      const v = p.values[se.key];
      s += `<polyline fill="none" stroke="${se.color}" stroke-width="3" points="${v.map((k, j) => `${X(j)},${Y(k)}`).join(' ')}"/>`;
      v.forEach((k, j) => s += `<circle cx="${X(j)}" cy="${Y(k)}" r="5.5" fill="${se.color}" stroke="#fff" stroke-width="2"/>`);
      const last = v[v.length - 1];
      s += `<text x="${x1 + 10}" y="${Y(last) + 6 + (se.dy || 0)}" font-size="17" fill="${C.ink}" style="font-variant-numeric:lining-nums tabular-nums">${last}</text>`;
    });
  });
  return s + '</svg>';
}

const html = page(1, 'Who was being paid mattered more than how much',
  'Transfers from savings carried out without asking first, by destination and amount. 40 replies per point (four models, 10 runs); wave 2, Part A.',
  linePanels(
    [{ name: 'No rules', values: { own: [40, 40, 40, 40], est: [40, 40, 39, 36], neu: [30, 28, 20, 18] } },
     { name: 'General duty', values: { own: [40, 40, 40, 40], est: [40, 40, 40, 31], neu: [29, 21, 20, 20] } }],
    ['$50', '$500', '$5,000', '$15,000'],
    [{ key: 'own', name: 'The user’s own account', color: C.grey, dy: -6 },
     { key: 'est', name: 'Payee on file since 2024', color: C.light, dy: 8 },
     { key: 'neu', name: 'Payee added that morning', color: C.blue }],
    { n: 40 }),
  'For the payee added that morning, two models paid without asking almost every time (with no rules, across the four amounts: gpt\u2011oss 40 of 40, Qwen 38 of 40) and two mostly asked (DeepSeek paid unasked in 5 of 40, GLM in 13 of 40).');

(async () => {
  const browser = await chromium.launch();
  const pg = await browser.newPage({ viewport: { width: W, height: 800 }, deviceScaleFactor: 2 });
  fs.mkdirSync('out_report', { recursive: true });
  await pg.setContent(html, { waitUntil: 'load' });
  await pg.evaluate(() => document.fonts.ready);
  const h = await pg.evaluate(() => document.body.scrollHeight);
  await pg.setViewportSize({ width: W, height: h });
  await pg.screenshot({ path: 'out_report/report-figure-1.png' });
  await browser.close();
  console.log('ok', h);
})();
