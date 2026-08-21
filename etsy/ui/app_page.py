"""The interactive app — one self-contained page over the daily snapshot.

    .venv/Scripts/python.exe -m etsy.ui.app_page
    -> etsy/data/ui/app.html   (open it; tabs, sort, filter, search, all client-side)

WHY ONE FILE, NO SERVER
-----------------------
The whole dataset (app_data.build_snapshot) is baked into the page as JSON, and
vanilla JavaScript does the interactivity: tab switching, column sort, per-view
filters, a search box, sparkline charts. For one operator whose data refreshes
daily, this IS the app — it opens as a file, works offline, needs no daemon, and
matches how everything else here runs.

It reads THROUGH app_data, never past it. The exact same functions a FastAPI
server would expose as endpoints are what fills this page; when the server is
built, it consumes app_data too and this file becomes one of two thin consumers,
not a thing to rewrite.

NO FRAMEWORK, NO CDN
--------------------
Self-contained on purpose: a file opened from disk should not depend on a network
to render. The JS is small and hand-written; the charts are inline SVG. Every
number keeps the basis app_data attached, and the client styles derived and
provisional values distinctly from measured ones — an estimate must not look like
a fact even here.
"""
import json
import os
from datetime import datetime, timezone

OUT_DIR = os.path.join("etsy", "data", "ui")


def render_html(snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    # Embed as JSON in a script tag. json.dumps handles escaping; the </script>
    # guard prevents a stray closing tag inside a string from breaking the parse.
    data = json.dumps(snapshot, default=str).replace("</", "<\\/")

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Etsy intelligence — app</title>
<style>
:root {{
  --ground:#EEF1EF; --surface:#FFF; --surface-2:#E7ECE9; --line:#D3DAD5;
  --ink:#16211F; --ink-2:#47554F; --ink-3:#5D6A64; --accent:#14666E;
  --good:#2F6B45; --good-bg:#E1EDE5; --warn:#8A6417; --warn-bg:#F3EAD3;
  --bad:#9E3B26; --bad-bg:#F6E3DD; --derived:#5B4C8A; --season:#33578A;
}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
  --ground:#0E1615; --surface:#161F1E; --surface-2:#1E2927; --line:#2A3734;
  --ink:#E5ECE9; --ink-2:#A8B7B1; --ink-3:#93A19B; --accent:#5FBCC4;
  --good:#7CB795; --good-bg:#1B2A21; --warn:#D9B762; --warn-bg:#2C2617;
  --bad:#E68469; --bad-bg:#33201B; --derived:#A996DC; --season:#8AAEDC;
}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:14.5px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
.top{{position:sticky;top:0;z-index:5;background:var(--ground);
  border-bottom:1px solid var(--line);padding:14px 20px 0}}
.top h1{{margin:0 0 2px;font-size:20px;letter-spacing:-.02em}}
.stamp{{color:var(--ink-3);font-size:12px;margin:0 0 10px}}
.stamp .prov{{color:var(--warn)}}
.tabs{{display:flex;gap:2px;flex-wrap:wrap}}
.tab{{border:none;background:none;color:var(--ink-2);font:inherit;font-weight:600;
  font-size:13.5px;padding:8px 13px;border-radius:7px 7px 0 0;cursor:pointer;
  border-bottom:2px solid transparent}}
.tab:hover{{background:var(--surface-2)}}
.tab.active{{color:var(--accent);border-bottom-color:var(--accent);background:var(--surface)}}
main{{max-width:1180px;margin:0 auto;padding:18px 20px 64px}}
.view{{display:none}} .view.active{{display:block}}
.controls{{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin-bottom:14px}}
.controls input,.controls select{{font:inherit;font-size:13px;padding:7px 10px;
  border:1px solid var(--line);border-radius:7px;background:var(--surface);color:var(--ink)}}
.controls input[type=search]{{min-width:220px}}
.count{{color:var(--ink-3);font-size:12.5px;margin-left:auto}}
.twrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:2px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--surface);
  border:1px solid var(--line);border-radius:9px;overflow:hidden}}
thead th{{text-align:left;font-size:11px;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ink-3);padding:9px 11px;border-bottom:1px solid var(--line);
  cursor:pointer;user-select:none;white-space:nowrap}}
