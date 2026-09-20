#!/usr/bin/env python3
"""把合并视图做成一个本地网页，方便挂在 Codex 应用右侧面板里看。

同一个时间轴、两个 agent、按角色分列（CLAUDE 绿 / CODEX 品红），
浏览器每 0.8 秒轮询一次增量（``/api/events?since=N``），只读日志文件，
不驱动任何进程。

用法：``python .pair/live.py [--port 8760]``，然后打开 http://127.0.0.1:8760
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import view  # noqa: E402  （.pair/view.py：解析逻辑的唯一来源）

ENTRIES: list = []
LOCK = threading.Lock()
STARTED = time.time()
LAST_ACTIVITY = time.time()
IDLE_EXIT = 900  # 秒；0 = 不自动退出


def touch() -> None:
    global LAST_ACTIVITY
    LAST_ACTIVITY = time.time()


class FileTail:
    """只读地跟随一个文件（或"最新的那个文件"），返回新增的完整行。"""

    def __init__(self, picker):
        self.picker = picker
        self.path = None
        self.offset = 0
        self.buffer = b""
        self.changed = False

    def poll(self) -> list:
        target = self.picker()
        self.changed = target != self.path
        if target != self.path:
            self.path = target
            self.offset = 0
            self.buffer = b""
        if self.path is None or not self.path.exists():
            return []
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except OSError:
            return []
        if not chunk:
            return []
        self.buffer += chunk
        pieces = self.buffer.split(b"\n")
        self.buffer = pieces.pop()
        return [raw.decode("utf-8", errors="replace").strip() for raw in pieces if raw.strip()]


def collect_loop() -> None:
    """后台线程：每 0.35 秒把两个源的新事件追加进 ENTRIES（同一时间轴）。"""
    claude = FileTail(view.newest_turn_file)
    codex = FileTail(lambda: view.CODEX_LOG if view.CODEX_LOG.exists() else None)
    while True:
        fresh = []
        claude_lines = claude.poll()
        if claude.changed and claude.path is not None:
            fresh.append(
                (time.strftime("%H:%M:%S"), "-", "sys", f"新一轮：{claude.path.name}")
            )
        for line in claude_lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            for clock, kind, text in view.structured_claude_entries(payload):
                if kind == "sys":
                    continue  # 会话开始那行没有时间戳，用上面的"新一轮"分隔代替
                fresh.append((clock, "CLAUDE", kind, text))
        for line in codex.poll():
            match = view.CLOCK_RE.search(line)
            clock = match.group(1) if match else time.strftime("%H:%M:%S")
            text = view.CLOCK_RE.sub("", line, count=1).strip()
            text = text.replace("[CODEX]", "", 1).strip()
            fresh.append((clock, "CODEX", "codex", text))
        if fresh:
            with LOCK:
                ENTRIES.extend(fresh)
            touch()
        time.sleep(0.35)


def watchdog(server) -> None:
    """空闲自动退出：没有新事件、也没有人看页面时，自己收掉。"""
    while True:
        time.sleep(2)
        if IDLE_EXIT and (time.time() - LAST_ACTIVITY) > IDLE_EXIT:
            print(f"[live] 空闲超过 {IDLE_EXIT}s，自动退出")
            server.shutdown()
            return


PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>Codex x Claude live</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:#0b1220; color:#cbd5e1;
         font:12.5px/1.5 Consolas,"Cascadia Mono",monospace; }
  header { position:sticky; top:0; z-index:2; background:#0f172a;
           border-bottom:1px solid #1e293b; padding:8px 12px;
           font-family:system-ui,"Microsoft YaHei",sans-serif; font-size:12.5px; }
  header b { color:#e2e8f0; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%;
         background:#22c55e; margin-right:6px; vertical-align:1px; }
  .stat { color:#94a3b8; margin-left:14px; }
  #rows { padding:4px 0 40vh; }
  .row { display:flex; gap:10px; padding:1px 12px; }
  .row:hover { background:#111c30; }
  .clock { flex:0 0 60px; color:#64748b; }
  .role  { flex:0 0 62px; font-weight:700; letter-spacing:.3px; }
  .text  { flex:1 1 auto; white-space:pre-wrap; word-break:break-word; }
  .claude .role { color:#4ade80; }
  .codex  .role { color:#e879f9; }
  .codex  .text { color:#f5d0fe; }
  .sep    .role, .sep .text { color:#64748b; font-style:italic; }
  .tool .text, .res .text { color:#94a3b8; }
  .err  .text { color:#f87171; }
  .sisyphus { color:#38bdf8; }
  .sys  .text { color:#64748b; }
  .done .text { color:#38bdf8; font-weight:700; }
  .tools { color:#64748b; }
</style></head>
<body>
<header>
  <span class="dot" id="dot"></span><b>Codex x Claude 实时工作</b>
  <span class="stat" id="stat">连接中…</span>
  <span class="stat">绿色 = CLAUDE，品红 = CODEX，同一根时间轴</span>
</header>
<div id="rows"></div>
<script>
let since = 0, pinned = true;
const rows = document.getElementById('rows');
const dot = document.getElementById('dot');
const stat = document.getElementById('stat');
let cCount = 0, xCount = 0, lastClock = '-';

addEventListener('scroll', () => {
  pinned = (innerHeight + scrollY) >= (document.body.scrollHeight - 60);
}, { passive: true });

function addRow(e) {
  const div = document.createElement('div');
  const roleClass = e.role === 'CLAUDE' ? 'claude' : (e.role === 'CODEX' ? 'codex' : 'sep');
  div.className = 'row ' + roleClass + ' ' + e.kind;
  const c = document.createElement('span'); c.className = 'clock'; c.textContent = e.clock;
  const r = document.createElement('span'); r.className = 'role';  r.textContent = e.role;
  const t = document.createElement('span'); t.className = 'text';  t.textContent = e.text;
  div.append(c, r, t);
  rows.appendChild(div);
  lastClock = e.clock;
  if (e.role === 'CLAUDE') cCount++; else xCount++;
}

async function tick() {
  try {
    const res = await fetch('/api/events?since=' + since, { cache: 'no-store' });
    const data = await res.json();
    // 看板服务每轮都会重起：新进程的编号从头开始，游标会失效。
    // 发现游标比总数还大就清空重来，避免页面永远空着。
    if (data.total < since) {
      rows.innerHTML = '';
      since = 0; cCount = 0; xCount = 0;
      stat.textContent = '看板已重启，正在重新加载…';
      dot.style.background = '#eab308';
      return;
    }
    if (data.entries.length) {
      data.entries.forEach(addRow);
      since = data.next;
      if (pinned) scrollTo(0, document.body.scrollHeight);
      dot.style.background = '#22c55e';
    }
    stat.textContent = `CLAUDE ${cCount} 条 · CODEX ${xCount} 条 · 最后事件 ${lastClock} · 服务已运行 ${data.uptime}s`;
  } catch (err) {
    failures++;
    dot.style.background = '#ef4444';
    stat.textContent = failures > 3
      ? '服务已停止（视图只读；重开：python .pair/live.py --port 8760）'
      : '连接中断，重试中…';
    return;
  }
  failures = 0;
}
let failures = 0;
setInterval(tick, 800); tick();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 安静一点
        return

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/events":
            since = int(parse_qs(parsed.query).get("since", ["0"])[0] or 0)
            with LOCK:
                items = ENTRIES[since:]
                next_index = len(ENTRIES)
            payload = {
                "entries": [
                    {"clock": clock, "role": role, "kind": kind, "text": text}
                    for clock, role, kind, text in items
                ],
                "next": next_index,
                "total": next_index,
                "uptime": int(time.time() - STARTED),
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/shutdown":
            touch()
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self.send_error(404)


def main() -> int:
    global IDLE_EXIT
    parser = argparse.ArgumentParser(description="合并视图的本地网页版（只读）")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument(
        "--idle-exit",
        type=int,
        default=900,
        help="空闲多少秒后自动退出（0 = 永不退出；默认 900）",
    )
    args = parser.parse_args()
    IDLE_EXIT = max(0, args.idle_exit)
    threading.Thread(target=collect_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    print(f"live view: http://127.0.0.1:{args.port}  (idle-exit {IDLE_EXIT}s)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
