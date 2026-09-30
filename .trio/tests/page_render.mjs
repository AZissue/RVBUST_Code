/*
 * 群页面**渲染**测试：把 serve.py 里内嵌的那段 JS 真的跑一遍，喂进真实形状的
 * 数据，再看 DOM 上出现了什么。**不调模型、不起服务、不花一分钱。**
 *
 * 为什么要有这个测试：上一轮框架的其它部分都跑通了——机械闸真的掐断了、A 真的
 * 回灌了、三个 commit 真的提交了——唯独**人什么也没看见**，因为没人验证过
 * "人这一侧"。组件级自检全绿，人却是瞎的，那绿灯就是假的。
 *
 * 用法： node .trio/tests/page_render.mjs .trio/serve.py
 */

import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const servePath = process.argv[2] || '.trio/serve.py';
const source = readFileSync(servePath, 'utf8');

// ---- 从 serve.py 的 PAGE 字符串里抠出 <script> 段（跟浏览器拿到的是同一份）
// \r? 是防换行符差异：同一份文件在 LF 与 CRLF 之间来回走过一次，
// 就会让这条正则突然匹配不上，然后测试报"没找到 PAGE"——纯噪音，不是真问题。
const pageMatch = source.match(/PAGE = """([\s\S]*?)"""\r?\n/);
if (!pageMatch) {
  console.error('✗ 没找到 PAGE 字符串');
  process.exit(1);
}
const page = pageMatch[1].replace(/\\\\/g, '\\');
const scriptMatch = page.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) {
  console.error('✗ PAGE 里没有 <script> 段');
  process.exit(1);
}
// 尾部挂一个探针：renderLegend 只在 fetch 成功时才被调用，而本测试里 fetch 是失败的——
// 不挂这个，那条路径就是"没被测到"（等于假绿）。roles/kinds 是 let，只有同作用域才够得着。
const js = scriptMatch[1]
  + '\n;globalThis.__probe = { renderLegend, setRoles: (r, k) => { roles = r; kinds = k; } };';

// ---- 极简 DOM 垫片：只实现页面真正用到的那几个方法
function mkEl(tag = 'div', id = '') {
  const e = {
    tagName: String(tag).toUpperCase(), id, className: '', _text: '',
    children: [], style: {}, dataset: {},
    appendChild(n) { this.children.push(n); return n; },
    append(...ns) { ns.forEach((n) => this.children.push(n)); },
    remove() {}, setAttribute() {}, addEventListener() {}, querySelectorAll: () => [],
    get textContent() { return this._text; },
    set textContent(v) { this._text = v === undefined || v === null ? '' : String(v); },
    get childNodes() { return this.children; },
  };
  e.classList = {
    add(c) { const s = new Set(e.className.split(' ').filter(Boolean)); s.add(c); e.className = [...s].join(' '); },
    remove(c) { const s = new Set(e.className.split(' ').filter(Boolean)); s.delete(c); e.className = [...s].join(' '); },
    toggle(c) { const s = new Set(e.className.split(' ').filter(Boolean)); const has = s.has(c); has ? s.delete(c) : s.add(c); e.className = [...s].join(' '); return !has; },
    contains(c) { return e.className.split(' ').filter(Boolean).includes(c); },
  };
  return e;
}

const registry = Object.create(null);
// 页面上真实存在的 id（少一个就说明 HTML 与 JS 对不上）
const KNOWN_IDS = [
  'banner', 'stat', 'dot', 'lobbyBody', 'tasks', 'empty', 'taskSel', 'hint',
  'legendBody', 'live', 'lled', 'ltask', 'lelapsed', 'lstate', 'lcount',
  'laction', 'lwarn', 'lbar', 'say', 'send', 'lobbyCount',
];
KNOWN_IDS.forEach((id) => { registry[id] = mkEl('div', id); });

const document = {
  getElementById: (id) => registry[id] || (registry[id] = mkEl('div', id)),
  createElement: (tag) => mkEl(tag),
  querySelectorAll: () => [],
  body: mkEl('body'),
};

