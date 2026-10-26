const state = { tasks: [], selected: null, evaluating: false };
const $ = (id) => document.getElementById(id);
const statusNames = { open: '待接取', claimed: '已接取', in_progress: '修复中', review: '待复核', done: '已完成' };
const transitions = { open: [], claimed: ['in_progress'], in_progress: ['review'], review: ['done', 'in_progress'], done: [] };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.add('visible');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $('toast').classList.remove('visible'), 3500);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}
function agentName() {
  const name = $('agent-name').value.trim();
  if (!name) throw new Error('请先填写当前 Agent 名称');
  localStorage.setItem('mcc-agent-name', name);
  return name;
}
function renderSummary(summary) {
  const project = summary.project || {};
  $('project-meta').textContent = `v${project.version || 'unknown'} · ${project.branch || 'unknown'} · ${project.head || 'unknown'}`;
  $('pass-rate').textContent = summary.pass_rate === null ? '—' : `${summary.pass_rate}%`;
  $('test-total').textContent = summary.evaluation && summary.evaluation.results.length
    ? `${summary.passed} 通过 / ${summary.failed} 失败` : '尚未运行评估';
  $('open-count').textContent = summary.open;
  $('active-count').textContent = summary.claimed + summary.in_progress + summary.review;
  $('done-count').textContent = summary.done;
  $('task-count').textContent = `${summary.total} 项任务`;
}
function renderEvaluation(evaluation) {
  const running = evaluation.state === 'running';
  state.evaluating = running;
  $('evaluate').disabled = running;
  $('evaluate').textContent = running ? '评估运行中…' : '运行项目评估';
  const badge = $('evaluation-state');
  badge.textContent = running ? '运行中' : evaluation.state === 'complete' ? '已完成' : '未运行';
  badge.className = `status ${evaluation.state}`;
  const tbody = $('evaluation-rows');
  tbody.replaceChildren();
  const results = evaluation.results || [];
  if (!results.length) {
    const row = element('tr');
    row.append(element('td', 'empty', running ? '正在启动测试…' : '点击“运行项目评估”获取当前代码的真实结果。'));
    row.firstChild.colSpan = 4;
    tbody.append(row);
    return;
  }
  for (const result of results) {
    const row = element('tr');
    row.title = (result.command || []).join(' ');
    row.append(element('td', '', result.name));
    row.append(element('td', '', String(result.returncode)));
    row.append(element('td', '', `${result.duration_sec}s`));
    row.append(element('td', result.returncode === 0 ? 'status done' : 'status open', result.returncode === 0 ? '通过' : '失败'));
    tbody.append(row);
  }
}
function taskMatchesFilter(task) {
  return !$('status-filter').value || task.status === $('status-filter').value;
}
function renderTasks() {
  const tasks = state.tasks.filter(taskMatchesFilter);
  const signature = JSON.stringify([$('status-filter').value,
    tasks.map(task => [task.id, task.status, task.agent, task.updated_at])]);
  if (state.taskSignature === signature) return;
  state.taskSignature = signature;
  const list = $('task-list');
  list.replaceChildren();
  if (!tasks.length) {
    list.append(element('p', 'empty', '当前筛选下没有任务。'));
    return;
  }
  for (const task of tasks) {
    const card = element('article', 'task-card');
    card.tabIndex = 0;
    card.setAttribute('aria-label', `${task.id} ${task.title}`);
    card.addEventListener('click', () => openTask(task.id));
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openTask(task.id); }
    });
    const header = element('div', 'task-card-header');
    header.append(element('span', `priority ${task.priority}`, task.priority));
    header.append(element('span', `status ${task.status}`, statusNames[task.status]));
    card.append(header);
    card.append(element('h3', '', `${task.id} · ${task.title}`));
    card.append(element('p', '', task.evidence));
    const meta = element('div', 'task-card-meta');
    meta.append(element('span', '', task.agent ? `Agent：${task.agent}` : '等待 Agent 接取'));
    meta.append(element('span', '', `${task.acceptance.length} 项验收`));
    card.append(meta);
    const actions = element('div', 'task-card-actions');
    if (task.status === 'open') {
      const claim = element('button', 'primary', '接取');
      claim.addEventListener('click', (event) => { event.stopPropagation(); claimTask(task.id); });
      actions.append(claim);
    }
    const detail = element('button', 'secondary', '详情');
    detail.addEventListener('click', (event) => { event.stopPropagation(); openTask(task.id); });
    actions.append(detail);
    card.append(actions);
    list.append(card);
  }
}
function section(title, values, code = false) {
  const wrapper = element('section', 'detail-section');
  wrapper.append(element('h3', '', title));
  for (const value of values) wrapper.append(code ? element('code', '', value) : element('p', '', value));
  return wrapper;
}
function openTask(id) {
  const task = state.tasks.find(item => item.id === id);
  if (!task) return;
  state.selected = task;
  $('dialog-priority').textContent = task.priority;
  $('dialog-priority').className = `priority ${task.priority}`;
  $('dialog-title').textContent = `${task.id} · ${task.title}`;
  const body = $('dialog-body');
  body.replaceChildren();
  body.append(section('问题证据', [task.evidence]));
  body.append(section('影响范围', task.scope, true));
  body.append(section('实施要求', task.requirements));
  body.append(section('验收命令', task.acceptance, true));
  if (task.dependencies.length) body.append(section('依赖', task.dependencies));
  const history = element('section', 'detail-section');
  history.append(element('h3', '', '状态与 Agent 历史'));
  const entries = element('div', 'history');
  for (const item of task.history.slice().reverse()) {
    entries.append(element('div', 'history-item', `${item.at} · ${item.agent || 'system'} · ${item.action} · ${item.note}`));
  }
  history.append(entries);
  body.append(history);
  $('claim-task').hidden = task.status !== 'open';
  $('release-task').hidden = task.status === 'open' || task.status === 'done';
  const next = $('next-status');
  next.replaceChildren();
  for (const status of transitions[task.status]) {
    const option = element('option', '', statusNames[status]);
    option.value = status;
    next.append(option);
  }
  next.value = transitions[task.status][0] || '';
  $('update-status').hidden = transitions[task.status].length === 0;
  $('task-dialog').showModal();
}
async function claimTask(id) {
  try {
    const task = await api(`/api/tasks/${id}/claim`, { method: 'POST', body: JSON.stringify({ agent: agentName() }) });
    toast(`${id} 已由 ${task.agent} 接取`);
    if ($('task-dialog').open) $('task-dialog').close();
    await refreshAll();
  } catch (error) { toast(error.message); }
}
async function releaseTask() {
  const task = state.selected;
  if (!task) return;
  try {
    await api(`/api/tasks/${task.id}/release`, { method: 'POST', body: JSON.stringify({ agent: agentName() }) });
    $('task-dialog').close();
    toast(`${task.id} 已释放，其他 Agent 可接取`);
    await refreshAll();
  } catch (error) { toast(error.message); }
}
async function updateStatus() {
  const task = state.selected;
  if (!task) return;
  try {
    await api(`/api/tasks/${task.id}/status`, { method: 'POST', body: JSON.stringify({
      agent: agentName(), status: $('next-status').value, note: `由 ${agentName()} 更新为 ${statusNames[$('next-status').value]}` }) });
    $('task-dialog').close();
    toast(`${task.id} 状态已更新`);
    await refreshAll();
  } catch (error) { toast(error.message); }
}
async function refreshEvaluation() {
  const evaluation = await api('/api/evaluation');
  renderEvaluation(evaluation);
  return evaluation.state === 'running';
}
async function refreshAll() {
  const [summary, tasks] = await Promise.all([api('/api/summary'), api('/api/tasks')]);
  renderSummary(summary);
  state.tasks = tasks.tasks;
  renderTasks();
  await refreshEvaluation();
}
async function startEvaluation() {
  try {
    await api('/api/evaluate', { method: 'POST', body: '{}' });
    renderEvaluation({ state: 'running', results: [] });
    await pollEvaluation();
  } catch (error) { toast(error.message); }
}
$('evaluate').addEventListener('click', startEvaluation);
$('refresh').addEventListener('click', () => refreshAll().catch(error => toast(error.message)));
$('status-filter').addEventListener('change', renderTasks);
$('agent-name').value = localStorage.getItem('mcc-agent-name') || 'kimi-code';
$('dialog-close').addEventListener('click', () => $('task-dialog').close());
$('claim-task').addEventListener('click', () => claimTask(state.selected.id));
$('release-task').addEventListener('click', releaseTask);
$('update-status').addEventListener('click', updateStatus);
$('task-dialog').addEventListener('click', (event) => {
  if (event.target === $('task-dialog')) {
    const rect = $('task-dialog').getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $('task-dialog').close();
  }
});
let pollInFlight = false;
async function pollEvaluation() {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    const wasRunning = state.evaluating;
    const running = await refreshEvaluation();
    if (wasRunning && !running) {
      await refreshAll();
      toast('评估已结束，任务列表已更新');
    } else if (!running) {
      const [summary, tasks] = await Promise.all([api('/api/summary'), api('/api/tasks')]);
      renderSummary(summary);
      state.tasks = tasks.tasks;
      renderTasks();
    }
  } catch (error) {
    toast(error.message);
  } finally {
    pollInFlight = false;
  }
}
refreshAll().catch(error => toast(error.message));
setInterval(pollEvaluation, 1500);
