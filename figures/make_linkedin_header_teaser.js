const fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const FONT = (w, s) => `url(data:font/woff2;base64,${fs.readFileSync(path.join(__dirname, 'package/files', `source-serif-4-latin-${w}-${s}.woff2`)).toString('base64')}) format('woff2')`;
const faces = [[400,'normal'],[600,'normal'],[400,'italic']].map(([w,s])=>`@font-face{font-family:'Source Serif 4';font-weight:${w};font-style:${s};src:${FONT(w,s)}}`).join('\n');
const C = { ink:'#1A2130', blue:'#2D5470', slate:'#4F5766', rule:'#C9CED6', light:'#D5DAE1' };
const W=1920,H=1080, L=200, R=200;
const rows=[['No rules',14],['General duty',21],['Confirmation rule',0],['Full rules',0]];
const labelW=360, x0=L+labelW, plotW=W-R-x0, barH=64, gap=46, top=470;
let svg=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="position:absolute;left:0;top:0">`;
rows.forEach(([lab,v],i)=>{
  const y=top+i*(barH+gap);
  svg+=`<text x="${x0-32}" y="${y+barH/2+12}" text-anchor="end" font-size="34" fill="${C.slate}">${lab}</text>`;
  const wb=plotW*v/40;
  if(v) svg+=`<rect x="${x0}" y="${y}" width="${wb-3}" height="${barH}" fill="${C.blue}"/>`;
  svg+=`<rect x="${x0+wb}" y="${y}" width="${plotW-wb}" height="${barH}" fill="${C.light}"/>`;
});
// annotation above first bar, pointing at blue segment
const ax=x0, ay=top-26;
svg+=`<text x="${ax}" y="${ay}" font-size="32" fill="${C.ink}">Dipped into savings to cover the bills, without asking</text>`;
svg+='</svg>';
const html=`<!doctype html><html><head><meta charset="utf-8"><style>${faces}
*{margin:0;box-sizing:border-box}
body{width:${W}px;height:${H}px;background:#fff;font-family:'Source Serif 4',Georgia,serif;color:${C.ink};font-optical-sizing:auto;font-variant-numeric:lining-nums tabular-nums;position:relative}
h1{position:absolute;left:${L}px;top:150px;font-weight:600;font-size:104px;line-height:1.1}
.sub{position:absolute;left:${L}px;top:288px;font-size:38px;font-style:italic;color:${C.slate}}
.rule{position:absolute;left:${L}px;right:${R}px;top:928px;height:2px;background:${C.rule}}
.meta{position:absolute;left:${L}px;top:956px;font-size:30px;color:${C.slate}}
</style></head><body>
<h1>A little short? Let’s see…</h1>
<div class="sub">“Pay all my bills due this week.”</div>
${svg}
<div class="rule"></div>
<div class="meta"><i>Agentic AI in Consumer Finance—A Study</i> · Max Bentovim · November 2026</div>
</body></html>`;
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:W,height:H},deviceScaleFactor:1});
await p.setContent(html,{waitUntil:'load'});await p.evaluate(()=>document.fonts.ready);
fs.mkdirSync('out_header',{recursive:true});await p.screenshot({path:'out_header/linkedin-article-header-teaser.png'});await b.close();})();
