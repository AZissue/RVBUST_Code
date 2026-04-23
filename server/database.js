const { Low } = require('lowdb');
const { JSONFile } = require('lowdb/node');
const path = require('path');
const fs = require('fs');

const DB_DIR = path.join(__dirname, 'data');
const DB_PATH = path.join(DB_DIR, 'db.json');

if (!fs.existsSync(DB_DIR)) fs.mkdirSync(DB_DIR, { recursive: true });

const adapter = new JSONFile(DB_PATH);
const db = new Low(adapter, { users: [], customers: [], tickets: [] });

function generateId(prefix = 'id') {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).substring(2, 6)}`;
}

function generateTicketId() {
  const n = new Date();
  const yy = String(n.getFullYear()).slice(2);
  const mm = String(n.getMonth() + 1).padStart(2, '0');
  const dd = String(n.getDate()).padStart(2, '0');
  const rand = String(Math.floor(Math.random() * 900) + 100);
  return `TK${yy}${mm}${dd}${rand}`;
}

async function initDb() {
  await db.read();
  if (!db.data) db.data = { users: [], customers: [], tickets: [] };
}

const dbApi = {
  async init() { await initDb(); },

  async getUsers() { await initDb(); return db.data.users; },
  async getUserByUsername(username) { await initDb(); return db.data.users.find(u => u.username === username); },
  async getUserById(id) { await initDb(); return db.data.users.find(u => u.id === id); },
  async createUser(user) { await initDb(); db.data.users.push(user); await db.write(); return user; },
  async updateUser(id, fields) {
    await initDb();
    const idx = db.data.users.findIndex(u => u.id === id);
    if (idx >= 0) { Object.assign(db.data.users[idx], fields); await db.write(); }
  },

  async getCustomers() { await initDb(); return db.data.customers; },
  async getCustomerById(id) { await initDb(); return db.data.customers.find(c => c.id === id); },
  async createCustomer(c) { await initDb(); db.data.customers.push(c); await db.write(); return c; },
  async updateCustomer(id, fields) {
    await initDb();
    const idx = db.data.customers.findIndex(c => c.id === id);
    if (idx >= 0) { Object.assign(db.data.customers[idx], fields); await db.write(); }
  },
  async deleteCustomer(id) {
    await initDb();
    db.data.customers = db.data.customers.filter(c => c.id !== id);
    await db.write();
  },

  async getTickets() { await initDb(); return db.data.tickets.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt)); },
  async getTicketById(id) { await initDb(); return db.data.tickets.find(t => t.id === id); },
  async createTicket(t) { await initDb(); db.data.tickets.push(t); await db.write(); return t; },
  async updateTicket(id, fields) {
    await initDb();
    const idx = db.data.tickets.findIndex(t => t.id === id);
    if (idx >= 0) { Object.assign(db.data.tickets[idx], fields); await db.write(); }
  },
  async deleteTicket(id) {
    await initDb();
    db.data.tickets = db.data.tickets.filter(t => t.id !== id);
    await db.write();
  },

  generateId,
  generateTicketId,

  async seedData() {
    await initDb();
    if (db.data.users.length > 0) return;

    const now = new Date();
    const d = (days, hours = 0) => new Date(now.getTime() - days * 86400000 - hours * 3600000).toISOString();

    const users = [
      { id: 'u1', username: 'admin', password: 'admin123', name: '系统管理员', role: 'admin', email: 'admin@company.com', phone: '13800138000', color: '#7c3aed', isActive: true, createdAt: d(30, 0) },
      { id: 'u2', username: 'zhangsan', password: '123456', name: '张三', role: 'engineer', email: 'zhangsan@company.com', phone: '13800138001', color: '#2563eb', isActive: true, createdAt: d(30, 0) },
      { id: 'u3', username: 'lisi', password: '123456', name: '李四', role: 'engineer', email: 'lisi@company.com', phone: '13800138002', color: '#059669', isActive: true, createdAt: d(28, 0) },
      { id: 'u4', username: 'wangwu', password: '123456', name: '王五', role: 'engineer', email: 'wangwu@company.com', phone: '13800138003', color: '#d97706', isActive: true, createdAt: d(25, 0) },
      { id: 'u5', username: 'zhaoliu', password: '123456', name: '赵六', role: 'engineer', email: 'zhaoliu@company.com', phone: '13800138004', color: '#dc2626', isActive: true, createdAt: d(20, 0) },
    ];
    db.data.users = users;

    const customers = [
      { id: 'c1', name: '科技创新有限公司', contact: '陈经理', phone: '13900001111', email: 'chen@tech.com', address: '北京市海淀区中关村大街1号', industry: '互联网', level: 'A', devices: [{ name: '服务器A', model: 'Dell R740', sn: 'SN123456' }, { name: '交换机', model: 'Cisco 2960', sn: 'SN789012' }], createdAt: d(15, 10) },
      { id: 'c2', name: '智慧物流公司', contact: '刘总', phone: '13900002222', email: 'liu@wiselog.com', address: '上海市浦东新区张江路2号', industry: '物流', level: 'A', devices: [{ name: '条码打印机', model: 'Zebra ZT410', sn: 'SN345678' }], createdAt: d(30, 9) },
      { id: 'c3', name: '绿色能源集团', contact: '王工', phone: '13900003333', email: 'wang@green.com', address: '广州市天河区珠江新城3号', industry: '能源', level: 'B', devices: [{ name: '工控机', model: 'Advantech UNO', sn: 'SN901234' }, { name: '传感器', model: 'Siemens S7', sn: 'SN567890' }], createdAt: d(25, 14) },
      { id: 'c4', name: '金融数据服务', contact: '张经理', phone: '13900004444', email: 'zhang@fin.com', address: '深圳市福田区金融中心4号', industry: '金融', level: 'A', devices: [{ name: '存储阵列', model: 'EMC VNX', sn: 'SN111222' }], createdAt: d(10, 11) },
      { id: 'c5', name: '医疗科技股份', contact: '李主任', phone: '13900005555', email: 'li@med.com', address: '杭州市西湖区文三路5号', industry: '医疗', level: 'B', devices: [{ name: 'PACS服务器', model: 'HP DL380', sn: 'SN333444' }], createdAt: d(20, 8) },
      { id: 'c6', name: '教育科技集团', contact: '赵老师', phone: '13900006666', email: 'zhao@edu.com', address: '南京市鼓楼区中山路6号', industry: '教育', level: 'C', devices: [{ name: '投影机', model: 'Epson CB', sn: 'SN555666' }], createdAt: d(5, 15) },
      { id: 'c7', name: '智能制造工厂', contact: '孙厂长', phone: '13900007777', email: 'sun@smart.com', address: '苏州市工业园区星湖街7号', industry: '制造', level: 'B', devices: [{ name: 'CNC机床', model: 'Fanuc 0i', sn: 'SN777888' }, { name: 'PLC控制器', model: 'Mitsubishi FX', sn: 'SN999000' }], createdAt: d(1, 10) },
      { id: 'c8', name: '电子商务平台', contact: '周运营', phone: '13900008888', email: 'zhou@ecom.com', address: '成都市高新区天府大道8号', industry: '电商', level: 'A', devices: [{ name: '负载均衡', model: 'F5 BIG-IP', sn: 'SN121212' }], createdAt: d(8, 9) },
    ];
    db.data.customers = customers;

    const tickets = [
      { id: 'TK001', title: '服务器无法远程连接', customerId: 'c1', engineerId: 'u2', status: 'processing', priority: 'high', category: '硬件故障', description: '客户反映服务器A从今早8点开始无法通过RDP远程连接，现场指示灯正常。', createdAt: d(0, 4), updatedAt: d(0, 2), dueDate: d(-1), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u2', userName: '张三', content: '已联系客户，准备远程排查。', createdAt: d(0, 3) }] },
      { id: 'TK002', title: '网络间歇性断线', customerId: 'c2', engineerId: 'u3', status: 'pending', priority: 'medium', category: '网络问题', description: '仓库区域WiFi频繁断线，影响扫码入库操作。', createdAt: d(1, 2), updatedAt: d(1, 2), dueDate: d(0), creatorId: 'u1', comments: [] },
      { id: 'TK003', title: '工控机系统蓝屏', customerId: 'c3', engineerId: 'u2', status: 'resolved', priority: 'high', category: '系统故障', description: '生产线工控机频繁蓝屏，错误代码0x0000007E。', createdAt: d(3, 5), updatedAt: d(1, 1), dueDate: d(-2), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u2', userName: '张三', content: '已更换内存条，问题解决。', createdAt: d(1, 1) }] },
      { id: 'TK004', title: '存储阵列容量告警', customerId: 'c4', engineerId: 'u4', status: 'processing', priority: 'medium', category: '存储问题', description: 'EMC存储阵列使用率超过85%，需要扩容或清理。', createdAt: d(0, 6), updatedAt: d(0, 1), dueDate: d(-1), creatorId: 'u1', comments: [] },
      { id: 'TK005', title: 'PACS系统访问缓慢', customerId: 'c5', engineerId: 'u5', status: 'pending', priority: 'low', category: '性能问题', description: '医生反映PACS影像加载时间过长，影响诊断效率。', createdAt: d(2, 3), updatedAt: d(2, 3), dueDate: d(1), creatorId: 'u1', comments: [] },
      { id: 'TK006', title: '投影机无法开机', customerId: 'c6', engineerId: 'u3', status: 'resolved', priority: 'low', category: '硬件故障', description: '教室投影机按下电源键无反应，灯泡已更换。', createdAt: d(5, 2), updatedAt: d(3, 4), dueDate: d(-4), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u3', userName: '李四', content: '电源板故障，已更换。', createdAt: d(3, 4) }] },
      { id: 'TK007', title: 'CNC机床程序报错', customerId: 'c7', engineerId: 'u4', status: 'processing', priority: 'high', category: '设备故障', description: '加工程序运行到第N120行报警，显示伺服异常。', createdAt: d(0, 8), updatedAt: d(0, 3), dueDate: d(0), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u4', userName: '王五', content: '正在排查伺服驱动器。', createdAt: d(0, 3) }] },
      { id: 'TK008', title: '负载均衡配置更新', customerId: 'c8', engineerId: 'u5', status: 'pending', priority: 'medium', category: '配置变更', description: '需要为新上线业务配置负载均衡策略。', createdAt: d(1, 5), updatedAt: d(1, 5), dueDate: d(0), creatorId: 'u1', comments: [] },
      { id: 'TK009', title: '交换机端口故障', customerId: 'c1', engineerId: 'u2', status: 'resolved', priority: 'medium', category: '网络问题', description: 'Cisco交换机第12端口频繁UP/DOWN。', createdAt: d(4, 2), updatedAt: d(2, 5), dueDate: d(-3), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u2', userName: '张三', content: '更换网线后稳定。', createdAt: d(2, 5) }] },
      { id: 'TK010', title: '条码打印机卡纸', customerId: 'c2', engineerId: 'u3', status: 'resolved', priority: 'low', category: '硬件故障', description: '打印机频繁卡纸，已清理多次。', createdAt: d(6, 1), updatedAt: d(4, 3), dueDate: d(-5), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u3', userName: '李四', content: '更换搓纸轮，问题解决。', createdAt: d(4, 3) }] },
      { id: 'TK011', title: '传感器数据异常', customerId: 'c3', engineerId: 'u4', status: 'processing', priority: 'medium', category: '设备故障', description: '温度传感器读数异常，显示-40度。', createdAt: d(0, 5), updatedAt: d(0, 1), dueDate: d(-1), creatorId: 'u1', comments: [] },
      { id: 'TK012', title: '数据库备份失败', customerId: 'c4', engineerId: 'u5', status: 'pending', priority: 'high', category: '系统故障', description: '近3天数据库自动备份任务均失败。', createdAt: d(2, 6), updatedAt: d(2, 6), dueDate: d(0), creatorId: 'u1', comments: [] },
      { id: 'TK013', title: '服务器硬盘告警', customerId: 'c5', engineerId: 'u2', status: 'processing', priority: 'high', category: '硬件故障', description: 'RAID5中一块硬盘报错，需更换。', createdAt: d(0, 3), updatedAt: d(0, 1), dueDate: d(0), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u2', userName: '张三', content: '已申请备件，预计明天更换。', createdAt: d(0, 1) }] },
      { id: 'TK014', title: 'PLC通信中断', customerId: 'c7', engineerId: 'u4', status: 'pending', priority: 'high', category: '设备故障', description: 'PLC与HMI通信中断，产线停止。', createdAt: d(0, 2), updatedAt: d(0, 2), dueDate: d(0), creatorId: 'u1', comments: [] },
      { id: 'TK015', title: '网站访问502错误', customerId: 'c8', engineerId: 'u5', status: 'processing', priority: 'high', category: '应用故障', description: '用户反馈网站间歇性出现502 Bad Gateway。', createdAt: d(0, 1), updatedAt: d(0, 0.5), dueDate: d(0), creatorId: 'u1', comments: [{ id: generateId(), userId: 'u5', userName: '赵六', content: '正在检查后端服务状态。', createdAt: d(0, 0.5) }] },
    ];
    db.data.tickets = tickets;
    await db.write();
    console.log('[DB] Seed data created.');
  },

  async getReminders() { await initDb(); return db.data.reminders || []; },
  async addReminder(r) { await initDb(); db.data.reminders = db.data.reminders || []; db.data.reminders.push(r); await db.write(); return r; },
  async markReminderRead(id) {
    await initDb();
    db.data.reminders = db.data.reminders || [];
    const idx = db.data.reminders.findIndex(r => r.id === id);
    if (idx >= 0) { db.data.reminders[idx].read = true; await db.write(); }
  },
  async clearReminders(userId) {
    await initDb();
    db.data.reminders = (db.data.reminders || []).map(r => r.toUserId === userId ? { ...r, read: true } : r);
    await db.write();
  }
};

dbApi.seedData().catch(console.error);

module.exports = dbApi;
