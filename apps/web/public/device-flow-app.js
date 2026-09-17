/* 设备流转管理（内嵌于技术支持系统的设备管理页面）
 * 由 DeviceFlowPage 挂载后调用 window.deviceFlowApp.init() 启动，
 * 卸载时调用 dispose() 清理事件与缓存。业务数据仍走 /api/html-device-flow。 */
(() => {
const $ = id => document.getElementById(id);
const DB_KEY = 'device_flow_records_v28_real', DEV_KEY = 'device_flow_devices_v28_real', SET_KEY = 'device_flow_settings_v28_real', RECYCLE_KEY = 'device_flow_recycle_v28_real';
const photoLabels = ['正面', '背面', '左侧', '右侧', '顶部', '底部', '配件图1', '配件图2'];
let currentPhotos = {}, currentAgreement = null, editingRecordId = null;
let selectedPhotoKey = null;
let draggingPhotoKey = null;
let currentDeviceFilter = '借测中';
let recycleTab = 'records';
let dashboardAction = 'overdue';
const VIEW_STATE_KEY = 'device_flow_view_state_v28_real';

/* 数据缓存：避免每次读取都对 1100+ 条记录做深拷贝（原页面切换卡顿的主因）。
 * 所有修改路径都会立即 save()；save 失败（如 409 冲突）时丢弃缓存，回退到服务器状态。 */
const cache = {};
function load(k, def) {
  if (!(k in cache)) cache[k] = flowOnline.load(k, def);
  return cache[k];
}
function save(k, v) {
  cache[k] = v;
  markDirtyFor(k);
  const pending = flowOnline.save(k, v);
  pending.catch(() => { delete cache[k]; });
  return pending;
}

/* 标签页懒渲染：只在首次进入或数据变化后重新渲染对应区块，纯切换不重复渲染。 */
const TAB_KEYS = ['dashboard', 'repairs', 'loans', 'recycle'];
const renderedTabs = new Set();
const dirtyTabs = new Set();
const tabRenderers = {
  dashboard() { renderDashboard(); renderDevices(); },
  repairs() { renderRecords('repair'); },
  loans() { renderRecords('loan'); },
  recycle() { renderRecycleBin(); },
};
function markDirtyFor(key) {
  const map = {
    [DB_KEY]: ['dashboard', 'repairs', 'loans'],
    [DEV_KEY]: ['dashboard'],
    [RECYCLE_KEY]: ['recycle', 'dashboard'],
  };
  (map[key] || []).forEach(t => dirtyTabs.add(t));
}

/* 前端组件（Excel/PDF/压缩/OCR）按需加载，不再随页面启动拉取 5 个 CDN 脚本。 */
const CDN_LIBS = {
  html2canvas: 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js',
  jspdf: 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js',
  tesseract: 'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js',
  jszip: 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js',
  xlsx: 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js',
};
const cdnPending = {};
function ensureCdn(name) {
  if (window[name]) return Promise.resolve();
  if (!cdnPending[name]) {
    cdnPending[name] = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = CDN_LIBS[name];
      script.onload = () => resolve();
      script.onerror = () => { delete cdnPending[name]; reject(new Error(name + ' 组件加载失败')); };
      document.head.append(script);
    });
  }
  return cdnPending[name];
}

function migrateLoanStatuses() {
  let arr = load(DB_KEY, []), changed = false;
  arr.forEach(r => {
    if (r.type !== 'loan') return;
    if (['已收回', '已完成'].includes(r.status)) { r.status = '已归还'; changed = true; }
    else if (r.status !== '已归还' && r.status !== '借测中') { r.status = '借测中'; changed = true; }
  });
  if (changed) save(DB_KEY, arr);
}
function esc(s = '') { return String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m])) }
function nowStr() { return new Date().toLocaleString('zh-CN', { hour12: false }) }
function uid(prefix) { return prefix + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 7) }
function nextOrderNo(type) {
  const d = new Date(), y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  const prefix = type === 'repair' ? 'WX' : 'JC', base = `${prefix}${y}${m}${day}`;
  const used = load(DB_KEY, []).map(r => r.orderNo || '').filter(x => x.startsWith(base));
  const nums = used.map(x => parseInt(x.slice(-3), 10) || 0); return base + '-' + String((nums.length ? Math.max(...nums) : 0) + 1).padStart(3, '0');
}
function displayOrderNo(r) { const no = String(r.orderNo || '').trim(); if (/^IMPORT-/i.test(no) || /^IMPORT-/i.test(String(r.id || ''))) return ''; return no; }
function logisticsText(r, html = false) {
  const sep = html ? '<br>' : ' / ';
  if (r.type === 'loan') return `寄出：${esc(r.outboundTracking || '待录入')}${sep}归还：${esc(r.inboundTracking || '待录入')}`;
  return `客户寄回：${esc(r.inboundTracking || '待录入')}${sep}维修返还：${esc(r.outboundTracking || '待录入')}`;
}
function recordHasSN(r, sn) {
  return r && (r.sn === sn || (Array.isArray(r.snList) && r.snList.includes(sn)));
}
function recordSNDisplay(r) {
  if (Array.isArray(r.snList) && r.snList.length > 1) return `${r.snList[0]} +${r.snList.length - 1}`;
  return r.sn || '-';
}
function getFollowUps(r) { return Array.isArray(r.followUps) ? r.followUps : [] }
function latestFollowUp(r) {
  const a = getFollowUps(r); return a.length ? a[a.length - 1] : null;
}
function followUpSummaryHtml(r) {
  const f = latestFollowUp(r);
  if (!f) return '<span class="label">-</span>';
  const meta = [f.date || '', f.person || ''].filter(Boolean).join(' · ');
  const txt = String(f.text || '');
  const short = txt.length > 65 ? txt.slice(0, 65) + '…' : txt;
  return `<div class="followup-latest">${meta ? `<div class="who">${esc(meta)}</div>` : ''}<div class="txt">${esc(short)}</div></div>`;
}
async function addFollowUp(recordId) {
  let arr = load(DB_KEY, []), r = arr.find(x => x.id === recordId); if (!r) return;
  const person = ($('fuPerson')?.value || '').trim();
  const date = ($('fuDate')?.value || '').trim();
  const content = ($('fuText')?.value || '').trim();
  if (!content) { alert('请填写跟进情况。'); return }
  if (!Array.isArray(r.followUps)) r.followUps = [];
  r.followUps.push({ id: uid('FU'), person, date, text: content, source: '系统新增' });
  r.updatedAt = date || nowStr();
  await save(DB_KEY, arr);
  renderRecords('loan'); renderDashboard(); renderDevices(); openRecord(recordId);
}
async function removeFollowUp(recordId, followId) {
  if (!confirm('确认删除这条跟进记录？')) return;
  let arr = load(DB_KEY, []), r = arr.find(x => x.id === recordId); if (!r) return;
  r.followUps = getFollowUps(r).filter(x => x.id !== followId);
  await save(DB_KEY, arr); renderRecords('loan'); renderDevices(); openRecord(recordId);
}
function followUpTimelineHtml(r) {
  const items = getFollowUps(r);
  const today = new Date().toISOString().slice(0, 10);
  const form = `<div class="followup-form">
    <div><label>跟进日期</label><input id="fuDate" type="date" value="${today}"></div>
    <div><label>跟进人</label><input id="fuPerson" list="followPersonList" placeholder="选择或输入姓名"><datalist id="followPersonList"><option value="侯智超"><option value="刘海焕"><option value="屈腾"><option value="杨明辉"><option value="游子超"><option value="智毅斐"><option value="朱靖"></datalist></div>
    <div><label>跟进内容</label><textarea id="fuText" placeholder="例如：9月14日电话沟通，客户预计下周归还"></textarea></div>
    <div><button class="btn primary" onclick="addFollowUp('${r.id}')">添加跟进</button></div>
  </div>`;
  const timeline = items.length ? `<div class="followup-timeline">${items.slice().reverse().map(f => {
    const meta = [f.date || '', f.person || ''].filter(Boolean).join(' · ') || '未填写跟进人/日期';
    return `<div class="followup-item"><div class="followup-meta">${esc(meta)}</div><div class="followup-text">${esc(f.text || '')}</div>${f.source ? `<div class="source-note">${esc(f.source)}</div>` : ''}${f.source === '系统新增' ? `<div style="margin-top:7px"><button class="btn danger" onclick="removeFollowUp('${r.id}','${f.id}')">删除此条</button></div>` : ''}</div>`;
  }).join('')}</div>` : '<div class="empty" style="padding:18px">暂无跟进记录</div>';
  return `<div class="divider"></div><div class="subhead">跟进情况</div>${form}${timeline}`;
}

