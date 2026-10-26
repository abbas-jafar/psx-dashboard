import json, os

PRIVATE_KEYS = ("qty", "avg_cost", "value", "cost", "pl", "day_change")


def scrub(d):
    d = json.loads(json.dumps(d))
    if d.get("show_rs"):
        return d
    for r in d["holdings"] + d["watchlist"]:
        for k in PRIVATE_KEYS:
            r.pop(k, None)
        r["held"] = r.get("weight_pct", 0) > 0
    for k in ("value", "cost", "pl", "day_change"):
        d["totals"].pop(k, None)
    return d


def write(docs, data):
    os.makedirs(docs, exist_ok=True)
    payload = json.dumps(scrub(data)).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", data["title"])
    with open(os.path.join(docs, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#faf9f7;--panel:#fff;--fg:#1d1c1a;--mut:#6b6862;--line:#e5e2dc;--ok:#1a7f4b;--bad:#c23a2b;--warn:#b7791f;--acc:#3b6fb6;--tgt:#cfcac1}
@media(prefers-color-scheme:dark){:root{--bg:#161513;--panel:#1f1e1b;--fg:#ecebe8;--mut:#a09c94;--line:#34322d;--ok:#4cc38a;--bad:#ef7b6c;--warn:#e0b04c;--acc:#7aa7e6;--tgt:#4a473f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font:400 28px/1.2 Georgia,serif;margin:0}h2{font-size:17px;margin:34px 0 4px;font-weight:600}
.sub{color:var(--mut);font-size:13px;margin:4px 0 0}.note{color:var(--mut);font-size:13px;margin:0 0 10px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.chip{font-size:12px;border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--mut)}.chip.ok::before{content:"● ";color:var(--ok)}.chip.bad::before{content:"● ";color:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:14px}
.card,.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.tile .l{font-size:12px;color:var(--mut)}.tile .b{font:400 26px Georgia,serif;margin:2px 0}
.pos{color:var(--ok)}.neg{color:var(--bad)}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th{font-size:12px;color:var(--mut);text-align:left;font-weight:500;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}.n{text-align:right}.scroll{overflow-x:auto}
.pill{display:inline-block;border:1px solid currentColor;border-radius:99px;padding:0 8px;font-size:12px;white-space:nowrap}
.review{color:var(--bad)}.trim,.watch,.sector{color:var(--warn)}.opportunity{color:var(--ok)}.info{color:var(--mut)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:12px}
.empty{color:var(--mut);font-size:13px}svg{width:100%;height:auto;display:block}svg text{fill:var(--fg);font-size:11px}svg .m{fill:var(--mut)}
a{color:var(--acc)}.li{padding:8px 0;border-bottom:1px solid var(--line)}.li:last-child{border:0}.tag{font-size:11px;color:var(--mut);margin-right:6px}
.btns{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}.btn{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:6px 12px;font-size:13px;color:var(--fg);text-decoration:none;cursor:pointer}
</style></head><body><div class="wrap">
<h1 id="title"></h1><p class="sub" id="gen"></p>
<div class="btns"><a class="btn" href="" onclick="location.reload();return false">Reload page</a><a class="btn" id="runlink" href="#" target="_blank" rel="noopener">Refresh data now</a></div>
<div class="chips" id="chips"></div>
<div class="tiles" id="tiles"></div>
<h2>Alerts and opportunities</h2><p class="note">Rule triggers. Prompts to check, not instructions to trade.</p>
<div class="card scroll" id="alerts"></div>
<h2>Charts</h2>
<div class="grid2"><div class="card"><b>Sector mix against target</b><div id="c-sector"></div></div>
<div class="card"><b>Where each price sits in its 52-week range</b><p class="note">Left is the 52-week low, right is the high.</p><div id="c-range"></div></div>
<div class="card"><b>Gain or loss since you bought</b><div id="c-pl"></div></div>
<div class="card"><b>Dividend yield against P/E</b><p class="note">Top-left is the cheap, high-yield corner. Hollow dots are watchlist.</p><div id="c-yp"></div></div></div>
<h2>What happened</h2><p class="note">Your stocks first, then the wider market.</p>
<div class="grid2"><div class="card"><b>Your stocks and watchlist</b><div id="a-mine"></div></div><div class="card"><b>Market, regulator and PSX notices</b><div id="a-mkt"></div></div></div>
<div class="card" style="margin-top:12px"><b>Headlines</b><div id="news"></div></div>
<h2>Holdings</h2><div class="card scroll" id="hold"></div>
<h2>Watchlist</h2><p class="note">Blank yield or P/E means the dividend or EPS has not been entered in config/watchlist.csv.</p><div class="card scroll" id="watch"></div>
<p class="note" style="margin-top:30px">Dividend and EPS figures are typed into the config files and go stale; update them after each result. Not investment advice.</p>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
const f1=v=>v==null?'—':(Math.round(v*10)/10).toFixed(1),pct=v=>v==null?'—':(v>=0?'+':'−')+f1(Math.abs(v))+'%',cl=v=>v==null?'':v>=0?'pos':'neg';
const rs=v=>'Rs '+Math.round(v).toLocaleString('en-US'),NS='http://www.w3.org/2000/svg';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('title').textContent=D.title;$('gen').textContent='Updated '+D.generated;
const repo=(location.hostname.endsWith('github.io'))?'https://github.com/'+location.hostname.split('.')[0]+'/'+(location.pathname.split('/')[1]||'')+'/actions':'#';$('runlink').href=repo;
$('chips').innerHTML=D.status.map(s=>`<span class="chip ${s.ok?'ok':'bad'}">${esc(s.name)}: ${esc(s.note)}</span>`).join('');
const T=D.totals,I=D.index,held=D.holdings.filter(r=>D.show_rs?r.qty>0:r.held);
const tile=(l,b,s,c)=>`<div class="tile"><div class="l">${l}</div><div class="b ${c||''}">${b}</div><div class="sub">${s||''}</div></div>`;
let tl=[];
if(D.show_rs)tl.push(tile('Portfolio value',rs(T.value),T.n_held+' holdings'),tile('Change today',(T.day_change>=0?'+':'−')+rs(Math.abs(T.day_change)),pct(T.day_change_pct),cl(T.day_change)),tile('Gain or loss',(T.pl>=0?'+':'−')+rs(Math.abs(T.pl)),pct(T.pl_pct)+' on cost',cl(T.pl)));
else tl.push(tile('Change today',pct(T.day_change_pct),'portfolio',cl(T.day_change_pct)),tile('Gain or loss on cost',pct(T.pl_pct),T.n_held+' holdings',cl(T.pl_pct)));
tl.push(tile('KSE-100',I?I.level.toLocaleString('en-US',{maximumFractionDigits:0}):'—',I&&I.change_pct!=null?pct(I.change_pct):'not retrieved',I?cl(I.change_pct):''),tile('Alerts',D.alerts.filter(a=>a.kind!=='opportunity').length,D.alerts.filter(a=>a.kind==='opportunity').length+' opportunities'));
$('tiles').innerHTML=tl.join('');
$('alerts').innerHTML=D.alerts.length?`<table><thead><tr><th>Stock</th><th>Rule</th><th>Detail</th><th>Type</th></tr></thead><tbody>${D.alerts.map(a=>`<tr><td><b>${esc(a.ticker)}</b></td><td>${esc(a.rule)}</td><td>${esc(a.detail)}</td><td><span class="pill ${a.severity}">${a.severity}</span></td></tr>`).join('')}</tbody></table>`:'<p class="empty">No rules triggered.</p>';
function svg(w,h){const s=document.createElementNS(NS,'svg');s.setAttribute('viewBox',`0 0 ${w} ${h}`);return s}
function el(p,t,a,txt){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;p.appendChild(e);return e}
// sector
(()=>{const m=D.sector_mix,W=520,rh=40,H=m.length*rh+10,L=96,mx=Math.max(30,...m.map(r=>Math.max(r.current_pct,r.target_pct))),x=v=>L+v/mx*(W-L-40),s=svg(W,H);
m.forEach((r,i)=>{const y=i*rh+4;el(s,'text',{x:L-8,y:y+18,'text-anchor':'end'},r.sector);el(s,'rect',{x:L,y,width:Math.max(0,x(r.target_pct)-L),height:12,rx:3,fill:'var(--tgt)'});el(s,'rect',{x:L,y:y+15,width:Math.max(0,x(r.current_pct)-L),height:12,rx:3,fill:'var(--acc)'});el(s,'text',{x:x(r.target_pct)+5,y:y+10,class:'m'},f1(r.target_pct)+'%');el(s,'text',{x:x(r.current_pct)+5,y:y+25},f1(r.current_pct)+'%')});$('c-sector').appendChild(s);
$('c-sector').insertAdjacentHTML('afterbegin','<p class="note"><span style="color:var(--tgt)">■</span> target &nbsp;<span style="color:var(--acc)">■</span> today</p>')})();
// range
(()=>{const rows=held.concat(D.watchlist.filter(r=>r.range_pos!=null)).filter(r=>r.range_pos!=null).sort((a,b)=>a.range_pos-b.range_pos),W=520,rh=22,H=rows.length*rh+8,L=64,R=W-20,s=svg(W,H);
rows.forEach((r,i)=>{const y=i*rh+4,w=!r.held&&!r.qty;el(s,'text',{x:L-8,y:y+12,'text-anchor':'end'},r.ticker);el(s,'rect',{x:L,y:y+4,width:R-L,height:6,rx:3,fill:'var(--tgt)'});
const c=r.range_pos<=15?'var(--bad)':r.range_pos>=85?'var(--warn)':'var(--acc)';el(s,'circle',{cx:L+(R-L)*Math.max(0,Math.min(100,r.range_pos))/100,cy:y+7,r:5,fill:w?'var(--panel)':c,stroke:c,'stroke-width':2});});$('c-range').appendChild(s)})();
// P/L
(()=>{const rows=held.filter(r=>r.pl_pct!=null).sort((a,b)=>a.pl_pct-b.pl_pct);if(!rows.length)return;const W=520,rh=22,H=rows.length*rh+8,L=64,mx=Math.max(10,...rows.map(r=>Math.abs(r.pl_pct))),mid=L+(W-L-50)/2,k=(W-L-50)/2/mx*0.72,s=svg(W,H);
el(s,'line',{x1:mid,x2:mid,y1:0,y2:H,stroke:'var(--line)'});rows.forEach((r,i)=>{const y=i*rh+4,w=Math.abs(r.pl_pct)*k;el(s,'text',{x:L-8,y:y+12,'text-anchor':'end'},r.ticker);el(s,'rect',{x:r.pl_pct>=0?mid:mid-w,y:y+2,width:w,height:12,rx:2,fill:r.pl_pct>=0?'var(--ok)':'var(--bad)'});el(s,'text',{x:r.pl_pct>=0?mid+w+4:mid-w-4,y:y+12,'text-anchor':r.pl_pct>=0?'start':'end'},pct(r.pl_pct))});$('c-pl').appendChild(s)})();
// yield vs PE
(()=>{const rows=held.concat(D.watchlist).filter(r=>r.pe!=null&&r.yield_pct!=null);if(!rows.length){$('c-yp').innerHTML='<p class="empty">No stocks have both EPS and dividend entered.</p>';return}
const W=520,H=320,L=40,B=30,mx=Math.max(20,...rows.map(r=>r.pe)),my=Math.max(8,...rows.map(r=>r.yield_pct)),x=v=>L+v/mx*(W-L-16),y=v=>H-B-v/my*(H-B-14),s=svg(W,H);
[0,.25,.5,.75,1].forEach(t=>{el(s,'line',{x1:L,x2:W-10,y1:y(my*t),y2:y(my*t),stroke:'var(--line)'});el(s,'text',{x:L-6,y:y(my*t)+4,'text-anchor':'end',class:'m'},f1(my*t)+'%');el(s,'text',{x:x(mx*t),y:H-10,'text-anchor':'middle',class:'m'},f1(mx*t))});el(s,'text',{x:W-10,y:H-1,'text-anchor':'end',class:'m'},'P/E');
el(s,'rect',{x:L,y:y(my),width:x(10)-L,height:y(4)-y(my),fill:'var(--ok)',opacity:.08});
rows.forEach(r=>{const w=!r.held&&!r.qty;el(s,'circle',{cx:x(r.pe),cy:y(r.yield_pct),r:5,fill:w?'var(--panel)':'var(--acc)',stroke:'var(--acc)','stroke-width':2});el(s,'text',{x:x(r.pe)+8,y:y(r.yield_pct)+4},r.ticker)});$('c-yp').appendChild(s)})();
// announcements
const cat=a=>`<span class="tag">${esc(a.category)}</span>`,item=a=>`<div class="li">${esc(a.date)} · <b>${esc(a.ticker||'—')}</b> ${cat(a)}<br>${a.url?`<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title.slice(0,200))}</a>`:esc(a.title.slice(0,200))}</div>`;
const key=['Risk notice','Results','Dividend / book closure','Board meeting','Material information'];
const mine=D.announcements.filter(a=>a.scope!=='market'),mk=D.announcements.filter(a=>a.scope==='market'&&key.includes(a.category)||a.source==='PSX notice'&&a.scope==='market');
$('a-mine').innerHTML=mine.length?mine.map(item).join(''):'<p class="empty">'+(D.status.find(s=>s.name==='Announcements'&&s.ok)?'Nothing new for your stocks in the last 3 days.':'Announcements feed not available this run.')+'</p>';
$('a-mkt').innerHTML=mk.length?mk.slice(0,25).map(item).join(''):'<p class="empty">No key market-wide notices retrieved.</p>';
$('news').innerHTML=D.news.length?D.news.map(n=>`<div class="li">${esc(n.date)} · <a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a></div>`).join(''):'<p class="empty">No headlines retrieved.</p>';
// tables
const th=(a)=>a.map((x,i)=>`<th class="${i?'n':''}">${x}</th>`).join('');
$('hold').innerHTML=`<table><thead><tr><th>Stock</th><th>Sector</th>${D.show_rs?th(['Value']):''}${th(['Weight','Today','Gain/loss','Above 52w low','Yield','P/E','Payout'])}<th>Plan</th></tr></thead><tbody>${held.sort((a,b)=>b.weight_pct-a.weight_pct).map(r=>`<tr><td><b>${r.ticker}</b></td><td>${esc(r.sector)}</td>${D.show_rs?`<td class="n">${rs(r.value)}</td>`:''}<td class="n">${f1(r.weight_pct)}%</td><td class="n ${cl(r.change_pct)}">${pct(r.change_pct)}</td><td class="n ${cl(r.pl_pct)}">${pct(r.pl_pct)}</td><td class="n">${f1(r.vs_low_pct)}%</td><td class="n">${f1(r.yield_pct)}%</td><td class="n">${f1(r.pe)}</td><td class="n">${r.payout_pct==null?'—':Math.round(r.payout_pct)+'%'}</td><td>${esc(r.plan)}</td></tr>`).join('')}</tbody></table>`;
$('watch').innerHTML=`<table><thead><tr><th>Stock</th><th>Sector</th>${th(['Price','Today','52w position','Yield','P/E'])}<th>Note</th></tr></thead><tbody>${D.watchlist.map(r=>`<tr><td><b>${r.ticker}</b></td><td>${esc(r.sector)}</td><td class="n">${r.price==null?'—':r.price.toFixed(2)}</td><td class="n ${cl(r.change_pct)}">${pct(r.change_pct)}</td><td class="n">${r.range_pos==null?'—':Math.round(r.range_pos)+'%'}</td><td class="n">${f1(r.yield_pct)}%</td><td class="n">${f1(r.pe)}</td><td>${esc(r.note)}</td></tr>`).join('')}</tbody></table>`;
</script></body></html>
"""