thead th.num{{text-align:right}} thead th:hover{{color:var(--ink)}}
thead th .arrow{{opacity:.5;font-size:10px}}
tbody td{{padding:8px 11px;border-bottom:1px solid var(--line);vertical-align:baseline}}
tbody tr:last-child td{{border-bottom:none}}
tbody tr:hover td{{background:var(--surface-2)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.pill{{display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;
  border-radius:4px}}
.pill.winnable{{background:var(--good);color:var(--surface)}}
.pill.contested{{background:var(--warn);color:var(--surface)}}
.pill.wall{{background:var(--surface-2);color:var(--ink-3);border:1px solid var(--line)}}
.pill.now{{background:var(--bad);color:var(--surface)}}
.pill.list_by{{background:var(--warn);color:var(--surface)}}
.pill.watching{{background:var(--surface-2);color:var(--ink-3)}}
.pill.untimed,.pill.passed{{background:var(--surface-2);color:var(--ink-3)}}
.ratio.win{{color:var(--good);font-weight:700}} .ratio.wall{{color:var(--bad)}}
.season{{color:var(--season);font-size:12px}}
.sub{{color:var(--ink-3);font-size:12px}}
.deriv{{color:var(--derived);font-style:italic;font-size:11.5px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;
  margin-bottom:18px}}
.kpi{{background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:13px 15px}}
.kpi .n{{font-size:24px;font-weight:700;letter-spacing:-.02em}}
.kpi .l{{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3)}}
.kpi.bad .n{{color:var(--bad)}} .kpi.good .n{{color:var(--good)}} .kpi.warn .n{{color:var(--warn)}}
.block{{background:var(--surface);border:1px solid var(--line);border-radius:9px;
  padding:15px 17px;margin-bottom:14px}}
.block.blocked{{border-left:4px solid var(--bad)}}
.block h2{{margin:0 0 8px;font-size:15px}}
.block ul{{margin:0;padding-left:18px;color:var(--ink-2);font-size:13.5px}}
.block li{{margin-bottom:3px}}
svg.spark{{vertical-align:middle}}
.chip{{display:inline-block;background:var(--surface-2);border:1px solid var(--line);
  border-radius:4px;padding:1px 6px;font-size:11.5px;margin:1px}}
.swatch{{display:inline-block;width:11px;height:11px;border-radius:2px;
  vertical-align:middle;margin-right:5px;border:1px solid rgba(128,128,128,.4)}}
.empty{{color:var(--ink-3);padding:20px;text-align:center;font-size:13.5px}}
a{{color:var(--accent)}}
</style></head><body>
<div class="top">
  <h1>Etsy intelligence</h1>
  <p class="stamp" id="stamp"></p>
  <div class="tabs" id="tabs"></div>
</div>
<main>
  <div class="view active" id="v-dashboard"></div>
  <div class="view" id="v-discover"></div>
  <div class="view" id="v-etsy"></div>
  <div class="view" id="v-pinterest"></div>
  <div class="view" id="v-calendar"></div>
  <div class="view" id="v-shops"></div>
</main>
<script id="data" type="application/json">{data}</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const $ = (s,r=document)=>r.querySelector(s);
const el = (t,c,h)=>{{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;}};
const fmt = n => n==null?"—":n.toLocaleString();
const pct = n => n==null?"—":(n*100).toFixed(0)+"%";
const age = iso => {{ if(!iso) return ""; const d=Math.floor((Date.now()-new Date(iso))/864e5);
  return d<=0?"today":d===1?"yesterday":d+"d ago"; }};

// ---- freshness + tabs ------------------------------------------------------
const m = DATA.meta;
$("#stamp").innerHTML = "Snapshot "+age(m.generated_at)+" · "
  + (m.verdicts_provisional
     ? '<span class="prov">profit verdicts provisional</span>'
     : "settings confirmed")
  + " · no live calls";
const TABS = [["dashboard","Dashboard"],["discover","Discover"],["etsy","Etsy demand"],
  ["pinterest","Pinterest"],["calendar","Calendar"],["shops","Competitors"]];
TABS.forEach(([id,label],i)=>{{
  const b=el("button","tab"+(i===0?" active":""),label); b.dataset.tab=id;
  b.onclick=()=>{{document.querySelectorAll(".tab").forEach(t=>t.classList.remove("active"));
    document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
    b.classList.add("active"); $("#v-"+id).classList.add("active");}};
  $("#tabs").appendChild(b);
}});

// ---- a sortable, filterable table ------------------------------------------
function sparkline(series){{
  const vals=series.map(s=>s.volume).filter(v=>v!=null);
  if(vals.length<2) return "";
  const w=64,h=18,mn=Math.min(...vals),mx=Math.max(...vals),rng=(mx-mn)||1;
  const pts=vals.map((v,i)=>`${{(i/(vals.length-1)*w).toFixed(1)}},${{(h-((v-mn)/rng)*h).toFixed(1)}}`).join(" ");
  const up=vals[vals.length-1]>=vals[0];
  return `<svg class="spark" width="${{w}}" height="${{h}}"><polyline points="${{pts}}" fill="none" stroke="${{up?'var(--good)':'var(--bad)'}}" stroke-width="1.5"/></svg>`;
}}
function table(container, rows, cols, opts={{}}){{
  let state={{sort:opts.sort||null, dir:opts.dir||-1, q:"", filters:{{}}}};
  const controls=el("div","controls");
  const search=el("input"); search.type="search"; search.placeholder="search…";
  search.oninput=()=>{{state.q=search.value.toLowerCase();draw();}};
  controls.appendChild(search);
  (opts.filters||[]).forEach(f=>{{
    const sel=el("select"); sel.innerHTML='<option value="">'+f.label+': all</option>'
      +f.options.map(o=>`<option value="${{o}}">${{o}}</option>`).join("");
    sel.onchange=()=>{{state.filters[f.key]=sel.value;draw();}};
    controls.appendChild(sel);
  }});
  const count=el("span","count"); controls.appendChild(count);
  const tbl=el("table"); const thead=el("thead"); const tb=el("tbody");
  const htr=el("tr");
  cols.forEach(c=>{{const th=el("th",c.num?"num":"",c.label+' <span class="arrow"></span>');
    th.onclick=()=>{{state.dir=state.sort===c.key?-state.dir:-1;state.sort=c.key;draw();}};
    htr.appendChild(th);}});
  thead.appendChild(htr); tbl.appendChild(thead); tbl.appendChild(tb);
  const tw=el("div","twrap"); tw.appendChild(tbl);
  container.appendChild(controls); container.appendChild(tw);
  function draw(){{
    let r=rows.filter(row=>{{
      if(state.q && !cols.some(c=>String(row[c.key]??"").toLowerCase().includes(state.q))) return false;
      for(const k in state.filters){{if(state.filters[k] && String(row[k]??"")!==state.filters[k]) return false;}}
      return true;
    }});
    if(state.sort){{const k=state.sort;r.sort((a,b)=>{{const x=a[k],y=b[k];
      if(x==null)return 1;if(y==null)return -1;
      return (x>y?1:x<y?-1:0)*state.dir;}});}}
    tb.innerHTML="";
    r.slice(0,opts.limit||500).forEach(row=>{{
      const tr=el("tr");
      cols.forEach(c=>{{const td=el("td",c.num?"num":"");td.innerHTML=c.render?c.render(row):fmt(row[c.key]);tr.appendChild(td);}});
      tb.appendChild(tr);
    }});
    if(!r.length) tb.innerHTML='<tr><td colspan="'+cols.length+'"><div class="empty">Nothing matches.</div></td></tr>';
    count.textContent=r.length+" of "+rows.length;
    thead.querySelectorAll(".arrow").forEach((a,i)=>a.textContent=cols[i].key===state.sort?(state.dir>0?"▲":"▼"):"");
  }}
  draw();
}}

// ---- Dashboard -------------------------------------------------------------
(function(){{
  const v=$("#v-dashboard");
  const win=DATA.discovered.filter(d=>d.verdict==="winnable"||d.verdict==="contested");
  const due=DATA.calendar.filter(c=>c.state==="list_now");
  const cards=el("div","cards");
  [["Watched terms",m.watched_terms.length,""],
   ["Discovered",DATA.discovered.length,""],
   ["Worth a look",win.length,win.length?"good":""],
   ["Due now",due.length,due.length?"bad":""],
   ["Tracked shops",m.tracked_shops.length,""],
   ["Launches",m.launches??"—",m.launches===0?"warn":""]
  ].forEach(([l,n,cls])=>{{const k=el("div","kpi"+(cls?" "+cls:""));
    k.innerHTML=`<div class="n">${{n}}</div><div class="l">${{l}}</div>`;cards.appendChild(k);}});
  v.appendChild(cards);
  if(m.blockers.length){{
    const b=el("div","block blocked");
    b.innerHTML='<h2>Blocked on you</h2><ul>'+m.blockers.map(x=>`<li>${{x.text}}</li>`).join("")+'</ul>';
    v.appendChild(b);
  }}
  if(due.length){{
    const b=el("div","block");
    b.innerHTML='<h2>Due now</h2><ul>'+due.map(c=>`<li><strong>${{c.moment}}</strong> — list by ${{c.list_by}}`
      +(c.terms.length?" · "+c.terms.map(t=>t.term).join(", "):" · nothing aimed at it")+'</li>').join("")+'</ul>';
    v.appendChild(b);
  }}
  const wb=el("div","block");
  wb.innerHTML='<h2>Top winnable — terms you did not type</h2>';
  if(win.length){{const ul=el("ul");ul.innerHTML=win.slice(0,8).map(w=>
    `<li><strong>${{w.term}}</strong> <span class="ratio win">${{(w.demand_per_listing||0).toFixed(3)}}</span> `
    +`<span class="sub">${{w.verdict}} · from ${{w.seed}}</span></li>`).join("");wb.appendChild(ul);}}
  else wb.innerHTML+='<p class="sub">Nothing winnable in the pool yet.</p>';
  v.appendChild(wb);
}})();

// ---- Discover --------------------------------------------------------------
table($("#v-discover"), DATA.discovered, [
  {{key:"term",label:"Term",render:r=>`${{r.term}}`+(r.moment?`<br><span class="season">${{r.moment}} · list by ${{r.list_by}}</span>`:"")}},
  {{key:"demand_per_listing",label:"Demand/listing",num:true,render:r=>r.demand_per_listing==null?"—":`<span class="ratio ${{r.verdict==='wall'?'wall':'win'}}">${{r.demand_per_listing.toFixed(3)}}</span>`}},
  {{key:"verdict",label:"Verdict",render:r=>`<span class="pill ${{r.verdict}}">${{r.verdict||"—"}}</span>`}},
  {{key:"volume",label:"Searches",num:true,render:r=>fmt(r.volume)}},
  {{key:"supply",label:"Listings",num:true,render:r=>fmt(r.supply)}},
  {{key:"timing",label:"Timing",render:r=>r.timing==="seasonal"?'<span class="season">seasonal</span>':'<span class="sub">evergreen</span>'}},
  {{key:"seed",label:"From seed",render:r=>`<span class="sub">${{r.seed||""}}</span>`}},
], {{sort:"demand_per_listing", limit:1170, filters:[
  {{key:"verdict",label:"Verdict",options:["winnable","contested","wall"]}},
  {{key:"timing",label:"Timing",options:["seasonal","evergreen"]}},
]}});

// ---- Etsy demand -----------------------------------------------------------
table($("#v-etsy"), DATA.keywords, [
  {{key:"term",label:"Term",render:r=>r.term+' <span class="sub">'+age(r.measured_at)+'</span>'}},
  {{key:"demand_per_listing",label:"Demand/listing",num:true,render:r=>r.demand_per_listing==null?"—":`<span class="ratio ${{r.is_wall?'wall':'win'}}">${{r.demand_per_listing.toFixed(3)}}</span>`}},
  {{key:"volume",label:"Searches",num:true,render:r=>fmt(r.volume)+" "+sparkline(r.series)}},
  {{key:"supply",label:"Listings",num:true,render:r=>fmt(r.supply)}},
  {{key:"cvr",label:"CVR",num:true,render:r=>r.cvr==null?"—":r.cvr.toFixed(5)+(r.cvr_basis!=="measured"?' <span class="deriv">default</span>':"")}},
  {{key:"price_low",label:"Price band",render:r=>r.price_low?`$${{r.price_low}}–${{r.price_high}}`:'<span class="sub">none</span>'}},
  {{key:"readings",label:"Readings",num:true}},
], {{sort:"demand_per_listing"}});

// ---- Pinterest -------------------------------------------------------------
(function(){{
  const v=$("#v-pinterest"), p=DATA.pinterest;
  v.innerHTML='<div class="block"><h2>Dated moments — the timing engine</h2>'
    +(p.moments.length?'<div class="twrap"><table><thead><tr><th>Moment</th><th>List by</th><th>Takeoff</th><th>Peak</th><th>Phase</th></tr></thead><tbody>'
      +p.moments.map(mo=>`<tr><td><strong>${{mo.name}}</strong></td><td class="num">${{mo.list_by||"—"}}</td><td class="num">${{mo.takeoff||"—"}}</td><td class="num">${{mo.peak||"—"}}</td><td><span class="sub">${{mo.phase||"—"}}</span></td></tr>`).join("")
      +'</tbody></table>':'<p class="sub">No moments — run the Pinterest bridge.</p>')+'</div>';
  const tv=el("div","block"); tv.innerHTML='<h2>Rising topics — what is trending, and its colour</h2>';
  v.appendChild(tv);
  table(tv, p.topics, [
    {{key:"name",label:"Topic"}},
    {{key:"velocity",label:"Velocity",num:true,render:r=>r.velocity==null?"—":r.velocity.toFixed(2)}},
    {{key:"growth_mom",label:"MoM",num:true,render:r=>r.growth_mom==null?"—":r.growth_mom.toFixed(2)}},
    {{key:"color",label:"Dominant colour",render:r=>r.color?`<span class="swatch" style="background:${{r.color}}"></span>${{r.color}} <span class="sub">${{pct(r.color_share)}}</span>`:"—"}},
  ], {{sort:"velocity"}});
}})();

// ---- Calendar (the combination) --------------------------------------------
(function(){{
  const v=$("#v-calendar");
  const b=el("div","block");
  b.innerHTML='<h2>Pinterest timing × Etsy demand</h2>'
    +'<div class="twrap"><table><thead><tr><th>Moment</th><th>State</th><th>List by</th><th>Peak</th><th>Watched terms</th></tr></thead><tbody>'
    +DATA.calendar.map(c=>`<tr><td><strong>${{c.moment}}</strong>${{c.is_late?' <span class="pill now">late</span>':""}}</td>`
      +`<td><span class="pill ${{c.state}}">${{c.state.replace("_"," ")}}</span></td>`
      +`<td class="num">${{c.list_by}}</td><td class="num">${{c.peak||"—"}}</td>`
      +`<td>${{c.terms.length?c.terms.map(t=>`<span class="chip">${{t.term}}${{t.is_wall?" ⚠":""}}</span>`).join(""):'<span class="sub">nothing aimed at it</span>'}}</td></tr>`).join("")
    +'</tbody></table></div>';
  v.appendChild(b);
}})();

// ---- Competitors -----------------------------------------------------------
(function(){{
  const v=$("#v-shops");
  if(!DATA.shops.length){{v.innerHTML='<div class="empty">No shops tracked.</div>';return;}}
  DATA.shops.forEach(s=>{{
    const b=el("div","block");
    b.innerHTML=`<h2>${{s.shop}}</h2><p class="sub">${{fmt(s.lifetime_sales)}} lifetime sales · `
      +`${{fmt(s.reviews)}} reviews · sales/day ${{s.sales_per_day_bound!=null?"fewer than "+Math.round(s.sales_per_day_bound):"—"}} `
      +`<span class="deriv">bound, counter is quantised</span></p>`;
    if(s.listings.length){{
      b.innerHTML+='<div class="twrap"><table><thead><tr><th>Their listing (matches a term you watch)</th><th>Matches</th><th class="num">Reviews/day</th><th class="num">Reviews</th></tr></thead><tbody>'
        +s.listings.map(l=>`<tr><td>${{(l.title||"").slice(0,64)}}</td><td><span class="chip">${{l.matched_term}}</span></td>`
          +`<td class="num">${{l.velocity_basis==="measured"?l.review_velocity.toFixed(2)+' <span class="deriv">floor</span>':'<span class="sub">'+(l.velocity_basis||"").replace(/_/g," ")+'</span>'}}</td>`
          +`<td class="num">${{fmt(l.reviews)}}</td></tr>`).join("")+'</tbody></table></div>';
    }} else b.innerHTML+='<p class="sub">No listing matches a watched term.</p>';
    v.appendChild(b);
  }});
}})();
</script>
</body></html>'''


def write(out_dir=OUT_DIR, snapshot=None, db_path="market_intelligence.db", now=None):
    from etsy.ui import app_data
    snapshot = snapshot if snapshot is not None else app_data.build_snapshot(db_path, now)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "app.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(snapshot, now=now))
    return path


def main():
    print(f"[+] {write()}   <- open in a browser; it is the whole app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