function closeAllDrawers() {
  $('drawer').classList.remove('open'); $('newRecord').classList.remove('open'); $('drawerOverlay').classList.remove('open'); if ($('imageLightbox')) closeLightbox();
}
function getViewState() {
  try { return JSON.parse(sessionStorage.getItem(VIEW_STATE_KEY) || '{}') } catch (e) { return {} }
}
let currentTab = 'dashboard';
function saveViewState(extra = {}) {
  try {
    const prev = getViewState();
    const state = Object.assign({}, prev, extra);
    state.scroll = Object.assign({}, prev.scroll, { [currentTab]: window.scrollY || 0 });
    sessionStorage.setItem(VIEW_STATE_KEY, JSON.stringify(state));
  } catch (e) { }
}
function showTab(id, opts = {}) {
  closeAllDrawers();
  document.querySelectorAll('.flow-tabs button').forEach(x => x.classList.toggle('active', x.dataset.tab === id));
  document.querySelectorAll('.section').forEach(s => s.classList.toggle('active', s.id === id));
  currentTab = id;
  if (!renderedTabs.has(id) || dirtyTabs.has(id)) {
    const renderer = tabRenderers[id];
    if (renderer) { renderer(); renderedTabs.add(id); dirtyTabs.delete(id); }
  }
  if (!opts.skipSave) saveViewState({ tab: id });
  if (!opts.skipScroll) {
    const pos = (getViewState().scroll || {})[id] || 0;
    requestAnimationFrame(() => window.scrollTo(0, pos));
  }
}
function setRecordPageType(type, editing = false) {
  $('rType').value = type; toggleTypeFields();
  if (editing) {
    $('recordTitle').textContent = type === 'repair' ? '编辑维修工单' : '编辑借测单';
    $('recordSubtitle').textContent = type === 'repair' ? '修改维修、物流、处理过程和寄返信息。' : '修改借测设备、物流、配件、照片和归还信息。';
  } else {
    $('recordTitle').textContent = type === 'repair' ? '新建维修工单' : '新建借测单';
    $('recordSubtitle').textContent = type === 'repair' ? '记录客户寄回、故障、维修过程以及维修后寄返信息。' : '记录借测设备、借测客户、配件、寄出与归还信息。';
  }
}
function openRecordDrawer() {
  $('newRecord').classList.add('open');
  $('drawerOverlay').classList.add('open');
  const sn = $('rSN'); if (sn) setTimeout(() => sn.focus(), 60);
}
function recordFormHasContent() {
  return ['rSN', 'rModel', 'rCustomer', 'rContact', 'rPhone', 'rAddress', 'rAppearance', 'rReason', 'rInboundTracking', 'rOutboundTracking', 'rNotes', 'rAccessoriesRepair', 'lStart', 'lDue', 'rReportDate'].some(id => $(id) && $(id).value)
    || !!(currentAgreement && currentAgreement.data)
    || !!(currentPhotos && Object.keys(currentPhotos).length)
    || !!editingRecordId;
}
function requestCloseRecordDrawer() {
  if (!recordFormHasContent()) { closeAllDrawers(); return; }
  if (confirm('关闭后未保存的表单内容将丢失，确认关闭？')) closeAllDrawers();
}
function goNew(type) {
  closeAllDrawers();
  resetRecordForm();
  $('rType').value = type; toggleTypeFields(); setRecordPageType(type, false);
  openRecordDrawer();
}
function backToRecordList() { requestCloseRecordDrawer(); }
function overlayClick() {
  if ($('newRecord').classList.contains('open')) requestCloseRecordDrawer();
  else closeAllDrawers();
}
function toggleTypeFields() {
  let repair = $('rType').value === 'repair';
  $('repairFields').classList.toggle('hidden', !repair);
  $('loanFields').classList.toggle('hidden', repair);
  $('pdfBtn').classList.toggle('hidden', !repair);

  const statuses = repair ? ['待寄回', '维修中', '已完成'] : ['借测中', '已归还'];
  $('rStatus').innerHTML = statuses.map(s => `<option>${s}</option>`).join('');

  $('outboundCarrierWrap').classList.toggle('hidden', repair);
  $('repairOutboundFixed').classList.toggle('hidden', !repair);

  $('loanAccessoriesWrap').classList.toggle('hidden', repair);
  $('repairAccessoriesWrap').classList.toggle('hidden', !repair);

  // 借测单不使用维修用语；物流区按“寄出 → 归还 → 状态 → 配件”排列
  $('notesSectionTitle').textContent = repair ? '维修过程 / 备注' : '借测备注';
  $('rNotes').placeholder = repair
    ? '记录检测结果、维修动作、更换件、复测结果、维修备注等'
    : '记录借测用途、使用反馈、归还约定等借测备注';
  const grid = $('logisticsGrid')
  if (grid) {
    const order = repair
      ? ['fInboundCarrier', 'fInboundTracking', 'fStatus', 'outboundCarrierWrap', 'fOutboundTracking', 'repairOutboundFixed', 'loanAccessoriesWrap', 'repairAccessoriesWrap']
      : ['outboundCarrierWrap', 'fOutboundTracking', 'fInboundCarrier', 'fInboundTracking', 'fStatus', 'loanAccessoriesWrap', 'repairAccessoriesWrap', 'repairOutboundFixed'];
    order.forEach(id => { const node = $(id); if (node) grid.appendChild(node) });
  }
  if (repair) {
    $('rOutboundCarrier').value = '顺丰';
    $('customerSectionTitle').textContent = '报修客户与联系人';
    $('customerLabel').textContent = '报修单位 *';
    $('contactLabel').textContent = '报修人';
    $('addressLabel').textContent = '维修后回寄地址';
    $('inboundCarrierLabel').textContent = '客户寄回物流公司';
    $('inboundTrackingLabel').textContent = '客户寄回快递单号';
    $('outboundTrackingLabel').textContent = '维修后返还快递单号';
  } else {
    $('customerSectionTitle').textContent = '借测客户与联系人';
    $('customerLabel').textContent = '借测客户 *';
    $('contactLabel').textContent = '联系人';
    $('addressLabel').textContent = '客户通讯地址';
    $('inboundCarrierLabel').textContent = '客户归还物流公司';
    $('inboundTrackingLabel').textContent = '客户归还快递单号';
    $('outboundTrackingLabel').textContent = '借测寄出快递单号';
  }
}
function renderPhotoGrid() {
  $('photoGrid').innerHTML = photoLabels.map((lab, i) => {
    const src = currentPhotos[i];
    const selected = Number(selectedPhotoKey) === i ? ' selected' : '';
    if (src) {
      return `<div class="photo-slot has-photo${selected}" id="slot${i}" draggable="true"
        onclick="selectPhotoSlot(event,${i})"
        ondragstart="photoDragStart(event,${i})"
        ondragend="photoDragEnd(event)"
        ondragenter="photoDragEnter(event,${i})"
        ondragover="photoDragOver(event,${i})"
        ondragleave="photoDragLeave(event)"
        ondrop="photoDrop(event,${i})">
        <img src="${src}" alt="${esc(lab)}" onclick="event.stopPropagation();previewCurrentPhoto(${i})">
        <span class="photo-drag-tip">拖动换位置</span>
        <button type="button" class="photo-remove" title="删除图片" onclick="event.stopPropagation();removeCurrentPhoto(${i})">删除</button>
        <span class="photo-view" onclick="event.stopPropagation();previewCurrentPhoto(${i})">查看大图</span>
        <span class="photo-change">更换图片</span>
        <input type="file" accept="image/*" title="更换${esc(lab)}" onchange="handlePhoto(event,${i})">
      </div>`;
    }
    return `<div class="photo-slot${selected}" id="slot${i}"
      onclick="selectPhotoSlot(event,${i})"
      ondragenter="photoDragEnter(event,${i})"
      ondragover="photoDragOver(event,${i})"
      ondragleave="photoDragLeave(event)"
      ondrop="photoDrop(event,${i})">
      <span>${lab}<br>点击上传</span>
      <input type="file" accept="image/*" title="上传${esc(lab)}" onchange="handlePhoto(event,${i})">
    </div>`;
  }).join('');
}
function selectPhotoSlot(e, key) {
  if (e && e.target && e.target.tagName === 'INPUT') return;
  selectedPhotoKey = Number(key);
  renderPhotoGrid();
}
function previewCurrentPhoto(photoKey) {
  lightboxItems = Object.entries(currentPhotos || {}).filter(([, v]) => v).map(([i, src]) => ({ key: Number(i), src, label: photoLabels[Number(i)] || '照片' }));
  if (!lightboxItems.length) return;
  const pos = lightboxItems.findIndex(x => x.key === Number(photoKey));
  lightboxIndex = pos >= 0 ? pos : 0;
  renderLightbox();
  $('imageLightbox').classList.add('open');
}
function removeCurrentPhoto(key) {
  if (!currentPhotos[key]) return;
  if (!confirm(`确认删除“${photoLabels[Number(key)] || '该'}”图片？`)) return;
  delete currentPhotos[key];
  if (Number(selectedPhotoKey) === Number(key)) selectedPhotoKey = null;
  renderPhotoGrid();
}
function photoDragStart(e, key) {
  if (!currentPhotos[key]) { e.preventDefault(); return }
  draggingPhotoKey = Number(key);
  selectedPhotoKey = Number(key);
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', String(key));
  requestAnimationFrame(() => { const el = $('slot' + key); if (el) el.classList.add('dragging') });
}
function photoDragEnd() {
  document.querySelectorAll('.photo-slot').forEach(el => el.classList.remove('dragging', 'drag-target'));
  draggingPhotoKey = null;
}
function photoDragEnter(e, key) {
  e.preventDefault();
  const el = $('slot' + key);
  if (el) el.classList.add('drag-target');
}
function photoDragOver(e, key) {
  // 必须 preventDefault，否则浏览器不会允许从资源管理器/企业微信等外部拖入。
  e.preventDefault();
  if (e.dataTransfer) {
    const hasExternalFiles = Array.from(e.dataTransfer.types || []).includes('Files');
    e.dataTransfer.dropEffect = draggingPhotoKey !== null ? 'move' : (hasExternalFiles ? 'copy' : 'copy');
  }
  const el = $('slot' + key);
  if (el) el.classList.add('drag-target');
}
function photoDragLeave(e) {
  if (e.currentTarget) e.currentTarget.classList.remove('drag-target');
}
async function getDroppedImageFile(dt) {
  if (!dt) return null;
  const files = Array.from(dt.files || []);
  let file = files.find(f => f && String(f.type || '').startsWith('image/'));
  if (file) return file;

  // 某些桌面应用通过 DataTransferItem 提供文件。
  const items = Array.from(dt.items || []);
  for (const item of items) {
    if (item.kind === 'file') {
      const f = item.getAsFile && item.getAsFile();
      if (f && String(f.type || '').startsWith('image/')) return f;
    }
  }
  return null;
}
async function photoDrop(e, targetKey) {
  e.preventDefault(); e.stopPropagation();
  document.querySelectorAll('.photo-slot').forEach(el => el.classList.remove('dragging', 'drag-target'));
  targetKey = Number(targetKey);

  // 1. 外部图片：资源管理器、桌面、支持标准文件拖放的聊天软件。
  const externalFile = await getDroppedImageFile(e.dataTransfer);
  if (externalFile) {
    try {
      currentPhotos[targetKey] = await compressImageFile(externalFile);
      selectedPhotoKey = targetKey;
      draggingPhotoKey = null;
      renderPhotoGrid();
    } catch (err) {
      console.error(err);
      alert('图片拖入失败，请尝试先把图片保存到桌面后再拖入，或点击该位置上传。');
    }
    return;
  }

  // 2. 页面内部图片：在“正面/背面/左侧...”槽位之间交换。
  const rawSource = draggingPhotoKey !== null ? draggingPhotoKey : (e.dataTransfer ? e.dataTransfer.getData('text/plain') : '');
  const sourceKey = Number(rawSource);
  if (Number.isNaN(sourceKey) || sourceKey === targetKey) { draggingPhotoKey = null; return }

  const sourceImg = currentPhotos[sourceKey];
  const targetImg = currentPhotos[targetKey];
  if (sourceImg) currentPhotos[targetKey] = sourceImg; else delete currentPhotos[targetKey];
  if (targetImg) currentPhotos[sourceKey] = targetImg; else delete currentPhotos[sourceKey];

  selectedPhotoKey = targetKey;
  draggingPhotoKey = null;
  renderPhotoGrid();
}
async function compressImageFile(file, maxSide = 1600, quality = 0.82) {
  if (!file || !file.type.startsWith('image/')) return null;
  const dataUrl = await new Promise((resolve, reject) => { const fr = new FileReader(); fr.onload = () => resolve(fr.result); fr.onerror = reject; fr.readAsDataURL(file) });
  const img = await new Promise((resolve, reject) => { const im = new Image(); im.onload = () => resolve(im); im.onerror = reject; im.src = dataUrl });
  let w = img.width, h = img.height;
  const scale = Math.min(1, maxSide / Math.max(w, h)); w = Math.round(w * scale); h = Math.round(h * scale);
  const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d'); ctx.drawImage(img, 0, 0, w, h);
  let q = quality, out = canvas.toDataURL('image/jpeg', q);
  while (out.length > 700 * 1024 * 1.37 && q > 0.55) { q -= 0.07; out = canvas.toDataURL('image/jpeg', q); }
  return out;
}
async function handlePhoto(e, i) {
  const f = e.target.files[0]; if (!f) return;
  try {
    const compressed = await compressImageFile(f);
    currentPhotos[i] = compressed || '';
    renderPhotoGrid();
  } catch (err) {
    alert('图片处理失败，请重新选择图片。');
  }
}

