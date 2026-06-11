#!/usr/bin/env python3
"""Local live-trading dashboard — performance and risk at a glance.

Serves a single auto-refreshing page from the status files that run_live.py
writes (data/live_status.json every 30s, live_status_history.jsonl).
Zero dependencies, read-only, never touches credentials or the exchange.

Usage:
    py -3 scripts/dashboard.py            # http://localhost:8787
    py -3 scripts/dashboard.py --port 9000

Polymarket's portfolio page remains ground truth for wallet balance and
on-exchange positions; this shows the strategy's own real-time view.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "live_status.json"
HISTORY = ROOT / "data" / "live_status_history.jsonl"

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Polymarket MM — Live</title>
<style>
 body{background:#0d1117;color:#c9d1d9;font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:0;padding:20px}
 h1{font-size:18px;margin:0 0 4px} .sub{color:#8b949e;font-size:12px;margin-bottom:16px}
 .badge{display:inline-block;padding:2px 10px;border-radius:10px;font-weight:700;font-size:12px;margin-right:8px}
 .live{background:#da3633;color:#fff}.dry{background:#1f6feb;color:#fff}
 .stale{background:#9e6a03;color:#fff;display:none}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
 .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px}
 .card .k{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
 .card .v{font-size:24px;font-weight:700;margin-top:2px}
 .pos{color:#3fb950}.neg{color:#f85149}.warn{color:#d29922}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th{color:#8b949e;text-align:left;padding:6px 8px;border-bottom:1px solid #30363d;font-weight:600}
 td{padding:5px 8px;border-bottom:1px solid #21262d}
 tr:hover{background:#161b22}
 #spark{width:100%;height:90px;background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:18px}
 .caps{font-size:12px;color:#8b949e;margin-bottom:14px}
 .bar{height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin-top:3px}
 .bar i{display:block;height:100%;background:#1f6feb}
 a{color:#58a6ff}
</style></head><body>
<h1>Polymarket MM
  <span id="mode" class="badge dry">…</span>
  <span id="halted" class="badge live" style="display:none">HALTED</span>
  <span id="stalebadge" class="badge stale">STATUS STALE — is run_live running?</span>
</h1>
<div class="sub">last status: <span id="ts">…</span> · refreshes every 10s ·
  ground truth: <a href="https://polymarket.com/portfolio" target="_blank">Polymarket portfolio</a></div>

<div class="grid">
 <div class="card"><div class="k">Session PnL</div><div class="v" id="pnl">…</div></div>
 <div class="card"><div class="k">Fills</div><div class="v" id="fills">…</div></div>
 <div class="card"><div class="k">Orders placed</div><div class="v" id="orders">…</div></div>
 <div class="card"><div class="k">Unhedged</div><div class="v" id="unhedged">…</div></div>
 <div class="card"><div class="k">Unroutable</div><div class="v" id="unroutable">…</div></div>
 <div class="card"><div class="k">Errors</div><div class="v" id="errors">…</div></div>
 <div class="card"><div class="k">Markets</div><div class="v" id="markets">…</div></div>
</div>

<canvas id="spark" width="1200" height="90"></canvas>
<div class="caps" id="caps"></div>

<table><thead><tr>
 <th>Market</th><th>PnL</th><th>Fills</th><th>Hedged</th><th>Unhedged</th>
 <th>Long $</th><th>Short $</th><th>FV</th><th></th>
</tr></thead><tbody id="rows"></tbody></table>

<script>
async function tick(){
  let s;
  try{ s = await (await fetch('/status')).json(); }catch(e){ return; }
  const stale = (Date.now() - Date.parse(s.ts)) > 90000;
  document.getElementById('stalebadge').style.display = stale ? 'inline-block' : 'none';
  const mode = document.getElementById('mode');
  mode.textContent = s.mode; mode.className = 'badge ' + (s.mode === 'LIVE' ? 'live' : 'dry');
  document.getElementById('ts').textContent = s.ts;
  const pnl = document.getElementById('pnl');
  pnl.textContent = (s.total_pnl >= 0 ? '+$' : '-$') + Math.abs(s.total_pnl).toFixed(2);
  pnl.className = 'v ' + (s.total_pnl >= 0 ? 'pos' : 'neg');
  document.getElementById('fills').textContent = s.total_fills;
  document.getElementById('orders').textContent = s.orders_placed;
  const uh = document.getElementById('unhedged');
  uh.textContent = s.open_unhedged; uh.className = 'v ' + (s.open_unhedged > 0 ? 'warn' : '');
  const ur = document.getElementById('unroutable');
  ur.textContent = s.unroutable; ur.className = 'v ' + (s.unroutable > 0 ? 'neg' : '');
  const er = document.getElementById('errors');
  er.textContent = s.errors; er.className = 'v ' + (s.errors > 0 ? 'warn' : '');
  document.getElementById('markets').textContent = s.markets;

  const anyHalt = (s.per_market || []).some(m => m.halted);
  document.getElementById('halted').style.display = anyHalt ? 'inline-block' : 'none';

  const p = s.portfolio || {};
  const used = p.long_term_notional || 0, max = p.max_long_term_notional || 1;
  document.getElementById('caps').innerHTML =
    `Long-term cap: $${used.toFixed(0)} / $${max.toFixed(0)} (${(p.long_term_pct||0).toFixed(1)}%)` +
    `<div class="bar"><i style="width:${Math.min(100, used/max*100)}%"></i></div>`;

  const rows = (s.per_market || []).map(m => `<tr>
    <td>${m.market}</td>
    <td class="${m.pnl >= 0 ? 'pos' : 'neg'}">${m.pnl >= 0 ? '+' : ''}${m.pnl.toFixed(2)}</td>
    <td>${m.fills}</td><td>${m.takers_filled}/${m.takers_sent}</td>
    <td class="${m.open_unhedged > 0 ? 'warn' : ''}">${m.open_unhedged}</td>
    <td>${m.long_notional.toFixed(0)}</td><td>${m.short_notional.toFixed(0)}</td>
    <td>${m.last_fv === null ? '—' : m.last_fv.toFixed(3)}</td>
    <td class="neg">${m.halted ? 'HALTED' : ''}</td></tr>`).join('');
  document.getElementById('rows').innerHTML = rows;

  try{
    const h = await (await fetch('/history')).json();
    const c = document.getElementById('spark'), ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
    if (h.length > 1){
      const vals = h.map(r => r.total_pnl);
      const min = Math.min(0, ...vals), max2 = Math.max(0.01, ...vals);
      ctx.beginPath(); ctx.strokeStyle = '#3fb950'; ctx.lineWidth = 1.5;
      vals.forEach((v, i) => {
        const x = i / (vals.length - 1) * (c.width - 8) + 4;
        const y = c.height - 6 - (v - min) / (max2 - min) * (c.height - 12);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.stroke();
      const zy = c.height - 6 - (0 - min) / (max2 - min) * (c.height - 12);
      ctx.strokeStyle = '#30363d'; ctx.setLineDash([3,3]);
      ctx.beginPath(); ctx.moveTo(0, zy); ctx.lineTo(c.width, zy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#8b949e'; ctx.font = '11px system-ui';
      ctx.fillText('session PnL (' + h.length + ' samples, 30s each)', 8, 14);
    }
  }catch(e){}
}
tick(); setInterval(tick, 10000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/status":
            try:
                self._send(200, STATUS.read_bytes(), "application/json")
            except OSError:
                self._send(200, b'{"ts":"1970-01-01T00:00:00","mode":"NO DATA",'
                                b'"markets":0,"total_pnl":0,"total_fills":0,'
                                b'"orders_placed":0,"open_unhedged":0,'
                                b'"unroutable":0,"errors":0,"per_market":[]}',
                           "application/json")
        elif self.path == "/history":
            rows = []
            try:
                lines = HISTORY.read_text().splitlines()[-2880:]  # ~24h of 30s rows
                rows = [json.loads(l) for l in lines if l.strip()]
            except OSError:
                pass
            self._send(200, json.dumps(rows).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    print(f"Dashboard: http://localhost:{args.port}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