const sandbox = {
  document, console, Date, Number, Math, String, Object, Array, JSON, Promise, Error,
  setInterval: () => 0, addEventListener: () => {}, scrollTo: () => {},
  performance: { now: () => 0 }, innerHeight: 800, scrollY: 0, window: {},
  // 页面一加载就会 tick()/tickLive()，让它们失败即可——这里测的是渲染，不是网络
  fetch: () => Promise.reject(new Error('测试环境不发请求')),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

try {
  vm.runInContext(js, sandbox, { filename: 'serve.PAGE<script>' });
} catch (err) {
  console.error('✗ 页面 JS 抛异常：', err.message);
  process.exit(1);
}

// ---- 断言
let failed = 0;
function check(name, cond, got) {
  if (cond) { console.log(`  ok   ${name}`); return; }
  failed++;
  console.log(`  FAIL ${name}${got === undefined ? '' : `  → 实际：${JSON.stringify(got)}`}`);
}

if (typeof sandbox.renderLive !== 'function') {
  console.error('✗ 页面 JS 里没有 renderLive —— 活动条没接上');
  process.exit(1);
}

console.log('活动条：B 正在跑（无写入已过软告警）');
sandbox.renderLive({
  task: 'T-005', phase: 'running', elapsed: 192, events: 4821, actions: 6,
  last_action: 'Edit  snake/core.py', since_write_events: 4821,
  warn_at: 2000, kill_at: 8000, no_write_streak: 6,
  updated: Date.now() / 1000,
});
check('活动条显示出来', !registry.live.classList.contains('off'), registry.live.className);
check('标题带任务号与状态', registry.ltask.textContent === 'T-005 · B 运行中', registry.ltask.textContent);
check('已跑时长可读', registry.lelapsed.textContent === '已跑 3分12秒', registry.lelapsed.textContent);
check('事件数/硬闸都在', registry.lcount.textContent.includes('4821') && registry.lcount.textContent.includes('8000'), registry.lcount.textContent);
check('最近动作上屏', registry.laction.textContent.includes('snake/core.py'), registry.laction.textContent);
check('软告警已过点明', registry.lwarn.textContent.includes('软告警 2000 已过'), registry.lwarn.textContent);
check('灯变黄', registry.lled.className.includes('warn'), registry.lled.className);
check('进度条按比例', registry.lbar.style.width === '60%', registry.lbar.style.width);

console.log('活动条：B 在跑但心跳停了（router 挂了）');
sandbox.renderLive({
  task: 'T-005', phase: 'running', elapsed: 300, events: 100, actions: 2,
  last_action: null, since_write_events: 0, updated: Date.now() / 1000 - 60,
});
check('明说心跳已停', registry.lstate.textContent.includes('心跳已停'), registry.lstate.textContent);
check('灯变灰', registry.lled.className.includes('stale'), registry.lled.className);
check('没动手时给个说法', registry.laction.textContent.includes('还没动手'), registry.laction.textContent);

console.log('活动条：B 没在跑');
for (const payload of [{ phase: 'idle' }, { phase: 'done' }, null]) {
  sandbox.renderLive(payload);
  check(`phase=${payload && payload.phase} 时收起来`, registry.live.classList.contains('off'), registry.live.className);
}

console.log('消息渲染：一条 A 的验收 + 一条带截图 refs');
sandbox.render({ seq: 1, ts: '2026-09-23T09:11:21+08:00', role: 'A', kind: 'verify', task: 'T-004', text: '验收结论：通过', refs: ['.pair/shots/06-won.png'] });
const seg = registry.tasks.children[0];
check('按 task 分了段', seg && seg.children.length === 2, seg && seg.children.length);
check('段头写了任务号', seg && JSON.stringify(seg.children[0].children.map((c) => c.textContent)).includes('T-004'));
const bubble = seg.children[1].children[0];
check('气泡带角色类', bubble.className.includes('a'), bubble.className);
check('截图内联成 <img>', JSON.stringify(bubble.children).includes('"shot"') || bubble.children.some((c) => (c.children || []).some((x) => x.tagName === 'IMG')));
check('ref 路径转成 /fs/', JSON.stringify(bubble).includes('/fs/.pair/shots/06-won.png'));

// 界面不许再说谎：人能在这里"记录"，但这里的话**叫不醒 A**。
// 让输入框暗示"说了 A 就会来"，跟上一版"把纪律写在提示词里"是同一种自欺。
console.log('界面是否如实交代了"这里喊不动 A"');
const placeholder = (page.match(/<textarea id="say" placeholder="([^"]*)"/) || [])[1] || '';
const sendLabel = (page.match(/<button id="send">([^<]*)<\/button>/) || [])[1] || '';
const hintSrc = (js.match(/getElementById\('hint'\)\.textContent =([\s\S]*?);\n/) || [])[1] || '';
check('输入框里说清了叫不醒 A', placeholder.includes('不会叫醒 A'), placeholder);
check('按钮不叫「发送」（那暗示有人会收到）', sendLabel === '记录', sendLabel);
check('页脚源码里说清了要 A 听见该去哪', hintSrc.includes('Codex'), hintSrc.slice(0, 80));

// 光看源码不够——真把 renderLegend 跑一遍，看它有没有写进 DOM
if (!sandbox.__probe || typeof sandbox.__probe.renderLegend !== 'function') {
  check('renderLegend 可被调用（探针挂上了）', false);
} else {
  sandbox.__probe.setRoles(
    { HUMAN: ['say', 'kill'], A: ['task'], B: ['deliver'], SYSTEM: ['gate'] },
    { say: '发言', kill: '掐断', task: '任务', deliver: '交付', gate: '机械闸' },
  );
  sandbox.__probe.renderLegend();
  check('图例按角色渲染了 4 行', registry.legendBody.children.length === 4,
    registry.legendBody.children.length);
  check('页脚写进了 DOM 且点明去 Codex 说', registry.hint.textContent.includes('Codex'),
    registry.hint.textContent);
  check('页脚点明掐断才是真机制', registry.hint.textContent.includes('掐断'),
    registry.hint.textContent);
}

// 待办栏（T-007）：人这一侧要能看见"还欠着谁什么"，并且**点一下就勾掉**。
// 这里盯源码钩子；真正的端到端（POST /api/todo_done 之后 bus.todos 少一条）
// 由 A 在真服务上验，读数记在 reports/T-007.md。
console.log('待办栏');
check('页面有等待办栏容器', page.includes('data-todos'), 'data-todos');
check(
  '待办行用 data-todo 标注',
  js.includes("setAttribute('data-todo'") || js.includes('data-todo='),
  'setAttribute(data-todo)',
);
check(
  '每行带完成按钮 data-done',
  js.includes("setAttribute('data-done'") || js.includes('data-done='),
  'setAttribute(data-done)',
);
check('完成按钮打到 /api/todo_done', js.includes('/api/todo_done'), '/api/todo_done');
check(
  '服务端也预渲染了待办行（不开 JS 也看得见）',
  /PAGE = """[\s\S]*data-todos/.test(source) && source.includes('open_todos()'),
  'build_page 里的 open_todos()',
);

// 页面版本与"该刷新了"横幅（T-010）：改完界面，人那一侧得知道。
// 这里盯源码钩子；行为级（版本不一致真的插横幅）还没法在这个沙盒里驱动——
// 沙盒只喂 renderLive/render 的假数据，版本比对发生在 tick() 里。
console.log('页面版本与刷新横幅');
check('页面里嵌了 PAGE_VERSION', source.includes('PAGE_VERSION'), 'PAGE_VERSION');
check('前端会读 page_version', js.includes('page_version'), 'page_version');
check('不一致时插入 data-reload 横幅', js.includes('data-reload'), 'data-reload');
check('横幅带刷新按钮 data-reload-btn', js.includes('data-reload-btn'), 'data-reload-btn');
check('点刷新是 location.reload()', js.includes('location.reload()'), 'location.reload()');
check(
  '不自动重载（人可能正在打字）',
  !/setTimeout\([^)]*reload/i.test(js) && !/setInterval\([^)]*reload/i.test(js),
  '没有定时自动 reload',
);

console.log('');
if (failed) { console.log(`✗ ${failed} 条不通过`); process.exit(1); }
console.log('✓ 页面渲染全部通过');
