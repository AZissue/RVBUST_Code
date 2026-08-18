// 模拟相机数据
const cameras = [
  { id: 'cam0', name: 'M2600R (SN-2024A)', ip: '192.168.1.10', online: true, markers: 8, active: true },
  { id: 'cam1', name: 'M2600R (SN-2024B)', ip: '192.168.1.11', online: true, markers: 5, active: false },
  { id: 'cam2', name: 'M2000 (SN-2024D)', ip: '192.168.1.13', online: true, markers: 6, active: false },
  { id: 'cam3', name: 'X1 (SN-2024C)', ip: '192.168.1.12', online: false, markers: 0, active: false },
];

let calibProgress = 75;

function init() {
  lucide.createIcons();
  renderCameras();
  updateClock();
  setInterval(updateClock, 1000);
  setInterval(simulateTelemetry, 3000);
}

function updateClock() {
  const now = new Date();
  document.getElementById('last-update').textContent = now.toLocaleTimeString('zh-CN', { hour12: false });
}

function renderCameras() {
  const grid = document.getElementById('camera-grid');
  grid.innerHTML = cameras.map((cam, idx) => {
    const markerDots = Array.from({ length: cam.markers }, (_, i) => ({
      left: 25 + Math.random() * 50,
      top: 25 + Math.random() * 50,
      delay: i * 0.15,
    }));

    return `
      <div class="camera-card ${cam.active ? 'active' : ''}" onclick="selectCamera('${cam.id}')">
        <div class="p-3 flex items-center justify-between border-b border-white/5">
          <div class="flex items-center gap-2">
            <div class="w-2 h-2 rounded-full ${cam.online ? 'bg-accent' : 'bg-slate-600'}"></div>
            <span class="font-semibold text-sm">${cam.name}</span>
          </div>
          <span class="text-[10px] text-muted font-mono">${cam.ip}</span>
        </div>
        <div class="camera-feed aspect-[4/3] relative">
          ${cam.online ? `
            <div class="absolute inset-0 flex items-center justify-center">
              <div class="w-24 h-16 rounded bg-white/10 border border-white/20"></div>
            </div>
            ${markerDots.map(m => `
              <div class="marker-dot" style="left:${m.left}%; top:${m.top}%; animation-delay:${m.delay}s"></div>
            `).join('')}
          ` : `
            <div class="absolute inset-0 flex flex-col items-center justify-center text-muted">
              <i data-lucide="wifi-off" class="w-8 h-8 mb-2 opacity-50"></i>
              <span class="text-xs">离线</span>
            </div>
          `}
          ${cam.online ? `<div class="absolute top-2 right-2 px-2 py-0.5 rounded-full bg-black/50 text-[10px] text-accent border border-accent/30">标记 ${cam.markers}</div>` : ''}
        </div>
        <div class="p-3 flex gap-2">
          <button class="btn-icon flex-1 justify-center text-xs gap-1" ${!cam.online ? 'disabled' : ''} onclick="event.stopPropagation(); previewCamera('${cam.id}')">
            <i data-lucide="eye" class="w-3.5 h-3.5"></i>
            预览
          </button>
          <button class="btn-icon flex-1 justify-center text-xs gap-1" ${!cam.online ? 'disabled' : ''} onclick="event.stopPropagation(); captureCamera('${cam.id}')">
            <i data-lucide="camera" class="w-3.5 h-3.5"></i>
            拍摄
          </button>
        </div>
      </div>
    `;
  }).join('');

  lucide.createIcons();
}

function selectCamera(id) {
  cameras.forEach(cam => cam.active = cam.id === id);
  renderCameras();
  showToast('info', `已选中 ${cameras.find(c => c.id === id).name}`);
}

function previewCamera(id) {
  showToast('info', `开始 ${id} 2D 预览`);
}

function captureCamera(id) {
  const cam = cameras.find(c => c.id === id);
  cam.markers = Math.floor(Math.random() * 10) + 3;
  renderCameras();
  addLog(`拍摄完成 ${id}：检测到 ${cam.markers} 个标记`, 'accent');
  showToast('success', `${cam.name} 拍摄完成`);
}

function simulateCapture() {
  cameras.forEach(cam => {
    if (cam.online) {
      cam.markers = Math.floor(Math.random() * 10) + 3;
    }
  });
  renderCameras();
  calibProgress = Math.min(100, calibProgress + 5);
  document.getElementById('calib-progress').textContent = calibProgress + '%';
  addLog('同步拍摄 4 台相机完成', 'accent');
  showToast('success', '同步拍摄完成');
}

function simulateTelemetry() {
  const online = cameras.filter(c => c.online).length;
  document.getElementById('online-cams').textContent = `${online}/${cameras.length}`;
}

function addLog(message, color = 'muted') {
  const panel = document.getElementById('log-panel');
  const now = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const colorClass = {
    accent: 'text-accent',
    blue: 'text-blue-400',
    amber: 'text-amber-400',
    red: 'text-red-400',
    muted: 'text-muted',
  }[color] || 'text-muted';

  const entry = document.createElement('div');
  entry.className = colorClass;
  entry.textContent = `[${now}] ${message}`;
  panel.appendChild(entry);
  panel.scrollTop = panel.scrollHeight;
}

function clearLogs() {
  document.getElementById('log-panel').innerHTML = '<div class="text-muted">[已清空日志]</div>';
}

function showToast(type, message) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type} flex items-start gap-3`;

  const iconName = type === 'success' ? 'check-circle' : 'info';
  const title = type === 'success' ? '成功' : '提示';

  toast.innerHTML = `
    <i data-lucide="${iconName}" class="w-5 h-5 mt-0.5 text-${type === 'success' ? 'accent' : 'blue-400'}"></i>
    <div>
      <div class="font-semibold text-sm">${title}</div>
      <div class="text-xs text-muted mt-0.5">${message}</div>
    </div>
  `;

  container.appendChild(toast);
  lucide.createIcons();

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.25s ease';
    setTimeout(() => toast.remove(), 250);
  }, 3000);
}

// 导航高亮
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', (e) => {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active', 'text-white'));
    e.target.classList.add('active');
  });
});

// 初始化
document.addEventListener('DOMContentLoaded', init);
