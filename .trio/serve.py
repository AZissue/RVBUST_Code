#!/usr/bin/env python3
"""三方工作群的可视化网页（人 / A / B）——**聊天式工作群**，不是表格看板。

为什么是聊天式：三方协作的真实形状是"一段一段的对话"，不是一堆状态格子。
同一 ``task`` 的消息归成一段（可折叠、段头带"掐断"按钮），没有 ``task`` 的
消息留在"会话流"里——那正是人插话的地方。真机验收的截图证据（``refs`` 里
的图片路径）直接内联成图，不用另开文件管理器。

只读/只写**总线**，不碰任何模型、不消耗 token：

* ``GET  /``                    单页界面（静态 HTML 内嵌在本文件里，无前端框架）
* ``GET  /api/events?since=N``  增量消息 + 权限矩阵 + 标签表
* ``POST /api/say``             ``{"text","task"}``，服务端**硬编码** role=HUMAN
* ``POST /api/kill``            ``{"task","reason"}``，发 kill 消息 + 落掐断标记文件
* ``GET  /fs/<相对仓库根的路径>`` 只为把 ``refs`` 里的图片喂给 ``<img>``

用法::

    python .trio/serve.py                 # 起服务（默认端口取 config.group_port）
    python .trio/serve.py --open          # 起服务并自动开浏览器
    python .trio/serve.py --demo --open   # 灌一批示例消息，零花费先看界面长什么样

鉴权模型**不在这一层**：谁能发什么由 ``bus.PERMISSIONS`` 强制，本文件只负责
按它渲染、并把人的发言钉死成 HUMAN。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bus  # noqa: E402  （消息总线：存储与权限矩阵的唯一来源）

TRIO_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRIO_DIR.parent

# 掐断标记：router.py 轮询这个文件来**真正**停掉 B（消费后应自行删除）。
# 路径挂在 bus.LOG_DIR 下，跟总线日志同一个目录，避免两处各写一份。
KILL_FLAG = bus.LOG_DIR / "kill.flag"

# 实时活动条的数据源：router.py 在驱动 B 的时候往这里写"B 现在在干什么"。
# 这里做**只读**——文件不在、写坏了、字段缺了，界面就当没在跑，绝不影响别的。
LIVE_FILE = bus.LOG_DIR / "live.json"

STARTED = time.time()
LAST_ACTIVITY = time.time()
IDLE_EXIT = 900  # 秒；0 = 不自动退出
_ACTIVITY_LOCK = threading.Lock()


def touch() -> None:
    global LAST_ACTIVITY
    with _ACTIVITY_LOCK:
        LAST_ACTIVITY = time.time()


def idle_seconds() -> float:
    with _ACTIVITY_LOCK:
        return time.time() - LAST_ACTIVITY


def watchdog(server: ThreadingHTTPServer) -> None:
    """没有任何请求进来就自己收掉，不留守护进程。"""
    while True:
        time.sleep(2)
        if IDLE_EXIT and idle_seconds() > IDLE_EXIT:
            print(f"[serve] 空闲超过 {IDLE_EXIT}s，自动退出")
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


# ---------------------------------------------------------------- 掐断


def write_kill_flag(task: str, reason: str, seq: int) -> dict:
    """落一个掐断标记文件，给 router.py 轮询。

    格式（JSON 单对象）::

        {"task": "...", "reason": "...", "ts": "<ISO 本地时间>", "seq": 42}

    ``seq`` 是那条 kill 消息在群里的编号，方便 router 对照。写成临时文件再
    ``os.replace``，避免 router 读到写了一半的内容。
    """
    bus.ensure_dirs()
    payload = {
        "task": task,
        "reason": reason,
        "ts": bus.now_iso(),
        "seq": seq,
    }
    tmp = KILL_FLAG.with_name(KILL_FLAG.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, KILL_FLAG)
    return payload


# ---------------------------------------------------------------- 静态页面

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>三方工作群</title>
<style>
  :root {
    color-scheme: dark;
    --bg:#0b1017; --panel:#121a25; --panel2:#0e141d; --line:#1e2836;
    --text:#d6dee9; --dim:#7b8798; --faint:#556172;
    --human:#60a5fa; --a:#e879f9; --b:#4ade80; --sys:#fbbf24; --kill:#f87171;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:13px/1.66 "Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace; }
  #banner { display:none; padding:8px 16px; background:#3a1418; color:#fca5a5;
            border-bottom:1px solid #7f1d1d; font-size:12.5px; }
  #banner.on { display:block; }
  [data-reload] { display:flex; align-items:center; gap:12px; padding:8px 16px;
                  background:#2a230d; color:#fde68a; border-bottom:1px solid #7c6a1a;
                  font-size:12.5px; }
  [data-reload] .reloadbar-spacer { flex:1 1 auto; }
  [data-reload-btn] { background:#3d3510; color:#fef3c7; border:1px solid #7c6a1a;
                      border-radius:4px; font:inherit; font-size:11.5px; padding:2px 12px;
                      cursor:pointer; }
  [data-reload-btn]:hover { background:#4d4416; }
  header { position:sticky; top:0; z-index:5; background:var(--panel2);
           border-bottom:1px solid var(--line); padding:11px 16px;
           display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:13.5px; font-weight:700; letter-spacing:.4px; color:#e8eef7; }
  .dot { width:8px; height:8px; border-radius:50%; background:#22c55e; display:inline-block; }
  .stat { color:var(--faint); font-size:11.5px; }
  main { max-width:1000px; margin:0 auto; padding:16px 16px 190px; }
  .sect { margin:0 0 22px; }
  .sect-head { display:flex; align-items:center; gap:8px; padding:6px 2px;
               border-bottom:1px dashed var(--line); margin-bottom:8px; }
  .sect-head .name { color:var(--dim); font-size:12px; letter-spacing:.5px; }
  .sect-head .tid { color:#e8eef7; font-weight:700; font-size:12.5px; }
  .sect-head .spacer { flex:1 1 auto; }
  .fold { background:none; border:0; color:var(--dim); cursor:pointer;
          font:inherit; padding:0 4px; }
  .fold:hover { color:var(--text); }
  .kill { background:#2a1418; color:#fca5a5; border:1px solid #7f1d1d;
          border-radius:4px; font:inherit; font-size:11.5px; padding:1px 9px;
          cursor:pointer; }
  .kill:hover { background:#3f1a1f; color:#fecaca; }
  .body.collapsed { display:none; }
  .empty { color:var(--faint); font-size:12.5px; padding:14px 2px; }
  .msg { display:flex; gap:12px; padding:5px 0; }
  .msg .meta { flex:0 0 104px; text-align:right; color:var(--faint);
               font-size:11.5px; padding-top:6px; white-space:nowrap; }
  .msg .bubble { flex:1 1 auto; min-width:0; background:var(--panel);
                 border-left:2px solid var(--line); border-radius:0 6px 6px 0;
                 padding:7px 12px 9px; }
  .head { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
          margin-bottom:3px; }
  .badge { font-size:11px; font-weight:700; letter-spacing:.4px; padding:0 6px;
           border-radius:3px; border:1px solid currentColor; }
  .kind { font-size:11.5px; color:var(--dim); }
  .tchip { font-size:11px; color:var(--faint); border:1px solid var(--line);
           border-radius:3px; padding:0 5px; }
  .text { white-space:pre-wrap; word-break:break-word; }
  .refs { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
  .ref { font-size:11.5px; color:var(--faint); border:1px dashed var(--line);
         border-radius:3px; padding:0 6px; text-decoration:none; }
  .ref:hover { color:var(--text); }
  img.shot { display:block; max-width:min(460px,100%); margin-top:9px;
             border:1px solid var(--line); border-radius:4px; }
  .shot-fail { display:inline-block; margin-top:9px; font-size:11.5px;
               color:#fca5a5; border:1px dashed #7f1d1d; border-radius:3px;
               padding:3px 8px; }
  .human .bubble { border-left-color:var(--human); background:#101a29; }
  .human .badge  { color:var(--human); }
  .a .bubble { border-left-color:var(--a); background:#1b1224; }
  .a .badge  { color:var(--a); }
  .b .bubble { border-left-color:var(--b); background:#0f1d16; }
  .b .badge  { color:var(--b); }
  .system .bubble { border-left:2px dashed var(--sys); background:#221b0d; }
  .system .badge  { color:var(--sys); }
  .system .text   { color:#fde68a; font-weight:700; }
  .killmsg .bubble { border-left:2px solid var(--kill); background:#291316; }
  .killmsg .badge  { color:var(--kill); }
  .killmsg .text   { color:#fecaca; font-weight:700; }
  #legend { max-width:1000px; margin:0 auto; padding:0 16px 24px; }
  #legend summary { color:var(--faint); font-size:11.5px; cursor:pointer; }
  #legend .row { color:var(--dim); font-size:11.5px; padding:2px 0 2px 14px; }
  footer { position:fixed; left:0; right:0; bottom:0; background:var(--panel2);
           border-top:1px solid var(--line); padding:10px 16px; }
  .composer { max-width:1000px; margin:0 auto; display:flex; gap:8px;
              align-items:flex-end; }
  #say { flex:1 1 auto; resize:none; height:56px; background:#0b1017;
         color:var(--text); border:1px solid var(--line); border-radius:5px;
         padding:8px 10px; font:inherit; }
  #say:focus { outline:none; border-color:#33415a; }
  #taskSel { background:#0b1017; color:var(--dim); border:1px solid var(--line);
             border-radius:5px; padding:8px 6px; font:inherit; font-size:11.5px; }
  #send { background:#16233a; color:#cfe0f7; border:1px solid #2b3d5e;
          border-radius:5px; padding:9px 16px; font:inherit; cursor:pointer; }
  #send:hover { background:#1d2e4b; }
  .hint { max-width:1000px; margin:6px auto 0; color:var(--faint); font-size:11px; }

  /* 实时活动条：B 跑着的时候，人得看得见它在动 */
  .live { flex:1 0 100%; margin-top:9px; background:var(--panel);
          border:1px solid var(--line); border-left:2px solid var(--b);
          border-radius:0 6px 6px 0; padding:7px 12px 9px; }
  .live.off { display:none; }
  .lrow { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .lspacer { flex:1 1 auto; }
  .lled { width:7px; height:7px; border-radius:50%; background:var(--b);
          display:inline-block; flex:0 0 auto; }
  .lled.warn { background:var(--sys); }
  .lled.stale { background:var(--faint); }
  .ltask { font-weight:700; font-size:12.5px; color:#cfe0f7; }
  .lelapsed { color:var(--faint); font-size:11.5px; }
  .lstate { color:var(--b); font-size:12px; }
  .lstate.warn { color:var(--sys); }
  .lstate.stale { color:var(--faint); }
  .lcount { color:var(--faint); font-size:11.5px; }
  .laction { color:var(--dim); font-size:11.5px; margin-top:3px;
             white-space:pre-wrap; word-break:break-all; }
  .lwarn { color:var(--sys); font-size:11.5px; margin-top:2px; }
  .ltrack { height:3px; background:#0b1017; border-radius:2px; margin-top:7px;
            overflow:hidden; }
  .lbar { height:100%; width:0; background:var(--b); }
  .lbar.warn { background:var(--sys); }

  /* 待办栏：人不开终端也看得见"还欠着谁什么"，点一下勾掉 */
  .todo { display:flex; align-items:flex-start; gap:10px; padding:7px 10px;
          background:var(--panel); border:1px solid var(--line);
          border-left:2px solid var(--human); border-radius:0 6px 6px 0;
          margin-bottom:6px; }
  .todo-meta { flex:0 0 auto; color:var(--faint); font-size:11.5px; padding-top:1px;
               white-space:nowrap; }
  .todo-text { flex:1 1 auto; min-width:0; white-space:pre-wrap; word-break:break-word; }
  .tododone { flex:0 0 auto; background:#12251a; color:#86efac; border:1px solid #1f5133;
              border-radius:4px; font:inherit; font-size:11.5px; padding:1px 10px;
              cursor:pointer; }
  .tododone:hover { background:#173321; color:#bbf7d0; }
</style></head>
<body>
<div id="banner"></div>
<header>
  <span class="dot" id="dot"></span>
  <h1>三方工作群</h1>
  <span class="stat" id="stat">连接中…</span>
  <span class="stat">人（蓝）· A（品红）· B（绿）· 系统（黄 = 机械闸/掐断）</span>

  <div class="live off" id="live">
    <div class="lrow">
      <span class="lled" id="lled"></span>
      <span class="ltask" id="ltask"></span>
      <span class="lspacer"></span>
      <span class="lelapsed" id="lelapsed"></span>
    </div>
    <div class="lrow">
      <span class="lstate" id="lstate"></span>
      <span class="lspacer"></span>
      <span class="lcount" id="lcount"></span>
    </div>
    <div class="laction" id="laction"></div>
    <div class="lwarn" id="lwarn"></div>
    <div class="ltrack"><div class="lbar" id="lbar"></div></div>
  </div>
</header>

<main>
  <section class="sect" id="todosSect">
    <div class="sect-head">
      <span class="name">待办（还欠着谁什么）</span>
      <span class="spacer"></span>
      <span class="stat" id="todoCount"></span>
    </div>
    <div class="body" id="todosBody" data-todos><!--TODOS--></div>
  </section>
  <section class="sect" id="lobby">
    <div class="sect-head">
      <button class="fold" data-fold="lobby">▾</button>
      <span class="name">会话流（不挂任务的发言）</span>
      <span class="spacer"></span>
      <span class="stat" id="lobbyCount"></span>
    </div>
    <div class="body" id="lobbyBody"></div>
  </section>
  <div id="tasks"></div>
  <div class="empty" id="empty">群里还没有消息——下面的输入框以「人」的身份发言，或运行 <b>python .trio/serve.py --demo</b> 灌一批示例。</div>
</main>

<details id="legend"><summary>权限矩阵（谁能发什么——机制强制，不是纪律）</summary><div id="legendBody"></div></details>

<footer>
  <div class="composer">
    <textarea id="say" placeholder="留个记录（Enter 发送，Shift+Enter 换行）——注意：这里说的话不会叫醒 A，要 A 听见请在 Codex 会话里直接说"></textarea>
    <select id="taskSel"><option value="">会话流</option></select>
    <button id="send">记录</button>
  </div>
  <div class="hint" id="hint"></div>
</footer>

<script>
const CLS = { HUMAN:'human', A:'a', B:'b', SYSTEM:'system' };
/* 页面版本：服务端 build_page() 把占位符换成真值（与 /api/events 的 page_version 同源）。
   每 tick 比对；不一致才提示刷新，**不自动重载**（人可能正在输入框里打字）。 */
const PAGE_VERSION = "<!--PAGEVER-->";
let since = 0, kinds = {}, roles = {}, failures = 0, pinned = true, count = 0;
const groups = {};                      // task -> {root, body, num, last}
const lobbyBody = document.getElementById('lobbyBody');
const tasksEl   = document.getElementById('tasks');
const banner    = document.getElementById('banner');
const stat      = document.getElementById('stat');
const dot       = document.getElementById('dot');
const emptyEl   = document.getElementById('empty');
const taskSel   = document.getElementById('taskSel');
const hintEl    = document.getElementById('hint');

addEventListener('scroll', () => {
  pinned = (innerHeight + scrollY) >= (document.body.scrollHeight - 80);
}, { passive:true });

function showBanner(msg) { banner.textContent = msg; banner.classList.add('on'); }
function hideBanner() { banner.classList.remove('on'); }

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

/* ---- 页面版本横幅：服务端页面比我手上这份新 → 给个刷新按钮，不自动重载 ----
   只在"状态翻转"时动 DOM：一致就不留任何 [data-reload]，不一致才插入一次。 */
let reloadShown = false;
function showReloadBanner() {
  if (document.querySelector('[data-reload]')) return;
  const bar = el('div');
  bar.setAttribute('data-reload', '');
  bar.appendChild(el('span', null, '群界面已更新（服务端页面版本和这份不一样）。'));
  bar.appendChild(el('span', 'reloadbar-spacer'));
  const btn = el('button', null, '刷新');
  btn.setAttribute('data-reload-btn', '');
  btn.onclick = () => location.reload();
  bar.appendChild(btn);
  document.body.insertBefore(bar, document.body.firstChild);
}
function hideReloadBanner() {
  const bar = document.querySelector('[data-reload]');
  if (bar) bar.remove();
}
function syncPageVersion(v) {
  const stale = !!v && v !== PAGE_VERSION;
  if (stale === reloadShown) return;        // 状态没变就别碰 DOM
  reloadShown = stale;
  if (stale) showReloadBanner(); else hideReloadBanner();
}

/* ---- 图片证据：refs 里的图片路径内联成 <img>，相对仓库根解析 ---- */
const IMG_RE = /\\.(png|jpe?g|gif|webp|bmp|svg|avif)$/i;
function fileURL(ref) {
  const clean = String(ref).replace(/\\\\/g, '/').replace(/^\\.\\//, '').replace(/^\\/+/, '');
  return '/fs/' + clean.split('/').map(encodeURIComponent).join('/');
}

function addRefs(bubble, refs) {
  const box = el('div', 'refs');
  let used = false;
  refs.forEach((raw) => {
    const ref = String(raw || '').trim();
    if (!ref) return;
    used = true;
    if (IMG_RE.test(ref.split('?')[0])) {
      const img = el('img', 'shot');
      img.alt = ref;
      img.loading = 'lazy';
      img.onerror = () => {                       // 破图 → 占位提示，不留红叉
        const fail = el('span', 'shot-fail', '图片加载失败：' + ref);
        bubble.appendChild(fail);
        img.remove();
      };
      img.onclick = () => window.open(img.src, '_blank');
      img.style.cursor = 'zoom-in';
      img.src = fileURL(ref);
      bubble.appendChild(img);
    } else {
      const link = el('a', 'ref', ref);           // 非图片：给个可点的小标签
      link.href = fileURL(ref);
      link.target = '_blank';
      box.appendChild(link);
    }
  });
  if (box.childNodes.length) bubble.appendChild(box);
  return used;
}

function addBubble(container, m) {
  const role = m.role || '?';
  const kind = m.kind || '';
  const row = el('div', 'msg ' + (CLS[role] || '') + (kind === 'kill' ? ' killmsg' : ''));
  row.appendChild(el('div', 'meta', String(m.ts || '').slice(11, 19) || '--:--:--'));
  const bubble = el('div', 'bubble');

  const head = el('div', 'head');
  head.appendChild(el('span', 'badge', role));
  head.appendChild(el('span', 'kind', kinds[kind] || kind));
  if (m.task) head.appendChild(el('span', 'tchip', m.task));
  bubble.appendChild(head);
  bubble.appendChild(el('div', 'text', m.text || ''));
  addRefs(bubble, Array.isArray(m.refs) ? m.refs : []);
  row.appendChild(bubble);
  container.appendChild(row);
  return row;
}

/* ---- 按 task 分段：段头（任务号 + 条数 + 掐断）可折叠 ---- */
function ensureGroup(task) {
  if (groups[task]) return groups[task];
  const root = el('section', 'sect');
  const head = el('div', 'sect-head');
  const body = el('div', 'body');
  const num  = el('span', 'stat', '0 条');
  const fold = el('button', 'fold', '▾');
  const kill = el('button', 'kill', '掐断');
  fold.onclick = () => {
    const hidden = body.classList.toggle('collapsed');
    fold.textContent = hidden ? '▸' : '▾';
  };
  kill.title = '停掉这个任务：发一条 kill，并落 .trio/log/kill.flag 让 router 停掉 B';
  kill.onclick = () => doKill(task);
  head.append(fold, el('span', 'tid', task), num, el('span', 'spacer'), kill);
  root.append(head, body);
  tasksEl.appendChild(root);
  groups[task] = { root: root, body: body, num: num, count: 0 };
  if (emptyEl) emptyEl.style.display = 'none';
  const opt = el('option', null, task);
  opt.value = task;
  taskSel.appendChild(opt);
  return groups[task];
}

function bumpGroup(task) {
  const g = groups[task];
  if (!g) return;
  g.count++;
  g.num.textContent = g.count + ' 条';
}

function render(m) {
  if (m.task) {
    ensureGroup(m.task);
    addBubble(groups[m.task].body, m);
    bumpGroup(m.task);
  } else {
    addBubble(lobbyBody, m);
  }
  count++;
  document.getElementById('lobbyCount').textContent = lobbyBody.childNodes.length + ' 条';
  if (emptyEl) emptyEl.style.display = 'none';
}

/* ---- 待办栏：列出未完成待办，点「完成」= 以人的身份勾掉 ---- */
const todosBody = document.getElementById('todosBody');
const todoCount = document.getElementById('todoCount');

function renderTodos(todos) {
  todosBody.replaceChildren();
  if (!todos || !todos.length) {
    todosBody.appendChild(el('div', 'empty', '没有未完成的待办。'));
    if (todoCount) todoCount.textContent = '';
    return;
  }
  todos.forEach((t) => {
    const id = String(t.todo_id);
    const row = el('div', 'todo');
    row.setAttribute('data-todo', id);
    const who = (t.role || '') + (t.task ? ' · ' + t.task : '');
    row.appendChild(el('div', 'todo-meta', who));
    row.appendChild(el('div', 'todo-text', t.text || ''));
    const btn = el('button', 'tododone', '完成');
    btn.setAttribute('data-done', id);
    btn.title = '勾掉这条待办（以人的身份发一条 todo）';
    btn.onclick = () => doTodoDone(id);
    row.appendChild(btn);
    todosBody.appendChild(row);
  });
  if (todoCount) todoCount.textContent = todos.length + ' 项';
}

async function doTodoDone(id) {
  try {
    const res = await fetch('/api/todo_done', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ todo_id: id })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { showBanner('勾掉失败：' + (data.error || res.status)); return; }
    hideBanner();
    if (data.message) {
      render(data.message);                       // 群里仍留一条记录
      since = Math.max(since, data.message.seq);
    }
    tick();                                        // 立刻刷新待办栏
  } catch (err) {
    showBanner('勾掉失败：服务已停止');
  }
}

/* ---- 掐断 ---- */
async function doKill(task) {
  const input = prompt('掐断 ' + task + ' 的理由（会写进群里，并落 .trio/log/kill.flag）：', '人工掐断：');
  if (input === null) return;
  const reason = input.trim() || '人工掐断';
  try {
    const res = await fetch('/api/kill', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ task: task, reason: reason })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { showBanner('掐断失败：' + (data.error || res.status)); return; }
    hideBanner();
    render(data.message);                 // 立刻上屏，不用等轮询
    since = Math.max(since, data.message.seq);
  } catch (err) {
    showBanner('掐断失败：服务已停止');
  }
}

/* ---- 发言 ---- */
async function sendSay() {
  const box = document.getElementById('say');
  const text = box.value.trim();
  if (!text) return;
  const task = taskSel.value || null;
  try {
    const res = await fetch('/api/say', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ text: text, task: task })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { showBanner('发送失败：' + (data.error || res.status)); return; }
    hideBanner();
    box.value = '';
    render(data.message);
    since = Math.max(since, data.message.seq);
    scrollTo(0, document.body.scrollHeight);
    pinned = true;
  } catch (err) {
    showBanner('发送失败：服务已停止');
  }
}

function renderLegend() {
  const box = document.getElementById('legendBody');
  Object.keys(roles).forEach((role) => {
    const labels = roles[role].map((k) => kinds[k] || k).join('、');
    box.appendChild(el('div', 'row', role + ' —— ' + labels));
  });
  // 这段话必须诚实：人能在这里"记录"，但**叫不醒 A**。
  // 让界面假装自己能喊人，跟上一版"把纪律写在提示词里"是同一种自欺。
  document.getElementById('hint').textContent =
    '权限由 .trio/bus.py 强制：B 永远收不到人的消息。'
    + '⚠ 这里的发言只进群日志，没有机制会因此唤醒 A（router 只轮询「掐断」）。'
    + '要 A 听见，请在 Codex 会话里直接跟它说。本页的「掐断」是真机制，随时可用。';
}

/* ---- 实时活动条：B 跑着的时候人得看得见它在动 ---- */
const liveEl = document.getElementById('live');
const lled = document.getElementById('lled');
const ltask = document.getElementById('ltask');
const lelapsed = document.getElementById('lelapsed');
const lstate = document.getElementById('lstate');
const lcount = document.getElementById('lcount');
const laction = document.getElementById('laction');
const lwarn = document.getElementById('lwarn');
const lbar = document.getElementById('lbar');

function fmtDur(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? (m + '分' + String(s).padStart(2, '0') + '秒') : (s + ' 秒');
}

function renderLive(d) {
  const running = d && (d.phase === 'running' || d.phase === 'starting');
  if (!running) { liveEl.classList.add('off'); return; }
  liveEl.classList.remove('off');

  // 心跳停了就明说——别让一个冻住的活动条看起来像"还在跑"
  const stale = (Date.now() / 1000 - (Number(d.updated) || 0)) > 15;
  const since = Number(d.since_write_events) || 0;
  const warnAt = Number(d.warn_at) || 0;
  const killAt = Number(d.kill_at) || 0;
  const overWarn = warnAt > 0 && since >= warnAt;

  lled.className = 'lled' + (stale ? ' stale' : (overWarn ? ' warn' : ''));
  ltask.textContent = (d.task || '?') + ' · '
    + (d.phase === 'starting' ? '正在起 B…' : 'B 运行中');
  lelapsed.textContent = '已跑 ' + fmtDur(d.elapsed);

  if (stale) {
    lstate.className = 'lstate stale';
    lstate.textContent = '● 心跳已停（router 可能已退出）';
  } else {
    lstate.className = 'lstate' + (overWarn ? ' warn' : '');
    lstate.textContent = overWarn ? '● 长时间没写文件' : '● 干活中';
  }

  lcount.textContent = '事件 ' + (d.events || 0) + ' / 硬闸 ' + (killAt || '-')
    + ' · 动作 ' + (d.actions || 0);
  laction.textContent = d.last_action ? ('最近动作：' + d.last_action) : '还没动手，在读任务书…';

  if (since > 0) {
    let w = '无写入已累积 ' + since + ' 个事件';
    if (overWarn) w += ' ← 软告警 ' + warnAt + ' 已过';
    else if (warnAt) w += '（软告警在 ' + warnAt + '）';
    if (Number(d.no_write_streak)) w += ' · 连续 ' + d.no_write_streak + ' 次动作没写文件';
    lwarn.textContent = w;
  } else {
    lwarn.textContent = '';
  }

  const pct = killAt ? Math.min(100, Math.round(since / killAt * 100)) : 0;
  lbar.style.width = pct + '%';
  lbar.className = 'lbar' + (overWarn ? ' warn' : '');
}

async function tickLive() {
  try {
    const res = await fetch('/api/live', { cache:'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    renderLive(await res.json());
  } catch (err) {
    renderLive(null);          // 读不到就收起来，不冒充"在跑"
  }
}

/* ---- 轮询（800ms 增量） ---- */
async function tick() {
  try {
    const res = await fetch('/api/events?since=' + since, { cache:'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    roles = data.roles || {}; kinds = data.kinds || {};
    syncPageVersion(data.page_version);
    if (data.todos) renderTodos(data.todos);
    if (data.messages && data.messages.length) {
      data.messages.forEach((m) => { render(m); since = Math.max(since, m.seq); });
      if (pinned) scrollTo(0, document.body.scrollHeight);
    } else if (data.last > since) {
      since = data.last;
    }
    failures = 0;
    hideBanner();
    dot.style.background = '#22c55e';
    stat.textContent = '已连接 · ' + count + ' 条 · 最新 #' + since
      + ' · 页面已开 ' + Math.round(performance.now() / 1000) + 's';
    if (!document.getElementById('legendBody').childNodes.length) renderLegend();
  } catch (err) {
    failures++;
    dot.style.background = '#ef4444';
    if (failures >= 3 || count === 0) {     // 一上来就连不上：立刻说清楚，别让人对着空白页猜
      stat.textContent = '未连接';
      showBanner('服务已停止——重开：python .trio/serve.py（页面保留最后一次收到的消息）');
    } else {
      stat.textContent = '连接中断，重试中…';
    }
  }
}

document.getElementById('send').onclick = sendSay;
document.getElementById('say').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendSay(); }
});
document.querySelectorAll('.fold[data-fold]').forEach((btn) => {
  btn.onclick = () => {
    const body = document.getElementById('lobbyBody');
    const hidden = body.classList.toggle('collapsed');
    btn.textContent = hidden ? '▸' : '▾';
  };
});
setInterval(() => { tick(); tickLive(); }, 800); tick(); tickLive();
</script>
</body></html>
"""

