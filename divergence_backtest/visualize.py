from __future__ import annotations

import json
from pathlib import Path

from .engine import BacktestResult, Quote


def _downsample_quotes(quotes: list[Quote], max_points: int) -> list[Quote]:
    if len(quotes) <= max_points:
        return quotes
    step = (len(quotes) - 1) / (max_points - 1)
    indexes = sorted({round(index * step) for index in range(max_points)})
    return [quotes[index] for index in indexes]


def write_signal_chart(
    quotes: list[Quote],
    result: BacktestResult,
    path: str | Path,
    max_points: int = 3_000,
) -> None:
    sampled = _downsample_quotes(quotes, max_points)
    payload = {
        "quotes": [
            {
                "t": quote.timestamp_ms,
                "s": quote.spot_mid,
                "f": quote.futures_mid,
            }
            for quote in sampled
        ],
        "signals": [
            {
                "event": signal.event_id,
                "t": signal.timestamp_ms,
                "mark": signal.mark,
                "direction": signal.direction,
                "reason": signal.reason,
                "s": signal.spot_mid,
                "f": signal.futures_mid,
                "basis": signal.basis_bps,
                "residual": signal.residual_bps,
            }
            for signal in result.signals
        ],
        "summary": result.summary(),
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    html = _HTML.replace("__PAYLOAD__", data)
    Path(path).write_text(html, encoding="utf-8")


_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DOGE Spot/Perpetual Signal Marks</title>
<style>
body{margin:0;background:#0d1117;color:#e6edf3;font:14px system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:24px}.panel{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
h1{font-size:22px;margin:0 0 8px}.muted{color:#8b949e}.legend{display:flex;flex-wrap:wrap;gap:14px;margin:12px 0}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}.stat{display:inline-block;margin-right:18px}
canvas{width:100%;height:650px;background:#0d1117;border-radius:6px;cursor:crosshair}.tip{min-height:48px;white-space:pre-wrap}
</style>
</head>
<body><main>
<section class="panel"><h1>DOGEUSDT Spot / Futures Signal Marks</h1>
<div class="muted">Only <b>confirmed</b> is an actionable signal. Detected events are observations.</div>
<div id="stats"></div>
<div class="legend">
<span><i class="dot" style="background:#58a6ff"></i>Spot</span>
<span><i class="dot" style="background:#f2cc60"></i>Futures</span>
<span><i class="dot" style="background:#8b949e"></i>Detected</span>
<span><i class="dot" style="background:#a371f7"></i>Candidate</span>
<span><i class="dot" style="background:#3fb950"></i>Confirmed / Entry</span>
<span><i class="dot" style="background:#f85149"></i>Rejected / Stop</span>
<span><i class="dot" style="background:#d29922"></i>Exit</span>
</div></section>
<section class="panel"><canvas id="chart"></canvas><div id="tip" class="tip muted">Move over a signal marker for details.</div></section>
</main>
<script>
const data=__PAYLOAD__, canvas=document.getElementById("chart"), ctx=canvas.getContext("2d"), tip=document.getElementById("tip");
const colors={detected:"#8b949e",candidate:"#a371f7",confirmed:"#3fb950",entry:"#3fb950",rejected:"#f85149",exit_target:"#d29922",exit_stop:"#f85149",exit_time:"#d29922",open_end_of_data:"#f85149"};
function size(){canvas.width=canvas.clientWidth*devicePixelRatio;canvas.height=canvas.clientHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0)}
function draw(){
 const W=canvas.clientWidth,H=canvas.clientHeight,p={l:70,r:24,t:24,b:48},q=data.quotes;
 if(!q.length)return; const ts=q.map(x=>x.t), ps=q.flatMap(x=>[x.s,x.f]);
 const t0=Math.min(...ts),t1=Math.max(...ts),lo=Math.min(...ps),hi=Math.max(...ps),pad=(hi-lo||hi*.001)*.08;
 const x=t=>p.l+(t-t0)/(t1-t0||1)*(W-p.l-p.r), y=v=>p.t+(hi+pad-v)/(hi-lo+2*pad)*(H-p.t-p.b);
 ctx.clearRect(0,0,W,H);ctx.strokeStyle="#30363d";ctx.fillStyle="#8b949e";ctx.font="12px system-ui";
 for(let i=0;i<=5;i++){let yy=p.t+i*(H-p.t-p.b)/5;ctx.beginPath();ctx.moveTo(p.l,yy);ctx.lineTo(W-p.r,yy);ctx.stroke();let v=hi+pad-i*(hi-lo+2*pad)/5;ctx.fillText(v.toFixed(6),5,yy+4)}
 function line(key,color){ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();q.forEach((d,i)=>{const xx=x(d.t),yy=y(d[key]);i?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy)});ctx.stroke()}
 line("s","#58a6ff");line("f","#f2cc60");window.points=[];
 data.signals.forEach(m=>{const xx=x(m.t),yy=y(m.f),c=colors[m.mark]||"#fff",r=m.mark==="confirmed"?7:m.mark==="entry"?6:4;ctx.fillStyle=c;ctx.beginPath();ctx.arc(xx,yy,r,0,Math.PI*2);ctx.fill();points.push({...m,x:xx,y:yy,r:r+5})});
 canvas.onmousemove=e=>{const r=canvas.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;let hit=points.find(z=>Math.hypot(z.x-mx,z.y-my)<=z.r);tip.textContent=hit?`Event #${hit.event} | ${hit.mark.toUpperCase()} | ${hit.direction.toUpperCase()}\\n${hit.reason}\\nBasis: ${hit.basis.toFixed(3)} bps | Residual: ${hit.residual.toFixed(3)} bps`:"Move over a signal marker for details."}
}
document.getElementById("stats").innerHTML=`<p><span class=stat>Detected: <b>${data.summary.marks_by_type?.detected||0}</b></span><span class=stat>Confirmed: <b>${data.summary.confirmed_signals||0}</b></span><span class=stat>Trades: <b>${data.summary.trades||0}</b></span><span class=stat>Win rate: <b>${((data.summary.win_rate||0)*100).toFixed(2)}%</b></span></p>`;
addEventListener("resize",()=>{size();draw()});size();draw();
</script></body></html>"""

