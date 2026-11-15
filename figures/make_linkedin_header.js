const fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const FONT = (w, s) => `url(data:font/woff2;base64,${fs.readFileSync(path.join(__dirname, 'package/files', `source-serif-4-latin-${w}-${s}.woff2`)).toString('base64')}) format('woff2')`;
const faces = [[400,'normal'],[600,'normal'],[400,'italic']].map(([w,s])=>`@font-face{font-family:'Source Serif 4';font-weight:${w};font-style:${s};src:${FONT(w,s)}}`).join('\n');
const W=1920,H=1080;
const html=`<!doctype html><html><head><meta charset="utf-8"><style>${faces}
*{margin:0;box-sizing:border-box}
body{width:${W}px;height:${H}px;background:#fff;font-family:'Source Serif 4',Georgia,serif;color:#1A2130;font-optical-sizing:auto;font-variant-numeric:lining-nums tabular-nums}
.wrap{position:absolute;left:200px;right:200px;top:0;bottom:0;display:flex;flex-direction:column;justify-content:center}
h1{font-weight:600;font-size:104px;line-height:1.12;letter-spacing:-0.005em;max-width:1400px}
.rule{height:2px;background:#C9CED6;margin:64px 0 40px;width:100%}
.meta{font-size:38px;color:#4F5766}
</style></head><body><div class="wrap">
<h1>Agentic AI in Consumer Finance—A&nbsp;Study</h1>
<div class="rule"></div>
<div class="meta">Max Bentovim · November 2026</div>
</div></body></html>`;
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:W,height:H},deviceScaleFactor:1});
await p.setContent(html,{waitUntil:'load'});await p.evaluate(()=>document.fonts.ready);
fs.mkdirSync('out_header',{recursive:true});await p.screenshot({path:'out_header/linkedin-article-header.png'});await b.close();})();