# 页面版本号：对**模板本身**取指纹（占位符 <!--PAGEVER--> 是稳定文本，
# 不参与真值注入），模板一动它就变。前端每 tick 拿 /api/events 里的同名值
# 比对，不一致才提示人刷新——**不自动重载**，免得吞掉人正在输入的字。
PAGE_VERSION = hashlib.md5(PAGE.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------- 待办栏


def _esc(value) -> str:
    """把待办里的自由文本安全地塞进 HTML（人/A 写的字不能当标签）。"""
    return (str("" if value is None else value)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_todo_rows(todos: list[dict]) -> str:
    """把未完成待办预渲染成服务端 HTML。

    浏览器里 JS 每 tick 会重渲染（用同一套 data-* 钩子）；这里预渲染是为了
    "页面一打开就看得见"——包括在**不跑 JS** 的渲染器里也能被断言到。
    """
    rows = []
    for item in todos:
        tid = _esc(item.get("todo_id"))
        who = _esc((item.get("role") or "") + (" · " + item["task"] if item.get("task") else ""))
        rows.append(
            f'<div class="todo" data-todo="{tid}">'
            f'<div class="todo-meta">{who}</div>'
            f'<div class="todo-text">{_esc(item.get("text"))}</div>'
            f'<button class="tododone" data-done="{tid}">完成</button>'
            f'</div>'
        )
    return "".join(rows) or '<div class="empty">没有未完成的待办。</div>'


def build_page() -> str:
    """整页 HTML：把当前未完成待办预渲染进 ``[data-todos]`` 容器。"""
    try:
        rows = render_todo_rows(bus.open_todos())
    except OSError:
        rows = ""
    page = PAGE.replace("<!--PAGEVER-->", PAGE_VERSION)
    return page.replace("<!--TODOS-->", rows)


# ---------------------------------------------------------------- demo


def has_demo() -> bool:
    return any(m.get("meta", {}).get("demo") for m in bus.read(0))


def seed_demo() -> int:
    """灌一批**不用任何模型**的示例消息，让界面立刻有东西看。"""
    if has_demo():
        print("[demo] 群里已有示例消息，跳过灌入（想重灌：删掉 .trio/log/group.jsonl 再跑）")
        return 0
    demo = {"demo": True}
    batch = [
        # 人的需求：不挂任务 → 落在"会话流"里，正好演示人插话的位置
        (bus.HUMAN, "say", None,
         "第 3 关按 P 暂停、再按 P 继续之后，蛇的移动速度掉回第 1 关的节奏了——"
         "关卡难度白选。截图在下面，第一张是暂停时，第二张是继续之后。",
         [".pair/shots/04-paused.png", ".pair/shots/03-playing-level3.png"]),
        # A 的任务书
        (bus.A, "task", "T-001",
         "任务书 T-001：暂停/继续之后必须保持当前关卡的速度与节奏。\n"
         "工作集：snake/game.py、snake/audio.py（其余文件不许改）。\n"
         "判据：① 第二次按 P 之后 tick 速率仍等于关卡表的值；② 暂停期间蛇不动、计时不推进；"
         "③ 173 项测试全绿。\n"
         "禁止：改关卡表的数值来绕过问题。交付时把运行截图贴回来。",
         []),
        # B 的技术方案
        (bus.B, "plan", "T-001",
         "技术方案：\n"
         "1. GameState 加 paused 标志，主循环从写死的 tick(10) 改成 tick(level.fps)；\n"
         "2. resume() 里重新读当前关卡 fps——根因就是继续时回落到默认值；\n"
         "3. 暂停期间冻结计时器，避免暂停久了直接判 game over。\n"
         "改动集中在 snake/game.py，不碰关卡表。",
         []),
        # B 的交付（带真机截图证据）
        (bus.B, "deliver", "T-001",
         "交付：改完了。pause()/resume() 现在共用同一个 fps 来源，暂停期间计时器冻结。\n"
         "自测：python -m pytest → 173 passed。手动跑第 3 关，暂停/继续后速度保持。\n"
         "截图：playing-level3.png 是继续之后的状态，paused.png 是暂停瞬间。",
         [".pair/shots/03-playing-level3.png", ".pair/shots/04-paused.png"]),
        # 机械闸（不用模型）
        (bus.SYSTEM, "gate", "T-001",
         "机械闸：同一命令 python -m pytest -q 在 2 个回合内重复 3 次 → 触发 "
         "repeat_threshold=3。记一次，继续观察。", []),
        # 掐断
        (bus.SYSTEM, "kill", "T-001",
         "掐断：snake/game.py 在 2 个回合内被改写 4 次，且没有新的测试结果落盘"
         "（no_progress_turns=2）。停手，交回 A。", []),
        # A 的验收
        (bus.A, "verify", "T-001",
         "验收：通过。复跑 python -m pytest（173 passed），并手动跑了第 3 关暂停/继续两轮——"
         "fps 保持关卡表的值，暂停期间计时不推进。B 的交付可信，回灌 inbox/007。", []),
        # A 升级给人
        (bus.A, "escalate", "T-001",
         "升级给人：暂停已经修好了。但顺手发现第 6 关通关之后分数不结算（见 06-won.png）。"
         "这个要你定：是 bug，还是本来就没做结算？定了我再开任务书。",
         [".pair/shots/06-won.png"]),
    ]
    added = 0
    for role, kind, task, text, refs in batch:
        try:
            bus.post(role, kind, text, task=task, refs=refs, meta=demo)
        except PermissionError as exc:      # 理论上到不了这里：demo 全用合法组合
            print(f"[demo] 跳过 {role}/{kind}：{exc}", file=sys.stderr)
            continue
        added += 1
    print(f"[demo] 已灌入 {added} 条示例消息（人 → A 任务书 → B 方案 → B 交付 → "
          f"机械闸 → 掐断 → A 验收 → A 升级）")
    return added


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "trio-serve/1.0"

    def log_message(self, *args):        # 静音：不要每请求一行
        return

    # ---- 发送助手
    def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _send_json(self, payload, status: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    # ---- GET
    def do_GET(self):  # noqa: N802
        touch()
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            return self._send(build_page().encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/events":
            raw_since = parse_qs(parsed.query).get("since", ["0"])[0]
            try:
                since = max(0, int(raw_since or 0))
            except ValueError:
                since = 0
            messages = bus.read(since)
            return self._send_json({
                "messages": messages,
                "last": bus.last_seq(),
                "roles": {role: sorted(bus.PERMISSIONS.get(role, ())) for role in bus.ROLES},
                "kinds": dict(bus.KIND_LABEL),
                # 只加字段：前端每 tick 顺带刷新待办栏（`since` 语义不变）
                "todos": bus.open_todos(),
                # 只加字段：前端拿它跟页面里的 PAGE_VERSION 比对，不一致就提示刷新
                "page_version": PAGE_VERSION,
            })
        if path == "/api/live":
            return self._send_json(self._read_live())
        if path.startswith("/fs/"):
            return self._serve_file(unquote(path[len("/fs/"):]))
        self.send_error(404)

    @staticmethod
    def _read_live() -> dict:
        """读活动条状态。读不到就返回 ``{"phase": "idle"}``——**不报错、不 500**。

        活动条坏了不该让页面显示成"服务已停止"，那会把人引到完全错误的方向上。
        """
        try:
            data = json.loads(LIVE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"phase": "idle"}
        return data if isinstance(data, dict) else {"phase": "idle"}

    def _serve_file(self, rel: str) -> None:
        """只喂仓库内的文件（refs 里的截图就是这么给到 <img> 的）。"""
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel:
            return self.send_error(404)
        try:
            target = (REPO_ROOT / rel).resolve()
            target.relative_to(REPO_ROOT.resolve())      # 越出仓库根一律拒绝
        except (ValueError, OSError):
            return self.send_error(403)
        if not target.is_file():
            return self.send_error(404)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        try:
            body = target.read_bytes()
        except OSError:
            return self.send_error(404)
        self._send(body, ctype)

    # ---- POST
    def do_POST(self):  # noqa: N802
        touch()
        path = urlparse(self.path).path
        payload = self._read_json()
        if payload is None:
            return self._send_json({"error": "请求体不是合法的 JSON 对象"}, 400)

        if path == "/api/say":
            text = str(payload.get("text") or "").strip()
            if not text:
                return self._send_json({"error": "text 不能为空"}, 400)
            task = payload.get("task") or None
            try:
                # 角色**硬编码**：前端不许指定角色，否则权限模型就废了
                message = bus.post(bus.HUMAN, "say", text, task=task)
            except PermissionError as exc:
                return self._send_json({"error": str(exc)}, 403)
            except OSError as exc:
                return self._send_json({"error": f"写总线失败：{exc}"}, 500)
            return self._send_json({"message": message})

        if path == "/api/todo_done":
            todo_id = str(payload.get("todo_id") or "").strip()
            if not todo_id:
                return self._send_json({"error": "todo_id 不能为空"}, 400)
            open_ids = {str(item.get("todo_id")) for item in bus.open_todos()}
            if todo_id not in open_ids:
                return self._send_json({"error": f"待办 {todo_id} 不存在或已完成"}, 400)
            try:
                # 角色**硬编码**：勾掉待办的人就是人，前端不许指定角色（同 /api/say）
                message = bus.post(
                    bus.HUMAN, "todo", f"完成待办 #{todo_id}",
                    meta={"todo_id": todo_id, "done": True},
                )
            except PermissionError as exc:
                return self._send_json({"error": str(exc)}, 403)
            except OSError as exc:
                return self._send_json({"error": f"写总线失败：{exc}"}, 500)
            return self._send_json({"ok": True, "seq": message["seq"], "message": message})

        if path == "/api/kill":
            task = str(payload.get("task") or "").strip()
            if not task:
                return self._send_json({"error": "task 不能为空"}, 400)
            reason = str(payload.get("reason") or "").strip() or "人工掐断"
            try:
                message = bus.post(bus.HUMAN, "kill", reason, task=task)
            except PermissionError as exc:
                return self._send_json({"error": str(exc)}, 403)
            except OSError as exc:
                return self._send_json({"error": f"写总线失败：{exc}"}, 500)
            try:
                flag = write_kill_flag(task, reason, message["seq"])
            except OSError as exc:
                return self._send_json({"error": f"写掐断标记失败：{exc}"}, 500)
            return self._send_json({"message": message, "flag": flag})

        self.send_error(404)


# ---------------------------------------------------------------- 入口


def main(argv=None) -> int:
    global IDLE_EXIT, KILL_FLAG, LIVE_FILE
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    default_port = bus.config().get("group_port", 8761)
    try:
        default_port = int(default_port)
    except (TypeError, ValueError):
        default_port = 8761

    parser = argparse.ArgumentParser(
        description="三方工作群的本地网页（聊天式，人 / A / B）"
    )
    parser.add_argument("--port", type=int, default=default_port,
                        help=f"监听端口（默认取 config.group_port={default_port}）")
    parser.add_argument("--idle-exit", type=int, default=900,
                        help="多少秒没有请求就自动退出（0 = 永不退出；默认 900）")
    parser.add_argument("--no-browser", action="store_true", help="不要自动开浏览器")
    parser.add_argument("--open", action="store_true", help="启动后自动开浏览器")
    parser.add_argument("--demo", action="store_true",
                        help="先灌一批示例消息（不调任何模型、零花费），再起服务")
    parser.add_argument("--log-dir", default=None, metavar="DIR",
                        help="把群日志与运行状态文件指到这个目录（测试用；不给就照旧用 "
                             ".trio/log/，正常运行时不用管它）")
    args = parser.parse_args(argv)

    IDLE_EXIT = max(0, args.idle_exit)

    if args.log_dir:
        # 给测试用：整条日志链（群日志 / 原始事件 / 掐断标记 / 活动条 live）全指到临时目录，
        # 不碰仓库里的 .trio/log/。只改本进程的模块属性，进程一退就没了。
        target = Path(args.log_dir).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        bus.LOG_DIR = target
        bus.GROUP_LOG = target / "group.jsonl"
        bus.RAW_DIR = target / "raw"
        KILL_FLAG = target / "kill.flag"
        LIVE_FILE = target / "live.json"
        print(f"[serve] --log-dir：群日志与状态文件改到 {target}")

    bus.ensure_dirs()

    if args.demo:
        seed_demo()

    url = f"http://127.0.0.1:{args.port}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"[serve] 起不来（端口 {args.port} 可能已被占用）：{exc}", file=sys.stderr)
        print(f"[serve] 已经开着的话直接用：{url}", file=sys.stderr)
        return 1

    threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    print(f"[serve] 三方工作群：{url}（Ctrl+C 退出；空闲 {IDLE_EXIT}s 自动退出）")
    print(f"[serve] 掐断标记：{KILL_FLAG}（router.py 轮询它来停掉 B）")
    if args.open or (args.demo and not args.no_browser):
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] 收到 Ctrl+C，退出")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