async function extractPdfTextFromDataUrl(dataUrl) {
  try {
    const base64 = (dataUrl.split(',')[1] || '');
    const raw = atob(base64), bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const pdfjsLib = await import('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.7.76/pdf.min.mjs');
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.7.76/pdf.worker.min.mjs';
    const pdf = await pdfjsLib.getDocument({ data: bytes }).promise;
    let out = '';
    for (let p = 1; p <= pdf.numPages; p++) {
      const page = await pdf.getPage(p);
      const content = await page.getTextContent();
      out += ' ' + content.items.map(x => x.str).join(' ');
    }
    return out.replace(/\s+/g, ' ').trim();
  } catch (err) {
    console.error('agreement pdf parse failed', err);
    return '';
  }
}
function pickAgreement(text, regs) {
  for (const rx of regs) { const m = text.match(rx); if (m && m[1]) return m[1].trim() }
  return '';
}
function parseLoanAgreementText(raw) {
  const spaced = String(raw || '').replace(/ /g, ' ').replace(/[|｜]/g, ' ').replace(/\s+/g, ' ').trim();
  if (!spaced) return {};
  const t = spaced.replace(/\s+/g, '').replace(/[：:]/g, '');

  // Always isolate CUSTOMER / 试用方 first, so supplier fields never overwrite customer fields.
  const cb = (t.match(/(?:CUSTOMER|试用方(?:（盖章）)?)([\s\S]*?)(?:SUPPLIER|供方(?:（盖章）)?)/i) || [])[1] || t;

  const company = pickAgreement(cb, [
    /公司名称(.{2,80}?有限公司)(?=信用代码|纳税人识别号|通讯地址|地址|开户银行)/,
    /公司名称(.{2,80}?公司)(?=信用代码|纳税人识别号|通讯地址|地址|开户银行)/
  ]);

  const address = pickAgreement(cb, [
    /通讯地址(.{6,160}?)(?=开户银行|银行账号|授权代表|联系电话|邮件地址)/,
    /地址(.{6,160}?)(?=电话|开户银行|账号|授权代表|联系电话)/
  ]);

  const contact = pickAgreement(cb, [
    /授权代表([一-龥·]{2,8})(?=联系电话|邮件地址)/,
    /收件人([一-龥·]{2,8})(?=联系电话|电话|1[3-9]\d{9})/
  ]);

  const phone = pickAgreement(cb, [
    /联系电话(1[3-9]\d{9})/,
    /收件电话(1[3-9]\d{9})/,
    /(1[3-9]\d{9})/
  ]);

  const agreementNo = pickAgreement(t, [/协议编码([A-Z0-9\-]+)/i]);
  const signDate = pickAgreement(t, [/签署日期(\d{4}[-/.]\d{2}[-/.]\d{2})/]).replace(/[/.]/g, '-');

  let model = pickAgreement(t, [
    /RVC-?([A-Z]\d{3,6}[A-Z0-9]*)/i,
    /货品描述\/?型号[\s\S]{0,80}?([MIPG]\d{3,6}(?:V\d)?)/i,
    /\b([MIPG]\d{3,6})\b/i
  ]);
  if (model) model = model.toUpperCase();

  const dueDate = pickAgreement(t, [
    /归还时间(?:（试用期限截止日）)?(\d{4}[-./]\d{2}[-./]\d{2})/,
    /(\d{4}[-./]\d{2}[-./]\d{2})(?=[\s\S]{0,20}(?:备注|TERM|NOTES))/i
  ]).replace(/\./g, '-').replace(/\//g, '-');

  const note = pickAgreement(t, [
    /备注(?:（配件\/线缆等）)?(.{1,140}?)(?=特殊情况|1\.试用产品质量|协议约定|TERMS)/,
    /(含.{1,120}?)(?=特殊情况|协议约定|TERMS)/
  ]);
  let accessories = '';
  if (/25M线缆/i.test(note)) accessories = '25m标配';
  else if (/15M线缆/i.test(note)) accessories = '15m标配';
  else if (/5M线缆/i.test(note)) accessories = '5m标配';
  else if (/裸机/.test(note)) accessories = '裸机';
  else if (note) accessories = note;

  return { company, address, contact, phone, model, dueDate, accessories, agreementNo, signDate };
}
function renderAgreementRecognition(r = {}) {
  if (!$('agreementAIResult')) return;
  const items = [
    ['客户', r.company], ['联系人', r.contact], ['电话', r.phone], ['地址', r.address],
    ['型号', r.model], ['归还日期', r.dueDate], ['配件', r.accessories], ['协议号', r.agreementNo]
  ].filter(([, v]) => v);
  $('agreementAIResult').innerHTML = items.map(([k, v]) => `<span class="semantic-chip">${k}<strong>${esc(v)}</strong></span>`).join('');
}
function applyAgreementRecognition(r = {}) {
  if (r.company) $('rCustomer').value = r.company;
  if (r.contact) $('rContact').value = r.contact;
  if (r.phone) $('rPhone').value = r.phone;
  if (r.address) $('rAddress').value = r.address;
  if (r.model) $('rModel').value = r.model;
  if (r.dueDate) $('lDue').value = r.dueDate;
  if (r.accessories) {
    if (['裸机', '5m标配', '15m标配', '25m标配'].includes(r.accessories)) $('rAccessories').value = r.accessories;
    else {
      let opt = [...$('rAccessories').options].find(x => x.value === r.accessories);
      if (!opt) { opt = document.createElement('option'); opt.value = r.accessories; opt.textContent = r.accessories; $('rAccessories').appendChild(opt) }
      $('rAccessories').value = r.accessories;
    }
  }
}

async function renderPdfFirstPageToCanvas(dataUrl, scale = 2.1) {
  const base64 = (dataUrl.split(',')[1] || '');
  const raw = atob(base64), bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  const pdfjsLib = await import('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.7.76/pdf.min.mjs');
  pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.7.76/pdf.worker.min.mjs';
  const pdf = await pdfjsLib.getDocument({ data: bytes }).promise;
  const page = await pdf.getPage(1);
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  await page.render({ canvasContext: ctx, viewport }).promise;
  return canvas;
}
async function ocrAgreementPdf(dataUrl) {
  if (!window.Tesseract) { try { await ensureCdn('tesseract') } catch (e) { throw new Error('OCR component unavailable') } }
  if (!window.Tesseract) throw new Error('OCR component unavailable');
  const canvas = await renderPdfFirstPageToCanvas(dataUrl, 2.2);
  $('agreementAINote').textContent = '检测到扫描版协议，正在 OCR 识别第一页，首次使用可能需要几十秒...';
  const result = await Tesseract.recognize(canvas, 'chi_sim+eng', {
    logger: m => {
      if (m.status === 'recognizing text' && $('agreementAINote')) {
        $('agreementAINote').textContent = `扫描件 OCR 识别中... ${Math.round((m.progress || 0) * 100)}%`;
      }
    }
  });
  return (result && result.data && result.data.text) || '';
}
function agreementResultScore(r = {}) {
  return ['company', 'address', 'contact', 'phone', 'model', 'dueDate', 'accessories', 'agreementNo'].filter(k => r[k]).length;
}

async function parseCurrentAgreement() {
  if (!currentAgreement || !currentAgreement.data) { alert('请先上传借测协议。'); return }
  if (!((currentAgreement.type || '').includes('pdf') || /\.pdf$/i.test(currentAgreement.name || ''))) {
    $('agreementAINote').textContent = '目前自动识别支持 PDF。Word / 图片文件可以保存，但请手动填写客户信息。';
    return;
  }
  try {
    $('agreementAINote').textContent = '正在读取协议内容...';
    const agreementData = await flowOnline.asDataUrl(currentAgreement.data);
    const textLayer = await extractPdfTextFromDataUrl(agreementData);
    let result = parseLoanAgreementText(textLayer);
    let usedOCR = false;

    // Fixed agreement should normally yield several fields. If too few are found, treat it as scan/image PDF.
    if (!textLayer || textLayer.replace(/\s+/g, '').length < 80 || agreementResultScore(result) < 4) {
      const ocrText = await ocrAgreementPdf(agreementData);
      const ocrResult = parseLoanAgreementText(ocrText);
      if (agreementResultScore(ocrResult) >= agreementResultScore(result)) result = ocrResult;
      usedOCR = true;
    }

    currentAgreement.parsed = result;
    renderAgreementRecognition(result);
    applyAgreementRecognition(result);

    const score = agreementResultScore(result);
    if (score) {
      $('agreementAINote').textContent = (usedOCR ? '扫描件 OCR 识别完成' : '协议识别完成') + '，已自动填入已识别字段，请务必核对后保存。';
    } else {
      $('agreementAINote').textContent = '未能可靠识别协议字段，请手动填写。扫描件清晰度、倾斜、印章遮挡都会影响 OCR。';
    }
  } catch (err) {
    console.error(err);
    $('agreementAINote').textContent = '协议识别失败，请手动填写；文件仍可正常保存。';
  }
}
function renderAgreementStatus() {
  if (!$('agreementStatus')) return;
  const has = currentAgreement && currentAgreement.data;
  $('agreementStatus').textContent = has ? '已添加借测协议' : '未添加借测协议';
  $('agreementStatus').className = has ? 'agreement-ok' : 'agreement-missing';
  $('agreementMeta').textContent = has ? `${currentAgreement.name || '借测协议'}${currentAgreement.size ? ' · ' + formatFileSize(currentAgreement.size) : ''}` : '创建借测工单前必须添加借测协议文档。';
  $('viewAgreementBtn').classList.toggle('hidden', !has);
  $('removeAgreementBtn').classList.toggle('hidden', !has);
  if ($('agreementParseBtn')) $('agreementParseBtn').disabled = !has;
  if (has && currentAgreement.parsed) renderAgreementRecognition(currentAgreement.parsed);
  else if ($('agreementAIResult')) { $('agreementAIResult').innerHTML = ''; $('agreementAINote').textContent = ''; }
}
function formatFileSize(bytes) {
  if (!bytes) return ''; if (bytes < 1024) return bytes + ' B'; if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'; return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}
async function processAgreementFile(f) {
  if (!f) return;
  const allowed = /(\.pdf|\.docx?|\.jpe?g|\.png)$/i.test(f.name || '') || /pdf|word|image/.test(f.type || '');
  if (!allowed) { alert('暂不支持此文件类型，请上传 PDF、Word 或图片。'); return }
  const r = new FileReader();
  r.onload = async () => {
    currentAgreement = { name: f.name, type: f.type || '', size: f.size, data: r.result };
    renderAgreementStatus();
    if ((f.type || '').includes('pdf') || /\.pdf$/i.test(f.name || '')) await parseCurrentAgreement();
  };
  r.readAsDataURL(f);
}
function handleAgreementFile(e) {
  const f = e.target.files && e.target.files[0];
  e.target.value = '';
  processAgreementFile(f);
}
function agreementDragEnter(e) {
  e.preventDefault(); e.stopPropagation();
  $('agreementDropzone').classList.add('dragover');
}
function agreementDragLeave(e) {
  e.preventDefault(); e.stopPropagation();
  if (e.currentTarget === e.target) $('agreementDropzone').classList.remove('dragover');
}
function agreementDrop(e) {
  e.preventDefault(); e.stopPropagation();
  $('agreementDropzone').classList.remove('dragover');
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  processAgreementFile(f);
}
function openDataFile(dataUrl, name = '', mime = '') {
  try {
    if (dataUrl.startsWith('/api/html-device-flow/files/')) {
      const target = (mime.includes('pdf') || mime.startsWith('image/')) ? dataUrl : dataUrl + '?download=1';
      window.open(target, '_blank', 'noopener');
      return;
    }
    const parts = dataUrl.split(',');
    const header = parts[0] || '';
    const base64 = parts[1] || '';
    const detected = (header.match(/data:(.*?);base64/i) || [])[1] || mime || 'application/octet-stream';
    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: detected });
    const url = URL.createObjectURL(blob);

    if (detected.includes('pdf') || detected.startsWith('image/')) {
      const w = window.open(url, '_blank');
      if (!w) {
        const a = document.createElement('a');
        a.href = url;
        a.download = name || '借测协议';
        a.click();
      }
    } else {
      const a = document.createElement('a');
      a.href = url;
      a.download = name || '借测协议';
      a.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (err) {
    console.error(err);
    alert('协议文件打开失败，请重新上传后再试。');
  }
}

function viewAgreement() {
  if (!currentAgreement || !currentAgreement.data) return;
  openDataFile(currentAgreement.data, currentAgreement.name || '借测协议', currentAgreement.type || '');
}
function removeAgreement() { if (!currentAgreement) return; if (!confirm('确认移除当前借测协议？')) return; currentAgreement = null; renderAgreementStatus(); if ($('agreementAIResult')) $('agreementAIResult').innerHTML = ''; if ($('agreementAINote')) $('agreementAINote').textContent = '' }

const KNOWN_MODELS = [
  'M2600', 'M2600 V2', 'M2600V2', 'M51000', 'M52000',
  'I540', 'I3360', 'I2120', 'P5330', 'G52000', 'M51000C', 'M52000C'
];

function normalizeSemanticText(raw = '') {
  return raw
    .replace(/ /g, ' ')
    .replace(/[，,；;|｜\t]+/g, ' ')
    .replace(/\s*\n+\s*/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
function detectPhone(s) {
  const raw = String(s || '').replace(/ /g, ' ');
  const labeledMobile = raw.match(/(?:收件电话|收件人电话|联系人电话|联系电话|手机|手机号)\s*[:：]?\s*(1[3-9]\d{9})/);
  if (labeledMobile) return labeledMobile[1];
  const mobile = raw.match(/(?<!\d)(1[3-9]\d{9})(?!\d)/);
  if (mobile) return mobile[1];
  const labeledLand = raw.match(/(?:电话|联系电话)\s*[:：]?\s*(0\d{2,3}[- ]?\d{7,8})/);
  if (labeledLand) return labeledLand[1];
  const land = raw.match(/(?<!\d)(0\d{2,3}[- ]?\d{7,8})(?!\d)/);
  return land ? land[1] : '';
}
function detectModel(s) {
  const upper = s.toUpperCase();
  const normalizedModels = [...KNOWN_MODELS].sort((a, b) => b.length - a.length);
  for (const m of normalizedModels) {
    const token = m.toUpperCase().replace(/\s+/g, '\\s*');
    const rx = new RegExp('(?:^|[^A-Z0-9])(' + token + ')(?:$|[^A-Z0-9])', 'i');
    const hit = upper.match(rx);
    if (hit) return hit[1].replace(/\s+/g, ' ').toUpperCase();
  }
  // fallback: common RVC-style model naming
  const fallback = s.match(/\b([MIPG]\d{3,5}(?:\s*V\d)?)\b/i);
  return fallback ? fallback[1].toUpperCase().replace(/\s+/g, ' ') : '';
}
function detectSN(s, model = '', structured = false) {
  const raw = String(s || '').replace(/ /g, ' ');
  // Only trust explicit SN labels in structured business text.
  const labeled = raw.match(/(?:\bSN\b|序列号|设备SN)\s*[:：]?\s*([A-Z0-9\-]{6,30})/i);
  if (labeled) return labeled[1].toUpperCase();
  if (structured) return '';

  // Free-form fallback is intentionally conservative.
  const tokens = raw.match(/\b[A-Z0-9-]{8,24}\b/gi) || [];
  const candidates = tokens.filter(t => {
    const u = t.toUpperCase();
    if (/^\d+$/.test(u)) return false;
    if (model && u.replace(/\s+/g, '') === model.toUpperCase().replace(/\s+/g, '')) return false;
    if (/^1[3-9]\d{9}$/.test(u)) return false;
    // Exclude common Chinese unified social credit code shape (18 chars).
    if (/^[0-9A-Z]{18}$/.test(u)) return false;
    return /\d/.test(u) && /[A-Z]/i.test(u);
  });
  return candidates.sort((a, b) => b.length - a.length)[0] || '';
}
function detectAddress(s, phone = '', model = '', sn = '') {
  const raw = String(s || '').replace(/ /g, ' ').replace(/[\t\r]+/g, ' ').replace(/\n+/g, ' \n ').replace(/\s+/g, ' ').trim();
  // Shipping/receiving address wins over invoice/company registered address.
  const shipLabels = /(?:收货地址|收件地址|收货地|收件地|寄送地址|送货地址|邮寄地址|设备寄送地址)\s*[:：]?\s*(.{6,150}?)(?=\s*(?:收件人|联系人|收货人|联系电话|联系手机|手机|电话|公司名称|纳税人识别号|开户行|账号)\s*[:：]?|$)/;
  const sm = raw.match(shipLabels); if (sm) return sm[1].replace(/[，,；;。]+$/, '').trim();
  const labeled = raw.match(/(?:通讯地址|公司地址|办公地址|地\s*址|地址)\s*[:：]?\s*(.{6,140}?)(?=\s*(?:电\s*话|联系电话|开户行|开户银行|账\s*号|银行账号|纳税人识别号|信用代码|授权代表|收件人|联系人)\s*[:：]?|$)/);
  if (labeled) return labeled[1].replace(/[，,；;。]+$/, '').trim();
  let work = ' ' + raw + ' ';
  [phone, model, sn].filter(Boolean).forEach(v => { work = work.replace(new RegExp(v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig'), ' ') });
  // Prefer full province/city/district road/building strings. Supports 园/公园/公元/产业园 and 13C etc.
  const rx = /((?:[一-龥]{2,}(?:省|自治区|特别行政区))?(?:[一-龥]{2,}(?:市|自治州|地区))?(?:[一-龥]{1,}(?:区|县|旗|市))?[一-龥A-Za-z0-9\-]{2,}(?:街道|镇|乡|路|街|大道|巷|村|社区|工业园|产业园|园区|公园|公元|大厦|广场|号|栋|幢|座|室)[一-龥A-Za-z0-9\-号栋幢座室层单元C]*)/;
  const m = work.match(rx); return m ? m[1].trim() : '';
}
function detectName(s, phone = '', model = '', sn = '', address = '', structured = false) {
  const raw = String(s || '').replace(/ /g, ' ');
  const explicit = raw.match(/(?:收件人|联系人|收货人|姓名|报修人|授权代表)\s*[:：]?\s*([一-龥·]{2,6})/);
  if (explicit) return explicit[1];
  if (structured) return '';
  let work = ' ' + raw + ' ';
  [phone, model, sn, address].filter(Boolean).forEach(v => { work = work.replace(new RegExp(v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig'), ' ') });
  work = work.replace(/[：:，,；;()（）]/g, ' ').replace(/\s+/g, ' ').trim();
  const staff = new Set(['侯智超', '刘海焕', '屈腾', '杨明辉', '游子超', '智毅斐', '朱靖']);
  const bad = /(公司|科技|机器人|智能|设备|客户|地址|电话|手机|先生|女士|省|市|区|县|路|街|大道|号|园|镇|乡|维修|借测|开户行|开户银行|银行|账号|帐号|纳税|信用|识别号|型号|单号|跟进)/;
  const cands = work.split(' ').filter(x => /^[一-龥·]{2,4}$/.test(x) && !bad.test(x) && !staff.has(x));
  return cands[0] || '';
}
function semanticParse(raw) {
  const s = normalizeSemanticText(raw);
  // Structured company/profile text must only use explicit labels for ambiguous fields.
  const structured = /(公司名称|纳税人识别号|信用代码|开户行|开户银行|账号|帐号|通讯地址|收货地址|收件地址|授权代表|联系人|收件人|设备SN|\bSN\b|型号|快递单号|物流单号|运单号)\s*[:：]?/i.test(s);

  const phone = detectPhone(s);
  const model = detectModel(s);
  const sn = detectSN(s, model, structured);
  const address = detectAddress(s, phone, model, sn);
  const name = detectName(s, phone, model, sn, address, structured);
  const company = detectCompany(s, name, address);
  const logistics = detectLogistics(s, phone, sn, structured);
  return { name, phone, address, model, sn, company, carrier: logistics.carrier, tracking: logistics.tracking };
}

function detectCompany(s, name = '', address = '') {
  const raw = String(s || '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();

  const explicit = raw.match(/(?:公司名称|客户公司|客户|借测单位|报修单位|单位)\s*[:：]?\s*([^，,；;\n]{2,50}?(?:有限公司|有限责任公司|股份有限公司|公司|研究院|研究所|大学|学院|集团))/);
  if (explicit) return explicit[1].trim();

  const org = raw.match(/([一-龥A-Za-z0-9（）()·\-]{2,45}(?:有限责任公司|股份有限公司|有限公司|科技公司|机器人公司|智能公司|自动化公司|研究院|研究所|大学|学院|集团))/);
  if (org) {
    const v = org[1].trim();
    if (address && v.includes(address)) return '';
    if (name && v === name) return '';
    return v;
  }
  return '';
}
function detectLogistics(s, phone = '', sn = '', structured = false) {
  const raw = String(s || '').replace(/ /g, ' ');
  const carriers = ['顺丰速运', '顺丰', '京东物流', '京东', '德邦', '中通', '圆通', '申通', '韵达', '极兔', 'EMS', '邮政', '跨越速运', '跨越', '安能', '百世'];
  let carrier = '';
  for (const c of carriers) { if (raw.toUpperCase().includes(c.toUpperCase())) { carrier = c; break } }
  const explicit = raw.match(/(?:快递|物流|快递公司|物流公司)\s*[:：]?\s*(顺丰速运|顺丰|京东物流|京东|德邦|中通|圆通|申通|韵达|极兔|EMS|邮政|跨越速运|跨越|安能|百世)/i);
  if (explicit) carrier = explicit[1];

  let tracking = '';
  const labeled = raw.match(/(?:快递单号|物流单号|运单号|快递号|单号)\s*[:：]?\s*([A-Z0-9\-]{8,30})/i);
  if (labeled) tracking = labeled[1];

  // Never guess a bank account / tax ID as tracking in structured company information.
  if (!tracking && carrier && !structured) {
    const tokens = raw.match(/\b[A-Z0-9]{10,30}\b/gi) || [];
    const candidates = tokens.filter(t => {
      if (phone && t === phone) return false;
      if (sn && t.toUpperCase() === sn.toUpperCase()) return false;
      if (/^1[3-9]\d{9}$/.test(t)) return false;
      if (/^[0-9A-Z]{18}$/.test(t)) return false;
      return /^\d{12,20}$/.test(t) || (/^[A-Z]/i.test(t) && /\d/.test(t) && t.length >= 10);
    });
    tracking = candidates.sort((a, b) => b.length - a.length)[0] || '';
  }
  return { carrier, tracking };
}
function renderSemanticPreview(result) {
  const items = [
    ['客户/公司', result.company], ['联系人', result.name], ['电话', result.phone], ['地址', result.address],
    ['型号', result.model], ['SN', result.sn], ['快递', result.carrier], ['快递单号', result.tracking]
  ].filter(([, v]) => v);
  $('semanticResult').innerHTML = items.map(([k, v]) => `<span class="semantic-chip">${k}<strong>${esc(v)}</strong></span>`).join('');
  const missing = [];
  if (!result.name) missing.push('联系人');
  if (!result.phone) missing.push('电话');
  if (!result.address) missing.push('地址');
  if (!result.model) missing.push('型号');
  if (missing.length) {
    $('semanticWarn').textContent = '未识别：' + missing.join('、') + '。可手动补充，不会影响其他已识别字段。';
    $('semanticWarn').classList.remove('hidden');
  } else {
    $('semanticWarn').classList.add('hidden');
  }
}
function parseSemanticInput() {
  const raw = $('semanticInput').value.trim();
  if (!raw) { alert('请先粘贴客户信息。'); return }
  const r = semanticParse(raw);
  renderSemanticPreview(r);
  if (r.company) $('rCustomer').value = r.company;
  if (r.name) $('rContact').value = r.name;
  if (r.phone) $('rPhone').value = r.phone;
  if (r.address) $('rAddress').value = r.address;
  if (r.model) $('rModel').value = r.model;
  if (r.sn) $('rSN').value = r.sn;

  // Logistics mapping depends on work-order type:
  // repair = customer's inbound shipment; loan = outbound shipment to customer.
  if (r.carrier || r.tracking) {
    const type = $('rType').value;
    if (type === 'repair') {
      if (r.carrier) $('rInboundCarrier').value = r.carrier;
      if (r.tracking) $('rInboundTracking').value = r.tracking;
    } else {
      if (r.carrier) $('rOutboundCarrier').value = r.carrier;
      if (r.tracking) $('rOutboundTracking').value = r.tracking;
    }
  }
}
function clearSemanticInput() {
  $('semanticInput').value = '';
  $('semanticResult').innerHTML = '';
  $('semanticWarn').classList.add('hidden');
}
function clearCurrentForm() {
  const hasData = [
    'rSN', 'rModel', 'rCustomer', 'rContact', 'rPhone', 'rAddress', 'rAppearance', 'rReason',
    'rInboundTracking', 'rOutboundTracking', 'rNotes', 'rAccessoriesRepair', 'lStart', 'lDue', 'rReportDate'
  ].some(id => $(id) && $(id).value) || (currentAgreement && currentAgreement.data) || Object.keys(currentPhotos || {}).length;
  if (hasData && !confirm('确认清空当前工单的全部已填写信息吗？\n\n客户信息、物流、协议、图片等都会清空。')) return;
  const type = $('rType').value;
  resetRecordForm();
  $('rType').value = type;
  toggleTypeFields();
  setRecordPageType(type, false);
}

function resetRecordForm() {
  ['rSN', 'rModel', 'rCustomer', 'rContact', 'rPhone', 'rAddress', 'rAppearance', 'rReason', 'rInboundTracking', 'rOutboundTracking', 'rNotes', 'rAccessoriesRepair'].forEach(id => { if ($(id)) $(id).value = '' });
  ['rReportDate', 'lStart', 'lDue'].forEach(id => { if ($(id)) $(id).value = '' });
  $('rInboundCarrier').value = '';
  $('rAccessories').value = '';
  $('rOutboundCarrier').value = '顺丰';
  currentPhotos = {}; selectedPhotoKey = null; draggingPhotoKey = null; currentAgreement = null; editingRecordId = null; clearSemanticInput(); renderPhotoGrid(); renderAgreementStatus(); toggleTypeFields();
}
function collectRecord() {
  return {
    id: editingRecordId || uid('R'), orderNo: editingRecordId ? ((load(DB_KEY, []).find(x => x.id === editingRecordId) || {}).orderNo || '') : nextOrderNo($('rType').value), type: $('rType').value, sn: $('rSN').value.trim(), model: $('rModel').value.trim(),
    customer: $('rCustomer').value.trim(), contact: $('rContact').value.trim(), phone: $('rPhone').value.trim(), address: $('rAddress').value.trim(),
    reportDate: $('rReportDate').value, appearance: $('rAppearance').value.trim(), reason: $('rReason').value.trim(),
    loanStart: $('lStart').value, loanDue: $('lDue').value, loanPurpose: '',
    inboundCarrier: $('rInboundCarrier').value.trim(), inboundTracking: $('rInboundTracking').value.trim(),
    outboundCarrier: ($('rType').value === 'repair' ? '顺丰' : $('rOutboundCarrier').value.trim()), outboundTracking: $('rOutboundTracking').value.trim(),
    status: $('rStatus').value, owner: '', accessories: ($('rType').value === 'repair' ? $('rAccessoriesRepair').value.trim() : $('rAccessories').value.trim()), notes: $('rNotes').value.trim(),
    photos: currentPhotos, agreement: currentAgreement, followUps: (editingRecordId ? (load(DB_KEY, []).find(x => x.id === editingRecordId)?.followUps || []) : []), updatedAt: nowStr(), createdAt: (editingRecordId ? (load(DB_KEY, []).find(x => x.id === editingRecordId) || {}).createdAt : nowStr()) || nowStr()
  }
}
async function saveRecord() {
  const r = collectRecord();
  if (!r.customer) { alert('请至少填写客户 / 报修单位。'); return }
  if (r.type === 'loan') {
    if (!r.sn) { alert('借测单请填写设备 SN。'); return }
    if (!(r.agreement && r.agreement.data)) { alert('请先添加借测协议文档，未添加协议无法创建借测单。'); return }
  }
  try { await flowOnline.persistRecordFiles(r) } catch (err) { alert('附件上传失败：' + err.message); return }
  const isNew = !editingRecordId;
  let arr = load(DB_KEY, []), idx = arr.findIndex(x => x.id === r.id); if (idx >= 0) arr[idx] = r; else arr.unshift(r);
  try { await save(DB_KEY, arr) } catch (err) { alert('工单保存失败：' + err.message); return }
  await ensureDeviceFromRecord(r);
  resetRecordForm();
  showTab(r.type === 'repair' ? 'repairs' : 'loans');
}
function ensureDeviceFromRecord(r) {
  if (!r.sn) return Promise.resolve();
  let devs = load(DEV_KEY, []), d = devs.find(x => x.sn === r.sn);
  const mapped = r.type === 'repair' ? (r.status === '已完成' ? '在库' : '维修中') : (r.status === '已归还' ? '在库' : '借测中');
  if (!d) { devs.unshift({ id: uid('D'), sn: r.sn, model: r.model, ownership: r.type === 'repair' ? '客户设备' : '公司资产', status: mapped, customer: r.customer, assetNo: '', note: '', createdAt: nowStr() }) }
  else { d.model = r.model || d.model; d.customer = r.customer || d.customer; d.status = mapped }
  const pending = save(DEV_KEY, devs); refreshSNList();
  return pending;
}
function addPhotosToRecord(id) {
  editRecord(id);
  setTimeout(() => {
    const grid = $('photoGrid');
    if (grid) grid.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 350);
}
function editRecord(id) {
  const r = load(DB_KEY, []).find(x => x.id === id); if (!r) return;
  closeAllDrawers();
  resetRecordForm();
  editingRecordId = id;
  openRecordDrawer();
  $('rType').value = r.type; toggleTypeFields(); setRecordPageType(r.type, true); $('recordTitle').textContent += ' · ' + displayOrderNo(r);
  const map = { rSN: 'sn', rModel: 'model', rCustomer: 'customer', rContact: 'contact', rPhone: 'phone', rAddress: 'address', rReportDate: 'reportDate', rAppearance: 'appearance', rReason: 'reason', lStart: 'loanStart', lDue: 'loanDue', rInboundCarrier: 'inboundCarrier', rInboundTracking: 'inboundTracking', rOutboundCarrier: 'outboundCarrier', rOutboundTracking: 'outboundTracking', rStatus: 'status', rNotes: 'notes' };
  Object.entries(map).forEach(([id, k]) => {
    $(id).value = r[k] || '';
  });
  if (r.type === 'repair') $('rOutboundCarrier').value = '顺丰';
  currentPhotos = r.photos || {}; currentAgreement = r.agreement || null; renderPhotoGrid(); renderAgreementStatus();
}
function getRecycle() { return Object.assign({ records: [], devices: [] }, load(RECYCLE_KEY, { records: [], devices: [] })) }
function saveRecycle(v) { save(RECYCLE_KEY, v); updateRecycleCount() }
function updateRecycleCount() { const rb = getRecycle(); const el = $('recycleCount'); if (el) el.textContent = rb.records.length + rb.devices.length }
function delRecord(id) {
  if (!confirm('确认删除此工单？删除后可在回收站恢复。')) return;
  let arr = load(DB_KEY, []), r = arr.find(x => x.id === id); if (!r) return;
  const rb = getRecycle(); rb.records.unshift({ ...r, deletedAt: nowStr() }); saveRecycle(rb);
  save(DB_KEY, arr.filter(x => x.id !== id));
  renderRecords('repair'); renderRecords('loan'); renderDashboard(); renderDevices();
}
function exportOrderNo(r) { const n = displayOrderNo(r); return n || '' }
function excelDate(v) { const s = toISODate(String(v || '')); return s || String(v || '') }
function loanOverdueDays(r) { if (r.status === '已归还') return 0; const n = daysUntil(r.loanDue); return n !== null && n < 0 ? Math.abs(n) : 0 }
function filteredRecordsForExport(type) {
  const search = $(type === 'repair' ? 'repairSearch' : 'loanSearch')?.value.toLowerCase() || '';
  const filter = $(type === 'repair' ? 'repairFilter' : 'loanFilter')?.value || '';
  let arr = load(DB_KEY, []).filter(r => r.type === type).filter(r => {
    if (!filter) return true;
    if (type === 'loan' && filter === '已逾期') { const n = daysUntil(r.loanDue); return r.status !== '已归还' && n !== null && n < 0 }
    return r.status === filter;
  }).filter(r => [r.customer, r.sn, (r.snList || []).join(' '), r.snRaw, r.inboundTracking, r.outboundTracking, r.model, r.orderNo, r.borrower, r.followOwner, r.recipientInfoRaw, getFollowUps(r).map(x => `${x.person || ''} ${x.date || ''} ${x.text || ''}`).join(' ')].join(' ').toLowerCase().includes(search));
  if (type === 'loan') {
    const mode = $('loanSort')?.value || 'default';
    if (mode === 'overdue_desc') arr.sort((a, b) => (daysUntil(a.loanDue) ?? 9999) - (daysUntil(b.loanDue) ?? 9999));
    else if (mode === 'overdue_asc') arr.sort((a, b) => (daysUntil(b.loanDue) ?? -9999) - (daysUntil(a.loanDue) ?? -9999));
    else if (mode === 'due_soon') arr.sort((a, b) => (daysUntil(a.loanDue) ?? 9999) - (daysUntil(b.loanDue) ?? 9999));
  }
  return arr;
}
function styleExportSheet(ws, widths) {
  ws['!autofilter'] = { ref: ws['!ref'] }; ws['!freeze'] = { xSplit: 0, ySplit: 1, topLeftCell: 'A2', activePane: 'bottomLeft', state: 'frozen' };
  ws['!cols'] = widths.map(w => ({ wch: w }));
  if (ws['!ref']) { const rg = XLSX.utils.decode_range(ws['!ref']); for (let R = 1; R <= rg.e.r; R++) for (let C = 0; C <= rg.e.c; C++) { const c = ws[XLSX.utils.encode_cell({ r: R, c: C })]; if (c) c.z = '@' } }
}
function exportRecordsExcel(type) {
  if (typeof XLSX === 'undefined') {
    ensureCdn('xlsx').then(() => exportRecordsExcel(type)).catch(() => alert('Excel 导出组件加载失败，请检查网络后重试。'));
    return;
  }
  const arr = filteredRecordsForExport(type); if (!arr.length) { alert('当前筛选条件下没有可导出的数据。'); return }
  const wb = XLSX.utils.book_new();
  if (type === 'loan') {
    const rows = arr.map(r => { const f = latestFollowUp(r) || {}; return { '工单号': exportOrderNo(r), '借出日期': excelDate(r.loanStart), '预计归还日期': excelDate(r.loanDue), '实际归还日期': excelDate(r.returnedDate), '状态': r.status || '', '逾期天数': loanOverdueDays(r), '客户/公司': r.customer || '', '联系人': r.contact || '', '联系电话': r.phone || '', '回寄地址': r.address || '', '设备型号': r.model || '', 'SN': recordSNDisplay(r) === '-' ? '' : recordSNDisplay(r), '随机配件': r.accessories || '', '寄出物流公司': r.outboundCarrier || '', '寄出快递单号': r.outboundTracking || '', '客户归还物流公司': r.inboundCarrier || '', '客户归还快递单号': r.inboundTracking || '', '借机人': r.borrower || '', '最后跟进人': f.person || r.followOwner || '', '最后跟进日期': excelDate(f.date), '最后跟进情况': f.text || '', '备注': r.notes || '' } });
    let ws = XLSX.utils.json_to_sheet(rows); styleExportSheet(ws, [16, 12, 14, 14, 10, 10, 28, 12, 16, 34, 14, 20, 24, 14, 20, 16, 20, 12, 12, 14, 40, 36]); XLSX.utils.book_append_sheet(wb, ws, '借测记录');
    const fus = []; arr.forEach(r => getFollowUps(r).forEach(f => fus.push({ '客户/公司': r.customer || '', '设备型号': r.model || '', 'SN': r.sn || '', '跟进日期': excelDate(f.date), '跟进人': f.person || '', '跟进内容': f.text || '' }))); ws = XLSX.utils.json_to_sheet(fus.length ? fus : [{ '客户/公司': '', '设备型号': '', 'SN': '', '跟进日期': '', '跟进人': '', '跟进内容': '' }]); styleExportSheet(ws, [28, 14, 20, 14, 12, 50]); XLSX.utils.book_append_sheet(wb, ws, '跟进记录');
    const active = arr.filter(r => r.status !== '已归还').length, returned = arr.filter(r => r.status === '已归还').length, overdue = arr.filter(r => loanOverdueDays(r) > 0).length, due7 = arr.filter(r => { const n = daysUntil(r.loanDue); return r.status !== '已归还' && n !== null && n >= 0 && n <= 7 }).length; const ds = arr.map(recordLoanDays).filter(x => x !== null); const mc = {}; arr.forEach(r => { if (r.model) mc[r.model] = (mc[r.model] || 0) + 1 }); const top = Object.entries(mc).sort((a, b) => b[1] - a[1])[0]; const sum = [['统计项目', '数值'], ['导出记录数', arr.length], ['借测中数量', active], ['已逾期数量', overdue], ['7天内到期数量', due7], ['已归还数量', returned], ['平均借测天数', ds.length ? Math.round(ds.reduce((a, b) => a + b, 0) / ds.length) : ''], ['借测最多型号', top ? top[0] : ''], [], ['型号统计', '借测次数'], ...Object.entries(mc).sort((a, b) => b[1] - a[1]), [], ['客户统计', '借测次数'], ...Object.entries(arr.reduce((o, r) => { if (r.customer) o[r.customer] = (o[r.customer] || 0) + 1; return o }, {})).sort((a, b) => b[1] - a[1])]; ws = XLSX.utils.aoa_to_sheet(sum); ws['!cols'] = [{ wch: 32 }, { wch: 16 }]; XLSX.utils.book_append_sheet(wb, ws, '统计汇总');
  } else {
    const rows = arr.map(r => ({ '工单号': exportOrderNo(r), '报修日期': excelDate(r.reportDate), '当前状态': r.status || '', '客户/公司': r.customer || '', '报修人': r.contact || '', '联系电话': r.phone || '', '维修后回寄地址': r.address || '', '设备型号': r.model || '', 'SN': recordSNDisplay(r) === '-' ? '' : recordSNDisplay(r), '报修原因/故障现象': r.reason || '', '外观情况': r.appearance || '', '客户寄回物流公司': r.inboundCarrier || '', '客户寄回快递单号': r.inboundTracking || '', '随机配件': r.accessories || '', '维修后返还快递单号': r.outboundTracking || '', '最后更新时间': r.updatedAt || '', '备注': r.notes || '' })); let ws = XLSX.utils.json_to_sheet(rows); styleExportSheet(ws, [16, 12, 12, 28, 12, 16, 34, 14, 20, 40, 20, 16, 20, 28, 20, 20, 40]); XLSX.utils.book_append_sheet(wb, ws, '维修记录');
  }
  const d = new Date(), date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; XLSX.writeFile(wb, `${type === 'loan' ? '借测记录' : '维修记录'}_${date}.xlsx`);
}

function renderRecords(type) {
  const search = $(type === 'repair' ? 'repairSearch' : 'loanSearch').value.toLowerCase(), filter = $(type === 'repair' ? 'repairFilter' : 'loanFilter').value;
  let arr = load(DB_KEY, []).filter(r => r.type === type).filter(r => {
    if (!filter) return true;
    if (type === 'loan' && filter === '已逾期') {
      const n = daysUntil(r.loanDue);
      return r.status !== '已归还' && n !== null && n < 0;
    }
    return r.status === filter;
  }).filter(r => [
    r.customer, r.sn, (r.snList || []).join(' '), r.snRaw, r.inboundTracking, r.outboundTracking, r.model, r.orderNo,
    r.borrower, r.followOwner, r.recipientInfoRaw, getFollowUps(r).map(x => `${x.person || ''} ${x.date || ''} ${x.text || ''}`).join(' ')
  ].join(' ').toLowerCase().includes(search));
  if (type === 'loan') {
    const sortMode = $('loanSort')?.value || 'default';
    if (sortMode === 'overdue_desc') {
      arr.sort((a, b) => (daysUntil(a.loanDue) ?? 9999) - (daysUntil(b.loanDue) ?? 9999));
    } else if (sortMode === 'overdue_asc') {
      arr.sort((a, b) => (daysUntil(b.loanDue) ?? -9999) - (daysUntil(a.loanDue) ?? -9999));
    } else if (sortMode === 'due_soon') {
      arr.sort((a, b) => (daysUntil(a.loanDue) ?? 9999) - (daysUntil(b.loanDue) ?? 9999));
    } else {
      arr.sort((a, b) => {
        if (a.status !== b.status) return a.status === '借测中' ? -1 : 1;
        return String(b.loanStart || b.updatedAt || '').localeCompare(String(a.loanStart || a.updatedAt || ''));
      });
    }
  }
  const target = $(type === 'repair' ? 'repairTable' : 'loanTable');
  if (!arr.length) { target.innerHTML = '<div class="empty">暂无记录</div>'; return }
  const headers = type === 'loan'
    ? '<th>工单</th><th>设备</th><th>客户</th><th>物流</th><th>状态</th><th>最后跟进</th><th>操作</th>'
    : '<th>工单</th><th>设备</th><th>客户</th><th>物流</th><th>状态</th><th>更新时间</th><th>操作</th>';
  target.innerHTML = `<table><thead><tr>${headers}</tr></thead><tbody>${arr.map(r => { const isOverdue = type === 'loan' && r.status !== '已归还' && daysUntil(r.loanDue) !== null && daysUntil(r.loanDue) < 0; return `<tr class="${isOverdue ? 'overdue-row' : ''}">
    <td class="clickable" onclick="openRecord('${r.id}')"><b>${type === 'repair' ? '维修' : '借测'}</b>${displayOrderNo(r) ? `<br><span class="label">${esc(displayOrderNo(r))}</span>` : ''}</td>
    <td class="clickable" onclick="openDeviceBySN('${esc(r.sn)}')"><span class="linklike">${esc(r.model || '-')}</span><br>SN: ${esc(recordSNDisplay(r))}</td>
    <td>${esc(r.customer || '-')}<br><span class="label">${esc(r.contact || '')}</span></td>
    <td>${logisticsText(r, true)}</td>
    <td>${type === 'loan' ? (() => { const ds = loanDueState(r); return `<span class="tag ${ds.cls}">${esc(ds.label)}</span>` })() : `<span class="tag ${r.status.includes('完成') ? 'green' : r.status.includes('待') ? 'orange' : ''}">${esc(r.status)}</span>`}</td>
    <td>${type === 'loan' ? followUpSummaryHtml(r) : esc(r.updatedAt || '-')}</td>
    <td><button class="btn" onclick="openRecord('${r.id}')">查看</button> <button class="btn" onclick="editRecord('${r.id}')">编辑</button> ${type === 'repair' ? `<button class="btn" onclick="repairPdfById('${r.id}')">生成PDF</button>` : ''} <button class="btn danger" onclick="delRecord('${r.id}')">删除</button></td>
  </tr>` }).join('')}</tbody></table>`;
}
function parseDateLocal(s) { if (!s) return null; const d = new Date(s + 'T00:00:00'); return isNaN(d) ? null : d }
function daysUntil(s) { const d = parseDateLocal(s); if (!d) return null; const today = new Date(); today.setHours(0, 0, 0, 0); return Math.ceil((d - today) / 86400000) }
function dueSoonLoans(includeOverdue = false) {
  return load(DB_KEY, []).filter(r => { if (r.type !== 'loan' || r.status === '已归还' || !r.loanDue) return false; const n = daysUntil(r.loanDue); return n !== null && (includeOverdue ? n <= 7 : n >= 0 && n <= 7) }).sort((a, b) => (daysUntil(a.loanDue) ?? 999) - (daysUntil(b.loanDue) ?? 999));
}
function isThisMonth(s) { const d = parseDateLocal(s); if (!d) return false; const n = new Date(); return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() }
function lastFollowDate(r) { const fs = getFollowUps(r); const d = fs.map(x => parseDateLocal(x.date)).filter(Boolean).sort((a, b) => b - a)[0]; return d || parseDateLocal(r.updatedAt) || parseDateLocal(r.loanStart) }
function staleLoan(r) { if (r.type !== 'loan' || r.status === '已归还') return false; const d = lastFollowDate(r); if (!d) return true; return Math.floor((Date.now() - d.getTime()) / 86400000) >= 14 }
function setDashboardAction(mode, btn) { dashboardAction = mode; document.querySelectorAll('.action-tab').forEach(x => x.classList.toggle('active', x.dataset.action === mode)); renderDashboardAttention() }
function renderDashboardAttention() {
  const records = load(DB_KEY, []), overdue = records.filter(r => r.type === 'loan' && r.status !== '已归还' && daysUntil(r.loanDue) !== null && daysUntil(r.loanDue) < 0).sort((a, b) => daysUntil(a.loanDue) - daysUntil(b.loanDue));
  const due = records.filter(r => r.type === 'loan' && r.status !== '已归还' && daysUntil(r.loanDue) !== null && daysUntil(r.loanDue) >= 0 && daysUntil(r.loanDue) <= 7).sort((a, b) => daysUntil(a.loanDue) - daysUntil(b.loanDue));
  const stale = records.filter(staleLoan).sort((a, b) => (lastFollowDate(a)?.getTime() || 0) - (lastFollowDate(b)?.getTime() || 0));
  if ($('aOverdue')) $('aOverdue').textContent = overdue.length; if ($('aDue')) $('aDue').textContent = due.length; if ($('aStale')) $('aStale').textContent = stale.length;
  const arr = dashboardAction === 'due' ? due : dashboardAction === 'stale' ? stale : overdue;
  $('attentionList').innerHTML = arr.length ? arr.slice(0, 8).map(r => { const n = daysUntil(r.loanDue); let label = dashboardAction === 'stale' ? '14天+未跟进' : n < 0 ? `已逾期 ${Math.abs(n)} 天` : n === 0 ? '今天到期' : `${n} 天后到期`; return `<div class="compact-item ${n < 0 ? 'overdue' : ''}" onclick="showTab('loans');openRecord('${r.id}')"><div><div class="compact-title">${esc(r.customer || '-')} · ${esc(r.model || '-')}</div><div class="compact-meta">SN: ${esc(r.sn || '-')}${displayOrderNo(r) ? ' · ' + esc(displayOrderNo(r)) : ''}${getFollowUps(r).length ? ' · ' + esc(getFollowUps(r).slice(-1)[0].person || '有跟进记录') : ''}</div></div><span class="tag ${n < 0 ? 'red' : 'orange'}">${label}</span></div>` }).join('') : '<div class="empty" style="padding:24px">当前没有此类待办</div>';
}
function dashboardJump(kind) {
  if (kind === 'monthRepair') { showTab('repairs'); return }
  showTab('loans'); const f = $('loanFilter'), s = $('loanSort');
  if (kind === 'overdue') { f.value = '已逾期'; s.value = 'overdue_desc' }
  else if (kind === 'dueSoon') { f.value = '借测中'; s.value = 'due_soon' }
  else { f.value = kind === 'loaning' ? '借测中' : ''; s.value = 'default' }
  renderRecords('loan');
}
function renderDashboard() {
  const records = load(DB_KEY, []), devs = load(DEV_KEY, []).map(d => Object.assign({}, d, { _displayStatus: normalizedDeviceStatus(d) }));
  const monthLoans = records.filter(r => r.type === 'loan' && isThisMonth(r.loanStart));
  const monthRepairs = records.filter(r => r.type === 'repair' && isThisMonth(r.reportDate));
  const monthReturned = records.filter(r => r.type === 'loan' && r.status === '已归还' && isThisMonth(r.updatedAt ? toISODate(r.updatedAt) : r.loanDue));
  $('mLoan').textContent = devs.filter(d => d._displayStatus === '借测中').length;
  $('mMonthLoan').textContent = monthLoans.length;
  $('mMonthRepair').textContent = monthRepairs.length;
  $('mDueSoon').textContent = dueSoonLoans(false).length;
  $('mMonthReturned').textContent = monthReturned.length;

  const days = monthLoans.map(recordLoanDays).filter(x => x !== null);
  $('mAvgLoanDays').textContent = days.length ? (Math.round(days.reduce((a, b) => a + b, 0) / days.length) + ' 天') : '-';

  const overdue = records.filter(r => r.type === 'loan' && r.status !== '已归还' && daysUntil(r.loanDue) !== null && daysUntil(r.loanDue) < 0).length;
  $('mOverdue').textContent = overdue;

  const modelCounts = {};
  monthLoans.forEach(r => { const m = r.model || '未填写'; modelCounts[m] = (modelCounts[m] || 0) + 1 });
  const ranked = Object.entries(modelCounts).sort((a, b) => b[1] - a[1]);
  $('mTopModel').textContent = ranked.length ? ranked[0][0] : '-';
  const max = ranked.length ? ranked[0][1] : 1;
  $('modelRank').innerHTML = ranked.length ? ranked.slice(0, 6).map(([m, c]) => `<div class="rank-row"><div>${esc(m)}</div><div class="rank-bar"><div class="rank-fill" style="width:${Math.round(c / max * 100)}%"></div></div><div>${c} 台</div></div>`).join('') : '<div class="hint">本月暂无借测数据</div>';

  renderDashboardAttention();

  const recent = records.slice().sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || ''))).slice(0, 6);
  $('recentFlow').innerHTML = recent.length ? `<table class="recent-flow-table"><tbody>${recent.map(r => `<tr class="clickable" onclick="openRecord('${r.id}')">
    <td><b>${r.type === 'loan' ? '借测' : '维修'}</b>${displayOrderNo(r) ? `<br><span class="label">${esc(displayOrderNo(r))}</span>` : ''}</td>
    <td>${esc(r.customer || '-')}</td><td>${esc(r.model || '-')} / ${esc(r.sn || '-')}</td>
    <td>${r.type === 'loan' ? `<span class="tag ${loanDueState(r).cls}">${esc(loanDueState(r).label)}</span>` : `<span class="tag">${esc(r.status || '-')}</span>`}</td>
    <td class="label">${esc(r.updatedAt || '-')}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">暂无流转记录</div>';

  updateRecycleCount();
}

function toISODate(s = '') {
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
  const m = String(s).match(/(\d{4})\/(\d{1,2})\/(\d{1,2})/);
  return m ? `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}` : '';
}
function deleteDevice(id) {
  const devs = load(DEV_KEY, []);
  const d = devs.find(x => x.id === id); if (!d) return;
  if (!confirm(`确认删除设备 ${d.model || ''} / ${d.sn} 吗？\n\n设备会进入回收站，关联工单不会删除。`)) return;
  const rb = getRecycle(); rb.devices.unshift({ ...d, deletedAt: nowStr() }); saveRecycle(rb);
  save(DEV_KEY, devs.filter(x => x.id !== id));
  closeAllDrawers(); renderDashboard(); renderDevices(); refreshSNList();
}

function setRecycleTab(tab) {
  recycleTab = tab; $('rbTabRecords').classList.toggle('active', tab === 'records'); $('rbTabDevices').classList.toggle('active', tab === 'devices'); renderRecycleBin();
}
function renderRecycleBin() {
  const rb = getRecycle(), target = $('recycleTable'); if (!target) return; const arr = recycleTab === 'records' ? rb.records : rb.devices;
  if (!arr.length) { target.innerHTML = '<div class="empty">回收站为空</div>'; return }
  if (recycleTab === 'records') {
    target.innerHTML = `<table><thead><tr><th>类型/工单</th><th>设备</th><th>客户</th><th>删除时间</th><th>操作</th></tr></thead><tbody>${arr.map((r, i) => `<tr><td>${r.type === 'repair' ? '维修' : '借测'}${displayOrderNo(r) ? `<br><span class="label">${esc(displayOrderNo(r))}</span>` : ''}</td><td>${esc(r.model || '-')}<br>SN: ${esc(r.sn || '-')}</td><td>${esc(r.customer || '-')}</td><td>${esc(r.deletedAt || '-')}</td><td><div class="recycle-row-actions"><button class="btn primary" onclick="restoreRecord(${i})">恢复</button><button class="btn danger" onclick="purgeRecord(${i})">永久删除</button></div></td></tr>`).join('')}</tbody></table>`;
  } else {
    target.innerHTML = `<table><thead><tr><th>设备</th><th>归属</th><th>客户</th><th>删除时间</th><th>操作</th></tr></thead><tbody>${arr.map((d, i) => `<tr><td>${esc(d.model || '-')}<br>SN: ${esc(d.sn || '-')}</td><td>${esc(d.ownership || '-')}</td><td>${esc(d.customer || '-')}</td><td>${esc(d.deletedAt || '-')}</td><td><div class="recycle-row-actions"><button class="btn primary" onclick="restoreDevice(${i})">恢复</button><button class="btn danger" onclick="purgeDevice(${i})">永久删除</button></div></td></tr>`).join('')}</tbody></table>`;
  }
}
function restoreRecord(i) { const rb = getRecycle(), r = rb.records[i]; if (!r) return; const arr = load(DB_KEY, []); const copy = { ...r }; delete copy.deletedAt; if (arr.some(x => x.id === copy.id)) copy.id = uid('R'); arr.unshift(copy); save(DB_KEY, arr); rb.records.splice(i, 1); saveRecycle(rb); ensureDeviceFromRecord(copy); renderRecycleBin(); renderRecords(copy.type); renderDashboard(); renderDevices() }
function restoreDevice(i) { const rb = getRecycle(), d = rb.devices[i]; if (!d) return; const arr = load(DEV_KEY, []); if (arr.some(x => x.sn === d.sn)) { alert('当前设备列表已有相同 SN，无法恢复。'); return } const copy = { ...d }; delete copy.deletedAt; arr.unshift(copy); save(DEV_KEY, arr); rb.devices.splice(i, 1); saveRecycle(rb); renderRecycleBin(); renderDashboard(); renderDevices(); refreshSNList() }
function purgeRecord(i) { if (!confirm('永久删除后无法恢复，确认继续？')) return; const rb = getRecycle(); rb.records.splice(i, 1); saveRecycle(rb); renderRecycleBin() }
function purgeDevice(i) { if (!confirm('永久删除后无法恢复，确认继续？')) return; const rb = getRecycle(); rb.devices.splice(i, 1); saveRecycle(rb); renderRecycleBin() }
function emptyRecycleBin() { if (!confirm('确认清空回收站？清空后无法恢复。')) return; saveRecycle({ records: [], devices: [] }); renderRecycleBin() }


function addDaysISO(n) {
  const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function isDemoRecord(r) { return String(r.sn || '').startsWith('DEMO-') || String(r.orderNo || '').includes('DEMO') }
function isDemoDevice(d) { return String(d.sn || '').startsWith('DEMO-') }
function clearDemoData() {
  const rs = load(DB_KEY, []), ds = load(DEV_KEY, []), rb = getRecycle();
  const rc = rs.filter(isDemoRecord).length, dc = ds.filter(isDemoDevice).length;
  const rr = rb.records.filter(isDemoRecord).length, rd = rb.devices.filter(isDemoDevice).length;
  if (!(rc + dc + rr + rd)) { alert('当前没有演示数据。'); return }
  if (!confirm(`确认清除全部演示数据？\n\n设备 ${dc + rd} 条，工单 ${rc + rr} 条。\n只删除 DEMO 开头的演示数据，不影响正式记录。`)) return;
  save(DB_KEY, rs.filter(r => !isDemoRecord(r)));
  save(DEV_KEY, ds.filter(d => !isDemoDevice(d)));
  saveRecycle({ records: rb.records.filter(r => !isDemoRecord(r)), devices: rb.devices.filter(d => !isDemoDevice(d)) });
  closeAllDrawers(); renderDashboard(); renderDevices(); renderRecords('repair'); renderRecords('loan'); refreshSNList(); updateRecycleCount();
  alert('演示数据已清除。');
}

function addDemoData() {
  if (!confirm('添加 4 组演示数据用于查看面板和提醒效果？不会覆盖现有数据。')) return;
  let devs = load(DEV_KEY, []), rs = load(DB_KEY, []);
  const demos = [
    { sn: 'DEMO-LOAN-001', model: 'M2600', customer: '华东自动化', ownership: '公司资产', status: '借测中' },
    { sn: 'DEMO-LOAN-002', model: 'M51000', customer: '工布智造', ownership: '公司资产', status: '借测中' },
    { sn: 'DEMO-REPAIR-001', model: 'M2600 V2', customer: '群青科技', ownership: '客户设备', status: '维修中' },
    { sn: 'DEMO-HIGH-001', model: 'M2600', customer: '视比特', ownership: '公司资产', status: '借测中' }
  ];
  demos.forEach(d => { if (!devs.some(x => x.sn === d.sn)) devs.unshift({ id: uid('D'), assetNo: '', note: '演示数据', createdAt: nowStr(), ...d }) });

  const baseRecords = [
    { id: uid('R'), orderNo: 'JC-DEMO-001', type: 'loan', sn: 'DEMO-LOAN-001', model: 'M2600', customer: '华东自动化', contact: '张工', phone: '13800000001', address: '上海市浦东新区演示路1号', loanStart: addDaysISO(-8), loanDue: addDaysISO(5), status: '借测中', outboundCarrier: '顺丰', outboundTracking: 'SFDEMO001', inboundCarrier: '', inboundTracking: '', accessories: '15m标配', notes: '演示：5天后到期', photos: {}, agreement: { name: '演示借测协议.pdf', type: 'application/pdf', size: 0, data: '' }, updatedAt: nowStr(), createdAt: nowStr() },
    { id: uid('R'), orderNo: 'JC-DEMO-002', type: 'loan', sn: 'DEMO-LOAN-002', model: 'M51000', customer: '工布智造', contact: '李工', phone: '13800000002', address: '湖北省武汉市演示大道2号', loanStart: addDaysISO(-20), loanDue: addDaysISO(-3), status: '借测中', outboundCarrier: '顺丰', outboundTracking: 'SFDEMO002', inboundCarrier: '', inboundTracking: '', accessories: '5m标配', notes: '演示：已逾期3天', photos: {}, agreement: { name: '演示借测协议.pdf', type: 'application/pdf', size: 0, data: '' }, updatedAt: nowStr(), createdAt: nowStr() },
    { id: uid('R'), orderNo: 'WX-DEMO-001', type: 'repair', sn: 'DEMO-REPAIR-001', model: 'M2600 V2', customer: '群青科技', contact: '王工', phone: '13800000003', address: '广东省深圳市演示园区3号', reportDate: addDaysISO(-4), appearance: '轻微划痕', reason: '3D拍摄异常', status: '维修中', inboundCarrier: '德邦', inboundTracking: 'DBDEMO001', outboundCarrier: '顺丰', outboundTracking: '', accessories: '相机×1、15m线缆×1', notes: '演示维修记录', photos: {}, updatedAt: nowStr(), createdAt: nowStr() }
  ];
  baseRecords.forEach(r => { if (!rs.some(x => x.orderNo === r.orderNo)) rs.unshift(r) });

  // High-turnover history: 7 loans + 1 repair to trigger "关注"
  for (let i = 1; i <= 7; i++) {
    const ono = `JC-DEMO-H-${i}`;
    if (!rs.some(x => x.orderNo === ono)) {
      rs.push({ id: uid('R'), orderNo: ono, type: 'loan', sn: 'DEMO-HIGH-001', model: 'M2600', customer: i % 2 ? '视比特' : '杭州智戎', contact: '演示联系人', phone: '13800000004', address: '演示地址', loanStart: addDaysISO(-60 + i * 5), loanDue: addDaysISO(-56 + i * 5), status: '已归还', outboundCarrier: '顺丰', outboundTracking: `SFH${i}`, inboundCarrier: '顺丰', inboundTracking: `SFR${i}`, accessories: '裸机', notes: '周转演示', photos: {}, agreement: { name: '演示协议.pdf', type: 'application/pdf', size: 0, data: '' }, updatedAt: nowStr(), createdAt: nowStr() });
    }
  }
  save(DEV_KEY, devs); save(DB_KEY, rs); renderDashboard(); renderDevices(); renderRecords('repair'); renderRecords('loan'); refreshSNList(); alert('演示数据已添加。可查看：即将到期、逾期、客户流转、设备健康、月度统计。');
}

function setDeviceFilter(btn, status) {
  currentDeviceFilter = status || '';
  document.querySelectorAll('.device-tab').forEach(x => x.classList.toggle('active', x === btn));
  renderDevices();
}
function normalizedDeviceStatus(d) {
  const records = load(DB_KEY, []).filter(r => r.sn === d.sn)
    .sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')));
  if (records[0]) return records[0].type === 'repair' ? '维修中' : '借测中';
  return d.status === '维修中' ? '维修中' : '借测中';
}
function renderDevices() {
  let q = ($('deviceSearch').value || '').toLowerCase();
  let devs = load(DEV_KEY, []).map(d => Object.assign({}, d, { _displayStatus: normalizedDeviceStatus(d) }))
    .filter(d => !currentDeviceFilter || d._displayStatus === currentDeviceFilter)
    .filter(d => [d.sn, d.model, d.customer, d.assetNo].join(' ').toLowerCase().includes(q));
  $('deviceTable').innerHTML = devs.length ? `<table><thead><tr><th>设备</th><th>当前客户 / 使用方</th><th>周转</th><th>最后跟进</th><th>健康</th><th>操作</th></tr></thead><tbody>${devs.map(d => {
    const s = deviceStats(d.sn), h = deviceHealth(d.sn);
    const active = load(DB_KEY, []).filter(r => r.type === 'loan' && r.status === '借测中' && recordHasSN(r, d.sn)).sort((a, b) => String(b.loanStart || '').localeCompare(String(a.loanStart || '')))[0];
    return `<tr class="clickable" onclick="openDevice('${d.id}')"><td><span class="linklike">${esc(d.model)}</span><br>SN: ${esc(d.sn)}</td><td>${esc(d.customer || '-')}</td><td>借测 ${s.loanCount} 次 / 维修 ${s.repairCount} 次</td><td>${active ? followUpSummaryHtml(active) : '<span class="label">-</span>'}</td><td><span class="tag ${h.cls}">${h.label}</span></td><td><button class="btn" onclick="event.stopPropagation();openDevice('${d.id}')">查看档案</button> <button class="btn danger" onclick="event.stopPropagation();deleteDevice('${d.id}')">删除</button></td></tr>`;
  }).join('')}</tbody></table>` : '<div class="empty">暂无设备</div>';
}
function recordLoanDays(r) {
  if (r.type !== 'loan' || !r.loanStart) return null;
  const s = parseDateLocal(r.loanStart), e = parseDateLocal(r.loanDue) || new Date();
  if (!s || !e) return null;
  const n = Math.max(0, Math.round((e - s) / 86400000)); return n;
}
function loanDueState(r) {
  if (r.type !== 'loan') return { label: '', cls: '' };
  if (r.status === '已归还') return { label: '已归还', cls: 'green' };
  const n = daysUntil(r.loanDue);
  if (n === null) return { label: '借测中', cls: '' };
  if (n < 0) return { label: `已逾期 ${Math.abs(n)} 天`, cls: 'red' };
  if (n <= 7) return { label: `${n === 0 ? '今天到期' : n + '天后到期'}`, cls: 'orange' };
  return { label: '正常', cls: 'green' };
}
function deviceStats(sn) {
  const rs = load(DB_KEY, []).filter(r => recordHasSN(r, sn));
  const loanCount = rs.filter(r => r.type === 'loan').length;
  const repairCount = rs.filter(r => r.type === 'repair').length;
  const customers = [...new Set(rs.map(r => r.customer).filter(Boolean))].length;
  return { loanCount, repairCount, customers };
}
function deviceHealth(sn) {
  const s = deviceStats(sn);
  if (s.repairCount >= 2 || s.loanCount >= 10) return { label: '建议检查', cls: 'health-check' };
  if (s.repairCount === 1 || s.loanCount >= 6) return { label: '关注', cls: 'health-watch' };
  return { label: '正常', cls: 'health-ok' };
}

function openDeviceBySN(sn) {
  const d = load(DEV_KEY, []).find(x => x.sn === sn); if (d) openDevice(d.id);
}
function openDevice(id) {
  closeAllDrawers();
  const d = load(DEV_KEY, []).find(x => x.id === id); if (!d) return;
  const rs = load(DB_KEY, []).filter(r => recordHasSN(r, d.sn)).sort((a, b) => String(a.createdAt || a.updatedAt || '').localeCompare(String(b.createdAt || b.updatedAt || '')));
  const customers = rs.map(r => r.customer).filter(Boolean).filter((x, i, a) => i === 0 || x !== a[i - 1]);
  const s = deviceStats(d.sn), h = deviceHealth(d.sn);
  $('dEyebrow').textContent = '设备档案'; $('dTitle').textContent = `${d.model} · ${d.sn}`;
  const flow = customers.length ? `<div class="divider"></div><div class="subhead">客户流转</div><div class="flow-chain">${customers.map((c, i) => `${i ? '<span class="flow-arrow">→</span>' : ''}<span class="flow-node">${esc(c)}</span>`).join('')}</div>` : '';
  $('drawerBody').innerHTML = `
    <div class="detail-grid">
      <div class="detail-card"><div class="label">当前分类</div><b>${esc(normalizedDeviceStatus(d))}</b></div>
      <div class="detail-card"><div class="label">设备健康</div><b><span class="tag ${h.cls}">${h.label}</span></b></div>
      <div class="detail-card"><div class="label">累计借测</div><b>${s.loanCount} 次</b></div>
      <div class="detail-card"><div class="label">累计维修</div><b>${s.repairCount} 次</b></div>
      <div class="detail-card"><div class="label">服务客户</div><b>${s.customers} 家</b></div>
      <div class="detail-card"><div class="label">当前客户 / 使用方</div><b>${esc(d.customer || '-')}</b></div>
    </div>
    ${flow}
    <div class="divider"></div><div class="subhead">设备完整历史（点击记录查看详情）</div>
    ${rs.length ? rs.slice().reverse().map(r => `<div class="record-card" onclick="openRecord('${r.id}')"><div class="record-head"><div><b>${r.type === 'repair' ? '维修工单' : '借测单'} · ${esc(displayOrderNo(r))}</b><div class="muted" style="margin-top:4px">${esc(r.customer)} · ${esc(r.updatedAt)}</div></div><span class="tag ${r.type === 'loan' ? loanDueState(r).cls : ''}">${esc(r.type === 'loan' ? loanDueState(r).label : r.status)}</span></div><div class="hint" style="margin-top:10px">${logisticsText(r, true)}</div></div>`).join('') : '<div class="empty">暂无流转记录</div>'}`;
  $('drawer').classList.add('open'); $('drawerOverlay').classList.add('open');
}
function openRecord(id) {
  const r = load(DB_KEY, []).find(x => x.id === id); if (!r) return;
  const photos = Object.entries(r.photos || {}).filter(([, v]) => v);
  $('dEyebrow').textContent = (r.type === 'repair' ? '维修' : '借测') + '工单详情';
  $('dTitle').textContent = displayOrderNo(r) || `${r.type === 'repair' ? '维修' : '借测'} · ${r.customer || r.model || r.sn || '详情'}`;

  const actionBar = `
    <div class="drawer-top-actions">
      <button class="btn primary" onclick="startRecordInlineEdit('${r.id}')">编辑信息</button>
      ${r.type === 'repair' ? `<button class="btn" onclick="repairPdfById('${r.id}')">生成维修 PDF</button>` : ''}
      ${photos.length ? `<button class="btn" onclick="downloadRecordPhotos('${r.id}')">一键打包下载图片</button>` : ''}
      ${r.sn ? `<button class="btn" onclick="openDeviceBySN('${esc(r.sn)}')">查看设备档案</button>` : ''}
    </div>`;

  const common = `
    <div class="detail-grid">
      <div class="detail-card"><div class="label">设备</div><b>${esc(r.model || '-')}<br>SN: ${esc(r.sn || '-')}</b></div>
      <div class="detail-card"><div class="label">当前状态</div><b>${esc(r.status || '-')}</b></div>
      <div class="detail-card"><div class="label">客户</div><b>${esc(r.customer || '-')}</b></div>
      <div class="detail-card"><div class="label">联系人 / 电话</div><b>${esc((r.contact || '-') + (r.phone ? ' ' + r.phone : ''))}</b></div>
      <div class="detail-card full"><div class="label">回寄地址</div><b>${esc(r.address || '-')}</b></div>`;

  const repair = r.type === 'repair' ? `
      <div class="detail-card"><div class="label">报修日期</div><b>${esc(r.reportDate || '-')}</b></div>
      <div class="detail-card full"><div class="label">报修原因 / 故障现象</div><b>${esc(r.reason || '-')}</b></div>
      <div class="detail-card"><div class="label">外观情况</div><b>${esc(r.appearance || '-')}</b></div>
      <div class="detail-card"><div class="label">客户寄回物流</div><b>${esc((r.inboundCarrier || '-') + (r.inboundTracking ? ' ' + r.inboundTracking : ''))}</b></div>
      <div class="detail-card"><div class="label">维修后返还物流</div><b>${esc((r.outboundCarrier || '-') + (r.outboundTracking ? ' ' + r.outboundTracking : ''))}</b></div>` : '';

  const loan = r.type === 'loan' ? `
      <div class="detail-card"><div class="label">借出日期</div><b>${esc(r.loanStart || '-')}</b></div>
      <div class="detail-card"><div class="label">预计归还日期</div><b>${esc(r.loanDue || '-')}</b></div>
      <div class="detail-card"><div class="label">到期情况</div><b><span class="tag ${loanDueState(r).cls}">${esc(loanDueState(r).label)}</span></b></div>
      <div class="detail-card"><div class="label">客户归还物流</div><b>${esc((r.inboundCarrier || '-') + (r.inboundTracking ? ' ' + r.inboundTracking : ''))}</b></div>
      <div class="detail-card"><div class="label">借测寄出物流</div><b>${esc((r.outboundCarrier || '-') + (r.outboundTracking ? ' ' + r.outboundTracking : ''))}</b></div>` : '';

  const agreement = r.type === 'loan' ? `
      <div class="detail-card full"><div class="label">借测协议</div>${r.agreement && r.agreement.data ? `<button class="btn" onclick="openRecordAgreement('${r.id}')">查看 / 下载协议</button><div class="agreement-meta">${esc(r.agreement.name || '借测协议')}</div>` : '<span class="danger">未添加</span>'}</div>` : '';
  const importedInfo = r.type === 'loan' ? `
      ${r.borrower ? `<div class="detail-card"><div class="label">借测人</div><b>${esc(r.borrower)}</b></div>` : ''}
      ${r.followOwner ? `<div class="detail-card"><div class="label">需求跟进人</div><b>${esc(r.followOwner)}</b></div>` : ''}
      ${r.returnedDate ? `<div class="detail-card"><div class="label">实际归还日期</div><b>${esc(r.returnedDate)}</b></div>` : ''}
      ${r.recipientInfoRaw ? `<div class="detail-card full"><div class="label">原始收件信息</div><b style="white-space:pre-wrap">${esc(r.recipientInfoRaw)}</b></div>` : ''}
      ${r.returnReason ? `<div class="detail-card"><div class="label">还回原因</div><b>${esc(r.returnReason)}</b></div>` : ''}
      ${r.feedback ? `<div class="detail-card full"><div class="label">反馈</div><b style="white-space:pre-wrap">${esc(r.feedback)}</b></div>` : ''}
      ` : '';

  const rest = `
      <div class="detail-card full"><div class="label">${r.type === 'repair' ? '客户寄回配件' : '随机器配件'}</div><b>${esc(r.accessories || '-')}</b></div>
      <div class="detail-card"><div class="label">最后更新</div><b>${esc(r.updatedAt || '-')}</b></div>
      <div class="detail-card full"><div class="label">${r.type === 'repair' ? '维修过程 / 备注' : '借测备注'}</div><b>${esc(r.notes || '-')}</b></div>
    </div>`;

  const photoHtml = photos.length ? `
    <div class="divider"></div><div class="subhead">设备六面图 / 配件图</div>
    <div class="detail-photo-grid">${photos.map(([i, v], pos) => `<div class="detail-photo"><img src="${v}" onclick="openLightboxByRecord('${r.id}',${pos})"><div>${photoLabels[Number(i)] || ('照片' + (Number(i) + 1))}</div></div>`).join('')}</div>` :
    `<div class="divider"></div><div class="subhead">设备六面图 / 配件图</div>
    <div class="empty" style="display:flex;flex-direction:column;align-items:center;gap:12px">
      <span>此工单未上传图片</span>
      <button class="btn primary" onclick="addPhotosToRecord('${r.id}')">+ 添加图片</button>
    </div>`;

  $('drawerBody').innerHTML = actionBar + common + repair + loan + agreement + (r.type === 'loan' ? `<div class="detail-grid">${importedInfo}</div>` : '') + rest + (r.type === 'loan' ? followUpTimelineHtml(r) : '') + photoHtml;
  $('drawer').classList.add('open'); $('drawerOverlay').classList.add('open');
}

const MAIN_CARRIERS = ['顺丰', '京东物流', '德邦', '中通', '圆通', '申通', '韵达', '极兔', 'EMS', '邮政', '跨越速运', '安能', '其他'];
function carrierOptions(selected = '') {
  return '<option value="">请选择</option>' + MAIN_CARRIERS.map(x => `<option ${x === selected ? 'selected' : ''}>${x}</option>`).join('');
}
function accessoryOptions(selected = '') {
  const opts = ['裸机', '5m标配', '15m标配', '25m标配'];
  let html = '<option value="">请选择</option>' + opts.map(x => `<option ${x === selected ? 'selected' : ''}>${x}</option>`).join('');
  if (selected && !opts.includes(selected)) html += `<option selected>${esc(selected)}</option>`;
  return html;
}

function startRecordInlineEdit(id) {
  const r = load(DB_KEY, []).find(x => x.id === id); if (!r) return;
  $('dEyebrow').textContent = (r.type === 'repair' ? '维修' : '借测') + '工单编辑';
  $('dTitle').textContent = displayOrderNo(r) || `${r.type === 'repair' ? '维修' : '借测'} · ${r.customer || r.model || r.sn || '详情'}`;
  const typeFields = r.type === 'repair' ? `
      <div><label>报修日期</label><input id="ieReportDate" type="date" value="${esc(r.reportDate || '')}"></div>
      <div><label>当前状态</label><select id="ieStatus"><option ${r.status === '待寄回' ? 'selected' : ''}>待寄回</option><option ${r.status === '维修中' ? 'selected' : ''}>维修中</option><option ${r.status === '已完成' ? 'selected' : ''}>已完成</option></select></div>
      <div class="full"><label>报修原因 / 故障现象</label><textarea id="ieReason">${esc(r.reason || '')}</textarea></div>
      <div class="full"><label>外观情况</label><input id="ieAppearance" value="${esc(r.appearance || '')}"></div>
      <div><label>客户寄回物流公司</label><select id="ieInCarrier">${carrierOptions(r.inboundCarrier || '')}</select></div>
      <div><label>客户寄回快递单号</label><input id="ieInTracking" value="${esc(r.inboundTracking || '')}"></div>
      <div><label>维修后返还物流</label><input value="顺丰（固定）" disabled></div>
      <div><label>维修后返还快递单号</label><input id="ieOutTracking" value="${esc(r.outboundTracking || '')}"></div>` :
    `<div><label>借出日期</label><input id="ieLoanStart" type="date" value="${esc(r.loanStart || '')}"></div>
      <div><label>预计归还日期</label><input id="ieLoanDue" type="date" value="${esc(r.loanDue || '')}"></div>
      <div><label>当前状态</label><select id="ieStatus"><option ${r.status === '借测中' ? 'selected' : ''}>借测中</option><option ${r.status === '已归还' ? 'selected' : ''}>已归还</option></select></div>
      <div></div>
      <div><label>借测寄出物流公司</label><select id="ieOutCarrier">${carrierOptions(r.outboundCarrier || '')}</select></div>
      <div><label>借测寄出快递单号</label><input id="ieOutTracking" value="${esc(r.outboundTracking || '')}"></div>
      <div><label>客户归还物流公司</label><select id="ieInCarrier">${carrierOptions(r.inboundCarrier || '')}</select></div>
      <div><label>客户归还快递单号</label><input id="ieInTracking" value="${esc(r.inboundTracking || '')}"></div>`;

  $('drawerBody').innerHTML = `
    <div class="drawer-top-actions">
      <button class="btn primary" onclick="saveRecordInlineEdit('${r.id}')">保存修改</button>
      <button class="btn" onclick="openRecord('${r.id}')">取消</button>
      ${r.type === 'repair' ? `<button class="btn" onclick="saveInlineAndPdf('${r.id}')">保存并生成维修 PDF</button>` : ''}
    </div>
    <div class="inline-edit-grid">
      <div><label>设备型号</label><input id="ieModel" value="${esc(r.model || '')}"></div>
      <div><label>设备 SN</label><input id="ieSN" value="${esc(r.sn || '')}"></div>
      <div><label>客户</label><input id="ieCustomer" value="${esc(r.customer || '')}"></div>
      <div><label>联系人</label><input id="ieContact" value="${esc(r.contact || '')}"></div>
      <div><label>联系电话</label><input id="iePhone" value="${esc(r.phone || '')}"></div>
      <div></div>
      <div class="full"><label>回寄地址</label><input id="ieAddress" value="${esc(r.address || '')}"></div>
      ${typeFields}
      <div class="full"><label>${r.type === 'repair' ? '客户寄回配件' : '随机器配件'}</label>${r.type === 'repair' ? `<textarea id="ieAccessories">${esc(r.accessories || '')}</textarea>` : `<select id="ieAccessories">${accessoryOptions(r.accessories || '')}</select>`}</div>
      <div class="full"><label>${r.type === 'repair' ? '维修过程 / 备注' : '借测备注'}</label><textarea id="ieNotes">${esc(r.notes || '')}</textarea></div>
    </div>`;
  $('drawer').classList.add('open'); $('drawerOverlay').classList.add('open');
}
function saveRecordInlineEdit(id) {
  let arr = load(DB_KEY, []), r = arr.find(x => x.id === id); if (!r) return;
  const oldSN = r.sn;
  r.model = $('ieModel').value.trim(); r.sn = $('ieSN').value.trim(); r.customer = $('ieCustomer').value.trim();
  r.contact = $('ieContact').value.trim(); r.phone = $('iePhone').value.trim(); r.status = $('ieStatus').value;
  r.address = $('ieAddress').value.trim();
  r.inboundCarrier = $('ieInCarrier').value.trim(); r.inboundTracking = $('ieInTracking').value.trim();
  r.outboundCarrier = (r.type === 'repair' ? '顺丰' : $('ieOutCarrier').value.trim()); r.outboundTracking = $('ieOutTracking').value.trim();
  r.accessories = $('ieAccessories').value.trim(); r.notes = $('ieNotes').value.trim();
  if (r.type === 'repair') {
    r.reportDate = $('ieReportDate').value; r.reason = $('ieReason').value.trim(); r.appearance = $('ieAppearance').value.trim();
  } else {
    r.loanStart = $('ieLoanStart').value; r.loanDue = $('ieLoanDue').value;
  }
  r.updatedAt = nowStr();
  if (!r.customer) { alert('客户不能为空。'); return Promise.resolve(false) }
  let pending = save(DB_KEY, arr);
  if (oldSN !== r.sn) {
    let devs = load(DEV_KEY, []), d = devs.find(x => x.sn === oldSN); if (d) d.sn = r.sn; pending = save(DEV_KEY, devs);
  }
  return pending.then(() => ensureDeviceFromRecord(r)).then(() => {
    renderRecords(r.type); renderDashboard(); renderDevices();
    openRecord(id);
    return true;
  });
}
function safeFileName(s = '') { return String(s).replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, ' ').trim() }
function dataUrlToBlob(dataUrl) {
  const [head, data] = dataUrl.split(','); const mime = (head.match(/data:(.*?);/) || [])[1] || 'image/jpeg';
  const bin = atob(data), arr = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], { type: mime });
}
function photoExt(dataUrl) { const m = (dataUrl || '').match(/^data:image\/([a-zA-Z0-9+.-]+);/); let ext = m ? m[1].toLowerCase() : 'jpg'; if (ext === 'jpeg') ext = 'jpg'; return ext }
async function downloadRecordPhotos(recordId) {
  const r = load(DB_KEY, []).find(x => x.id === recordId); if (!r) return;
  const photos = Object.entries(r.photos || {}).filter(([, v]) => v);
  if (!photos.length) { alert('当前工单没有图片。'); return }
  if (!window.JSZip) {
    try { await ensureCdn('jszip') } catch (e) { alert('压缩组件加载失败，请检查网络后重试。'); return }
  }
  const zip = new JSZip();
  for (const [i, src] of photos) {
    const label = photoLabels[Number(i)] || `照片${Number(i) + 1}`;
    const blob = src.startsWith('data:') ? dataUrlToBlob(src) : await (await fetch(src, { credentials: 'same-origin' })).blob();
    zip.file(`${safeFileName(label)}图.${photoExt(src)}`, blob);
  }
  const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } });
  const name = `${safeFileName(r.customer || '客户')}的${safeFileName(r.model || '设备')}图片_${safeFileName(displayOrderNo(r))}.zip`;
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function openRecordAgreement(id) {
  const r = load(DB_KEY, []).find(x => x.id === id); if (!r || !r.agreement || !r.agreement.data) return;
  const a = r.agreement;
  openDataFile(a.data, a.name || '借测协议', a.type || '');
}
let lightboxItems = [], lightboxIndex = 0;
function openLightboxByRecord(recordId, index = 0) {
  const r = load(DB_KEY, []).find(x => x.id === recordId); if (!r) return;
  lightboxItems = Object.entries(r.photos || {}).filter(([, v]) => v).map(([i, src]) => ({ src, label: photoLabels[Number(i)] || '照片' }));
  if (!lightboxItems.length) return;
  lightboxIndex = Math.max(0, Math.min(index, lightboxItems.length - 1));
  renderLightbox(); $('imageLightbox').classList.add('open');
}
function renderLightbox() {
  const item = lightboxItems[lightboxIndex]; if (!item) return;
  $('lightboxImage').src = item.src;
  $('lightboxCaption').textContent = `${item.label} · ${lightboxIndex + 1}/${lightboxItems.length}`;
  $('imageLightbox').querySelector('.lightbox-prev').style.display = lightboxItems.length > 1 ? 'block' : 'none';
  $('imageLightbox').querySelector('.lightbox-next').style.display = lightboxItems.length > 1 ? 'block' : 'none';
}
function lightboxStep(step) { if (!lightboxItems.length) return; lightboxIndex = (lightboxIndex + step + lightboxItems.length) % lightboxItems.length; renderLightbox() }
function closeLightbox() { $('imageLightbox').classList.remove('open'); $('lightboxImage').src = '' }
function lightboxBackdrop(e) { if (e.target === $('imageLightbox')) closeLightbox() }


function showDueWarning() {
  const list = dueSoonLoans(true); if (!list.length) return;
  const todayKey = new Date().toISOString().slice(0, 10); if (sessionStorage.getItem('due_warning_seen') === todayKey) return; sessionStorage.setItem('due_warning_seen', todayKey);
  $('dueWarningList').innerHTML = list.map(r => { const n = daysUntil(r.loanDue), overdue = n < 0, txt = overdue ? `已逾期 ${Math.abs(n)} 天` : n === 0 ? '今天到期' : `${n} 天后到期`; return `<div class="warning-item ${overdue ? 'overdue' : ''}"><div style="display:flex;justify-content:space-between;gap:12px"><b>${esc(r.customer)} · ${esc(r.model || '-')}</b><span class="days">${txt}</span></div><div class="hint" style="margin-top:6px">SN: ${esc(r.sn)} · 预计归还：${esc(r.loanDue)} · ${esc(displayOrderNo(r))}</div><div style="margin-top:8px"><button class="btn" onclick="closeDueWarning();showTab('loans');openRecord('${r.id}')">查看工单</button></div></div>` }).join('');
  $('dueWarningModal').classList.add('open');
}
function closeDueWarning() { $('dueWarningModal').classList.remove('open') }

function closeDrawer() { closeAllDrawers() }
function refreshSNList() { $('deviceSNList').innerHTML = load(DEV_KEY, []).map(d => `<option value="${esc(d.sn)}">${esc(d.model)} · ${esc(d.customer || '')}</option>`).join('') }

function getSettings() { return Object.assign({ sales: '李辉', afterSales: '刘海焕', returnAddress: '深圳市宝安区华丰国际机器人产业园二期A座301 刘海焕：19377730597' }, load(SET_KEY, {})) }
function loadSettings() { }
function saveSettings() { }
/* 维修工单 PDF：由当前维修单实际保存的数据生成，空字段显示“未填写”。 */
function rpVal(v) { const s = String(v || '').trim(); return s || '未填写' }
function fillRepairSheet(r) {
  $('rpDate').textContent = '生成时间：' + nowStr();
  $('rpOrderNo').textContent = rpVal(displayOrderNo(r));
  $('rpReportDate').textContent = rpVal(r.reportDate);
  $('rpCustomer').textContent = rpVal(r.customer);
  $('rpContact').textContent = rpVal(r.contact);
  $('rpPhone').textContent = rpVal(r.phone);
  $('rpModel').textContent = rpVal(r.model);
  $('rpSN').textContent = rpVal(r.sn);
  $('rpAppearance').textContent = rpVal(r.appearance);
  $('rpStatus').textContent = rpVal(r.status);
  $('rpReason').textContent = rpVal(r.reason);
  $('rpNotes').textContent = rpVal(r.notes);
  $('rpInbound').textContent = rpVal((r.inboundCarrier || '') + (r.inboundCarrier && r.inboundTracking ? ' ' : '') + (r.inboundTracking || ''));
  $('rpOutbound').textContent = rpVal((r.outboundCarrier || '顺丰') + (r.outboundTracking ? ' ' + r.outboundTracking : ''));
  $('rpAddress').textContent = rpVal(r.address);
}
async function buildRepairSheetBlob(r) {
  fillRepairSheet(r);
  const sheet = $('repairSheet'); sheet.style.left = '0'; sheet.style.zIndex = '9999';
  try {
    if (!(window.html2canvas && window.jspdf)) {
      try { await Promise.all([ensureCdn('html2canvas'), ensureCdn('jspdf')]) } catch (e) { /* fall through to guard below */ }
    }
    if (!(window.html2canvas && window.jspdf)) throw new Error('PDF component unavailable');
    const canvas = await html2canvas(sheet, { scale: 1.7, backgroundColor: '#fff', useCORS: true });
    const img = canvas.toDataURL('image/jpeg', 0.96); const { jsPDF } = window.jspdf; const pdf = new jsPDF('p', 'mm', 'a4');
    const pw = 210, ph = 297, iw = pw - 10, ih = canvas.height * iw / canvas.width; let y = 5, left = ih;
    pdf.addImage(img, 'JPEG', 5, y, iw, ih); left -= ph - 10;
    while (left > 0) { pdf.addPage(); y = -(ih - left) + 5; pdf.addImage(img, 'JPEG', 5, y, iw, ih); left -= ph - 10 }
    return pdf.output('blob');
  } finally {
    sheet.style.left = '-200vw'; sheet.style.zIndex = '-1';
  }
}
async function downloadRepairSheetPDF(r) {
  try {
    const blob = await buildRepairSheetBlob(r), url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = `维修工单-${safeFileName(displayOrderNo(r) || '无单号')}-${safeFileName(r.customer || '未填写')}.pdf`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
  } catch (e) {
    console.error(e); alert('维修工单 PDF 生成失败，请重试。');
  }
}
/* 详情/列表入口：直接用已保存的数据生成。 */
function repairPdfById(id) {
  const r = load(DB_KEY, []).find(x => x.id === id);
  if (r && r.type === 'repair') downloadRepairSheetPDF(r);
}
/* 新建/编辑抽屉入口：先把最新修改保存落库，再用保存后的数据生成。 */
async function generateRepairPdfFromForm() {
  if ($('rType').value !== 'repair') { alert('借测单不生成维修工单 PDF。'); return }
  const r = collectRecord();
  if (!r.customer) { alert('请至少填写客户 / 报修单位后再生成 PDF。'); return }
  try { await flowOnline.persistRecordFiles(r) } catch (err) { alert('附件上传失败：' + err.message); return }
  let arr = load(DB_KEY, []), idx = arr.findIndex(x => x.id === r.id); if (idx >= 0) arr[idx] = r; else arr.unshift(r);
  try { await save(DB_KEY, arr) } catch (err) { alert('工单保存失败：' + err.message); return }
  await ensureDeviceFromRecord(r);
  editingRecordId = r.id;
  $('recordTitle').textContent = '编辑维修工单 · ' + displayOrderNo(r);
  renderRecords('repair'); renderDashboard(); renderDevices();
  await downloadRepairSheetPDF(r);
}
/* 内联编辑入口：先保存修改再生成。 */
async function saveInlineAndPdf(id) {
  await saveRecordInlineEdit(id);
  const r = load(DB_KEY, []).find(x => x.id === id);
  if (r && r.type === 'repair') await downloadRepairSheetPDF(r);
}

function migrateRecords() {
  let arr = load(DB_KEY, []), changed = false;
  arr.forEach(r => { if (!r.orderNo) { r.orderNo = nextOrderNo(r.type); changed = true } });
  if (changed) save(DB_KEY, arr);
}
function restoreViewState() {
  const state = getViewState();
  const tab = TAB_KEYS.includes(state.tab) ? state.tab : 'dashboard';
  showTab(tab, { skipSave: true });
  requestAnimationFrame(() => window.scrollTo(0, (state.scroll || {})[tab] || 0));
}

/* 事件绑定统一收口，dispose() 可整体移除，保证 React  StrictMode 重复挂载安全。 */
const cleanups = [];
let viewStateSaveTimer = null;
function on(target, type, fn, opts) { target.addEventListener(type, fn, opts); cleanups.push(() => target.removeEventListener(type, fn, opts)); }
function bindEvents() {
  document.querySelectorAll('.flow-tabs button').forEach(b => { b.onclick = () => showTab(b.dataset.tab); });
  $('rSN').addEventListener('input', () => { const d = load(DEV_KEY, []).find(x => x.sn === $('rSN').value.trim()); if (d) { $('rModel').value = d.model || ''; if (!$('rCustomer').value) $('rCustomer').value = d.customer || '' } });

  on(document, 'keydown', e => {
    // 图片大图优先：Esc/方向键只作用于 Lightbox，不级联关闭抽屉
    if ($('imageLightbox') && $('imageLightbox').classList.contains('open')) {
      if (e.key === 'Escape') { closeLightbox(); return; }
      if (e.key === 'ArrowLeft') { lightboxStep(-1); return; }
      if (e.key === 'ArrowRight') { lightboxStep(1); return; }
    }
    if (e.key === 'Escape') {
      if ($('newRecord').classList.contains('open')) { requestCloseRecordDrawer(); return; }
      if ($('drawer').classList.contains('open')) closeAllDrawers();
      return;
    }
    if ((e.key === 'Backspace' || e.key === 'Delete') && selectedPhotoKey !== null) {
      const active = document.activeElement;
      if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName)) return;
      if ($('newRecord').classList.contains('open') && currentPhotos[selectedPhotoKey]) {
        e.preventDefault();
        removeCurrentPhoto(selectedPhotoKey);
      }
    }
  });

  on(window, 'scroll', () => {
    clearTimeout(viewStateSaveTimer);
    viewStateSaveTimer = setTimeout(() => saveViewState({}), 120);
  }, { passive: true });
  on(window, 'beforeunload', () => saveViewState({}));
}

let alive = false;
let initPromise = null;
function init() {
  alive = true;
  if (!initPromise) {
    initPromise = (async () => {
      const ready = await flowOnline.init();
      if (!ready || !alive) return;
      bindEvents();
      toggleTypeFields(); renderPhotoGrid(); renderAgreementStatus(); refreshSNList(); updateRecycleCount();
      const requested = new URLSearchParams(location.search).get('tab');
      if (TAB_KEYS.includes(requested)) showTab(requested, { skipSave: true });
      else restoreViewState();
      setTimeout(() => { if (alive) showDueWarning(); }, 300);
    })();
    const pending = initPromise;
    pending.catch(() => undefined).finally(() => { initPromise = null; });
    return pending;
  }
  return initPromise;
}
function dispose() {
  alive = false;
  cleanups.splice(0).forEach(fn => { try { fn() } catch (e) { } });
  clearTimeout(viewStateSaveTimer); viewStateSaveTimer = null;
  Object.keys(cache).forEach(k => { delete cache[k]; });
  renderedTabs.clear(); dirtyTabs.clear();
  currentPhotos = {}; currentAgreement = null; editingRecordId = null; selectedPhotoKey = null; draggingPhotoKey = null;
  currentDeviceFilter = '借测中'; recycleTab = 'records'; dashboardAction = 'overdue'; currentTab = 'dashboard';
  lightboxItems = []; lightboxIndex = 0;
}

/* 片段内联 onclick / oninput 处理器需要全局可访问的函数 */
Object.assign(window, {
  $, showTab, closeAllDrawers, closeDrawer, overlayClick, backToRecordList, goNew, editRecord, saveRecord,
  resetRecordForm, clearCurrentForm, toggleTypeFields, parseSemanticInput,
  openDevice, openDeviceBySN, deleteDevice, setDeviceFilter, renderDevices,
  renderRecords, renderDashboard, setDashboardAction, dashboardJump,
  exportRecordsExcel, delRecord, repairPdfById, generateRepairPdfFromForm, saveInlineAndPdf,
  setRecycleTab, renderRecycleBin, restoreRecord, purgeRecord, restoreDevice, purgeDevice, emptyRecycleBin,
  openRecord, startRecordInlineEdit, saveRecordInlineEdit, downloadRecordPhotos, openRecordAgreement, addPhotosToRecord,
  openLightboxByRecord, lightboxStep, closeLightbox, lightboxBackdrop,
  addFollowUp, removeFollowUp,
  selectPhotoSlot, previewCurrentPhoto, removeCurrentPhoto, handlePhoto,
  photoDragStart, photoDragEnd, photoDragEnter, photoDragOver, photoDragLeave, photoDrop,
  agreementDragEnter, agreementDragLeave, agreementDrop, handleAgreementFile, viewAgreement, removeAgreement, parseCurrentAgreement,
  closeDueWarning, showDueWarning, refreshSNList, clearDemoData, addDemoData,
});

window.deviceFlowApp = { init, dispose };
})();
