// RTL rendering rules (docs/PACK_SCHEMA.md "RTL rendering"), checked on rendered markup
// with a tag-stack walk. Shared by engine_checks, script_app_checks, characters_app_checks.
// rtlAudit(html) returns the violations:
//   bidi:  a UI text node (Latin letters, or digits with no RTL letter: "79 words",
//          "3 / 4", "1–2 of 8") whose nearest dir ancestor is dir=rtl. dir=ltr/auto or a
//          <bdi> nearer isolates it;
//   font:  RTL-script text outside any data-tl element (no pack font), or Latin text
//          inside a data-tl element with no data-ui element in between (pack font);
//   mixed: one text node holding both RTL-script and Latin letters (never isolated).
"use strict";
const RTL_TXT = /[֐-ࣿיִ-﷿ﹰ-﻿]/;
const VOID = new Set(["input","br","img","hr","meta","link","path","rect","circle","polygon","line","polyline"]);
const decode = h => h.replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&");
function rtlAudit(html){
  const stack = [], bad = [];
  for(const m of String(html).matchAll(/<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>|([^<]+)/g)){
    if(m[4] !== undefined){
      const t = decode(m[4]); if(!t.trim()) continue;
      const latin = /[A-Za-z]/.test(t), rtl = RTL_TXT.test(t), ui = latin || (!rtl && /[0-9]/.test(t));
      const nd = [...stack].reverse().find(e => e.dir || e.tag === "bdi");
      const ti = stack.map(e => e.tl).lastIndexOf(true);
      if(ui && nd && nd.dir === "rtl") bad.push(`bidi: "${t.trim()}" in dir=rtl <${nd.tag}>`);
      if(rtl && ti < 0) bad.push(`font: "${t.trim()}" outside data-tl`);
      if(latin && ti >= 0 && !stack.slice(ti).some(e => e.ui)) bad.push(`font: "${t.trim()}" inside data-tl <${stack[ti].tag}>`);
      if(latin && rtl) bad.push(`mixed: "${t.trim()}"`);
      continue;
    }
    const tag = m[2].toLowerCase();
    if(m[1]){ const i = stack.map(e => e.tag).lastIndexOf(tag); if(i >= 0) stack.length = i; continue; }
    if(VOID.has(tag) || /\/\s*$/.test(m[3])) continue;
    stack.push({ tag, dir: (m[3].match(/\bdir="(\w+)"/) || [])[1], tl: /\bdata-tl\b/.test(m[3]), ui: /\bdata-ui\b/.test(m[3]) });
  }
  return bad;
}
// Buttons built with createElement (fake DOM El: dir, innerHTML), audited as their markup.
const elsMarkup = els => (els || []).map(b => `<button${b.dir ? ` dir="${b.dir}"` : ""}>${b.innerHTML}</button>`).join("");
module.exports = { rtlAudit, elsMarkup, RTL_TXT };
