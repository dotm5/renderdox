"""Offline reports: escaped source data, no CDN, no local HTTP server."""
import copy
import html
import json


STYLE = """
body{margin:0;background:#131820;color:#e9edf5;font:15px system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:32px}
h1{font-size:30px}p{line-height:1.6;color:#b9c6d8}input,select,button{padding:9px;background:#222c3b;color:#edf2fa;border:1px solid #61728b;border-radius:5px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid #344052}th{position:sticky;top:0;background:#222c3b}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1d2531;padding:16px}details{margin:10px 0;padding:10px;border:1px solid #344052;border-radius:5px}
summary{cursor:pointer}img{max-width:100%}a{color:#86c9ff}.bar{height:13px;background:#65b6ec;min-width:0}.controls{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}
"""


def document(title, body, script=""):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="icon" href="data:,"><title>' + html.escape(title) + '</title><style>' + STYLE + '</style><main><h1>' + html.escape(title) + '</h1>' + body + '</main>' + script + '</html>'


def json_text(value):
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def profile_report(payload, title):
    payload = copy.deepcopy(payload)
    for event in payload["events"]:
        for counter in event["counters"]:
            if isinstance(counter.get("value"), int) and abs(counter["value"]) > 2**53 - 1:
                counter["value"] = str(counter["value"])
                counter["displayNote"] = "Exact integer preserved; outside JavaScript numeric range"
    # '<' is escaped even inside application/json to prevent </script> breakout.
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    body = '''<p>GPU replay counter measurements. Horizontal widths show relative metric weight, not start/end timestamps or parallel GPU execution. Marker sums cover measured events only. Missing values remain unknown.</p>
<div class="controls"><label>View <select id="view"><option value="ranking">Metric ranking</option><option value="sequence">Event order / cumulative measurements</option></select></label><label>Counter <select id="metric"></select></label><label>Filter name / EID <input id="filter"></label><label>Minimum EID <input id="minimum" type="number" min="0"></label><label>Maximum EID <input id="maximum" type="number" min="0"></label></div>
<p id="coverage"></p><details><summary>Measurement identity and counter definitions</summary><pre id="identity"></pre></details>
<div id="hierarchy"></div><h2 id="view-title">Measured event ranking</h2><p id="sequence-note" hidden>Cumulative samples in EID order for the current filter. Gaps and GPU overlap are not measured; this axis does not represent elapsed frame time. Unknown and nonnumeric values do not advance the axis.</p><table><thead><tr><th>EID</th><th>Marker / event</th><th>Value</th><th id="axis-title">Metric weight</th><th>Evidence</th></tr></thead><tbody id="rows"></tbody></table><button id="more">Show more</button>
<details><summary>Selected event data</summary><pre id="detail">Select an event.</pre></details>'''
    script = '<script type="application/json" id="data">' + data + '</script><script>' + r'''
const data=JSON.parse(document.getElementById('data').textContent), $=id=>document.getElementById(id);
const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=String(value);return e};
for(const c of data.counters){const o=text('option',c.name+' ('+c.unit+')');o.value=c.counterId;$('metric').append(o)}
$('identity').textContent=JSON.stringify({identity:data.identity,counters:data.counters,interpretation:data.interpretation},null,2);
let page=200;
const value=(e,id)=>{const c=e.counters.find(x=>x.counterId===id);return c&&c.valid&&Number.isFinite(c.value)?c.value:null};
function render(){
 const id=Number($('metric').value), q=$('filter').value.toLowerCase(), lo=$('minimum').value,hi=$('maximum').value;
 const events=data.events.filter(e=>{const a=e.action||{};const label=((a.ancestry||[]).map(x=>x.name).join('/')+'/'+(a.name||'')+' '+e.eventId).toLowerCase();return !e.aggregateAction&&label.includes(q)&&(!lo||e.eventId>=Number(lo))&&(!hi||e.eventId<=Number(hi))});
 const sequence=$('view').value==='sequence';events.sort(sequence?((a,b)=>a.eventId-b.eventId):((a,b)=>(value(b,id)??-1)-(value(a,id)??-1)||a.eventId-b.eventId));
 $('view-title').textContent=sequence?'Event order / cumulative measurements':'Measured event ranking';$('sequence-note').hidden=!sequence;$('axis-title').textContent=sequence?'Cumulative selected value':'Metric weight';
 const total=events.reduce((s,e)=>s+Math.max(0,value(e,id)||0),0);$('coverage').textContent=events.length+' measured events match; '+events.filter(e=>value(e,id)===null).length+' missing selected values. Showing '+Math.min(page,events.length)+'.';
 let cumulative=0;$('rows').replaceChildren();for(const e of events.slice(0,page)){const a=e.action||{},v=value(e,id),raw=e.counters.find(x=>x.counterId===id),r=document.createElement('tr');r.append(text('td',e.eventId),text('td',(a.ancestry||[]).map(x=>x.name).concat(a.name||'unknown').join(' / ')),text('td',v===null?(raw&&raw.displayNote?raw.value+' (exact; no numeric bar)':'unknown'):v));const cell=document.createElement('td'),bar=document.createElement('div');bar.className='bar';bar.style.width=(total&&v!==null?Math.max(0,v)/total*100:0)+'%';if(sequence){bar.style.marginLeft=(total?cumulative/total*100:0)+'%';const start=cumulative;if(v!==null)cumulative+=Math.max(0,v);cell.append(text('small',v===null?'unknown':start.toPrecision(7)+' → '+cumulative.toPrecision(7)));r.dataset.cumulativeStart=String(start);r.dataset.cumulativeEnd=String(cumulative)}cell.append(bar);r.append(cell);const b=text('button','Inspect');b.onclick=()=>{$('detail').textContent=JSON.stringify(e,null,2)};const c=document.createElement('td');c.append(b);r.append(c);$('rows').append(r)}
 $('more').hidden=page>=events.length;
 // Each measured EID contributes once to each ancestor. Full paths use IDs,
 // so identically named sibling/nested markers are not merged.
 const groups=new Map();for(const e of events){const ancestry=(e.action||{}).ancestry||[];let ids=[];for(const a of ancestry){ids.push(a.eventId);const k=ids.join('/');if(!groups.has(k))groups.set(k,{name:a.name,id:a.eventId,parent:ids.slice(0,-1).join('/'),count:0,ms:0});const g=groups.get(k);g.count++;if(Number.isFinite(e.durationMs))g.ms+=e.durationMs}}
 $('hierarchy').replaceChildren();const nodes=new Map();for(const [k,g] of [...groups].sort((a,b)=>a[0].split('/').length-b[0].split('/').length||a[1].id-b[1].id)){const d=document.createElement('details');d.append(text('summary','EID '+g.id+' '+g.name+' — '+g.count+' measured events; '+g.ms.toFixed(4)+' ms measured duration sum'));(nodes.get(g.parent)||$('hierarchy')).append(d);nodes.set(k,d)}
 if(!groups.size)$('hierarchy').append(text('p','No marker hierarchy recorded for the matching events.'));
}
for(const id of ['view','metric','filter','minimum','maximum'])$(id).oninput=()=>{page=200;render()};$('more').onclick=()=>{page+=200;render()};render();
''' + '</script>'
    return document(title, body, script)


