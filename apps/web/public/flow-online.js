(() => {
  const keys = {
    device_flow_records_v28_real: 'records',
    device_flow_devices_v28_real: 'devices',
    device_flow_recycle_v28_real: 'recycle',
    device_flow_settings_v28_real: 'settings',
  };
  let state = null;
  let revision = 0;
  let timer = null;
  let saving = false;
  let blocked = false;
  let lastSent = '';
  const pending = [];
  const copy = (value) => structuredClone(value);

  let hideTimer = null;
  function status(message, error = false) {
    let node = document.getElementById('flowSyncStatus');
    if (!node) {
      node = document.createElement('div');
      node.id = 'flowSyncStatus';
      node.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;padding:7px 12px;border:1px solid #ddd;border-radius:6px;background:#fff;font-size:12px;box-shadow:0 2px 8px #0002';
      document.body.append(node);
    }
    node.textContent = message;
    node.style.color = error ? '#b91c1c' : '#333';
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    if (error) {
      // 保存失败 / 多人编辑冲突：常驻提示，直到下一次状态变化
      if (blocked) {
        const reload = document.createElement('button');
        reload.type = 'button';
        reload.textContent = '重新加载';
        reload.style.cssText = 'margin-left:10px;border:1px solid #b91c1c;background:white;color:#b91c1c;border-radius:4px;cursor:pointer';
        reload.onclick = () => location.reload();
        node.append(reload);
      }
      return;
    }
    // 连接/保存成功：短暂提示后自动消失，避免常驻遮挡
    hideTimer = setTimeout(() => { const current = document.getElementById('flowSyncStatus'); if (current) current.remove(); }, 2000);
  }

  async function init() {
    const response = await fetch('/api/html-device-flow/snapshot', { credentials: 'same-origin' });
    if (response.status === 401 || response.status === 403) {
      top.location.href = '/login';
      return false;
    }
    if (!response.ok) throw new Error('设备流转数据加载失败');
    const snapshot = await response.json();
    state = snapshot.data;
    revision = snapshot.revision;
    status('已连接');
    return true;
  }

  function load(key, fallback) {
    const name = keys[key];
    return name && state ? copy(state[name] ?? fallback) : fallback;
  }

  function save(key, value) {
    const name = keys[key];
    if (!name || !state || blocked) {
      const result = Promise.reject(new Error(blocked ? '数据已被其他人更新，请刷新后重新操作' : '尚未加载设备流转数据'));
      result.catch(() => undefined);
      return result;
    }
    state[name] = copy(value);
    status('正在保存…');
    if (timer) clearTimeout(timer);
    timer = setTimeout(flush, 80);
    const result = new Promise((resolve, reject) => pending.push({ resolve, reject }));
    // Many original HTML handlers do not await save; keep their failures visible without unhandled rejections.
    result.catch(() => undefined);
    return result;
  }

  async function flush() {
    timer = null;
    if (saving || blocked || !pending.length) return;
    saving = true;
    const batch = pending.splice(0);
    const payload = JSON.stringify({ revision, data: state });
    lastSent = JSON.stringify(state);
    try {
      const form = new FormData();
      form.append('payload', new Blob([payload], { type: 'application/json' }), 'state.json');
      const response = await fetch('/api/html-device-flow/sync', { method: 'POST', body: form, credentials: 'same-origin' });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        if (response.status === 409) blocked = true;
        throw new Error(error.message || `保存失败 (${response.status})`);
      }
      revision = (await response.json()).revision;
      batch.forEach((item) => item.resolve());
      status('已保存到服务器');
    } catch (error) {
      batch.forEach((item) => item.reject(error));
      status(error.message, true);
      if (blocked) alert('其他人已修改设备流转数据。当前页面不会覆盖其修改，请刷新页面后重新操作。');
    } finally {
      saving = false;
      if (pending.length || (!blocked && JSON.stringify(state) !== lastSent)) {
        if (!blocked) timer = setTimeout(flush, 80);
      }
    }
  }

  async function uploadDataUrl(dataUrl, name) {
    const blob = await (await fetch(dataUrl)).blob();
    const form = new FormData();
    form.append('file', blob, name);
    const response = await fetch('/api/html-device-flow/files', { method: 'POST', body: form, credentials: 'same-origin' });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).message || '文件上传失败');
    return response.json();
  }

  async function persistRecordFiles(record) {
    const photos = { ...(record.photos || {}) };
    for (const [key, value] of Object.entries(photos)) {
      if (typeof value === 'string' && value.startsWith('data:')) {
        photos[key] = (await uploadDataUrl(value, `设备图片-${key}.jpg`)).url;
      }
    }
    record.photos = photos;
    if (record.agreement?.data?.startsWith('data:')) {
      const result = await uploadDataUrl(record.agreement.data, record.agreement.name || '借测协议.pdf');
      record.agreement = { ...record.agreement, data: result.url };
    }
  }

  async function asDataUrl(value) {
    if (!value || value.startsWith('data:')) return value;
    const blob = await (await fetch(value, { credentials: 'same-origin' })).blob();
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  window.addEventListener('beforeunload', (event) => {
    if ((saving || pending.length || timer) && !blocked) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  window.flowOnline = { init, load, save, persistRecordFiles, asDataUrl };
})();