def evidence_report(content, copied, title):
    body = '<p>Saved capture evidence. Images are opaque RGB display previews; stored resource alpha is not browser opacity. Original image bytes and display transforms remain in analysis.json and attached artifacts.</p>'
    body += '<details><summary>Capture identity and summary</summary><pre>' + json_text({"capture": content["capture"], "summary": content["summary"]}) + '</pre></details>'
    body += '<h2>Annotations</h2>'
    for note in content.get("annotations", []):
        body += '<p>' + html.escape(str(note.get("note", ""))) + '</p>'
    for evidence in content.get("evidence", []):
        action = evidence["action"]
        body += '<details><summary>' + html.escape('EID %s: %s' % (action["eventId"], action["name"])) + '</summary>'
        for preview in evidence.get("previews", []):
            image = preview.get("displayImage", preview["image"])
            body += '<img loading="lazy" alt="' + html.escape(preview["resourceId"], quote=True) + '" src="' + html.escape(image["path"], quote=True) + '">'
        body += '<pre>' + json_text(evidence) + '</pre></details>'
    body += '<h2>Attached artifacts</h2><ul>'
    for key, path in copied.items():
        body += '<li><a href="' + html.escape(path, quote=True) + '">' + html.escape(key) + '</a></li>'
    return document(title, body + '</ul><p><a href="analysis.json">Full analysis JSON</a></p>')
