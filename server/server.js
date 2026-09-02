const express = require('express');
const cors = require('cors');
const path = require('path');
const multer = require('multer');
const fs = require('fs');
const db = require('./database');

const app = express();
const PORT = process.env.PORT || 8080;

// ===== 文件上传配置 =====
const UPLOAD_DIR = path.join(__dirname, '..', 'project', 'uploads');
if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, UPLOAD_DIR),
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname) || '.jpg';
    const name = `${Date.now().toString(36)}_${Math.random().toString(36).substring(2, 8)}${ext}`;
    cb(null, name);
  }
});
const upload = multer({ storage, limits: { fileSize: 10 * 1024 * 1024 } }); // 10MB

app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, '..', 'project')));
app.use('/uploads', express.static(UPLOAD_DIR));

// ===== Auth middleware =====
async function auth(req, res, next) {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token) return res.status(401).json({ error: '未登录' });
  try {
    const decoded = Buffer.from(token, 'base64').toString('utf8');
    const [userId, username, role] = decoded.split(':');
    const user = await db.getUserById(userId);
    if (!user || !user.isActive) return res.status(401).json({ error: '用户无效' });
    req.user = user;
    next();
  } catch (e) {
    return res.status(401).json({ error: '认证失败' });
  }
}

function adminOnly(req, res, next) {
  if (req.user.role !== 'admin') return res.status(403).json({ error: '需要管理员权限' });
  next();
}

// ===== Helper =====
function makeToken(user) {
  return Buffer.from(`${user.id}:${user.username}:${user.role}`).toString('base64');
}

// ===== Auth Routes =====
app.post('/api/login', async (req, res) => {
  const { username, password } = req.body;
  const user = await db.getUserByUsername(username);
  if (!user || user.password !== password || !user.isActive) {
    return res.status(401).json({ error: '用户名或密码错误' });
  }
  const token = makeToken(user);
  res.json({ token, user: { id: user.id, username: user.username, name: user.name, role: user.role, color: user.color, email: user.email, phone: user.phone } });
});

app.post('/api/logout', auth, (req, res) => {
  res.json({ success: true });
});

// ===== Upload Routes =====
app.post('/api/upload', auth, upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: '未收到文件' });
  const url = `/uploads/${req.file.filename}`;
  res.json({ url, name: req.file.originalname, size: req.file.size });
});

app.post('/api/upload/multi', auth, upload.array('files', 10), async (req, res) => {
  if (!req.files || !req.files.length) return res.status(400).json({ error: '未收到文件' });
  const urls = req.files.map(f => ({ url: `/uploads/${f.filename}`, name: f.originalname, size: f.size }));
  res.json({ urls });
});

// ===== User Routes =====
app.get('/api/users', auth, async (req, res) => {
  const users = (await db.getUsers()).map(u => ({ ...u, password: undefined }));
  res.json(users);
});

app.post('/api/users', auth, adminOnly, async (req, res) => {
  const user = req.body;
  const existing = await db.getUserByUsername(user.username);
  if (existing) return res.status(400).json({ error: '账号已存在' });
  const newUser = await db.createUser(user);
  res.status(201).json({ ...newUser, password: undefined });
});

app.put('/api/users/:id', auth, adminOnly, async (req, res) => {
  const { id } = req.params;
  const fields = req.body;
  delete fields.id;
  await db.updateUser(id, fields);
  res.json({ success: true });
});

// ===== Ticket Routes =====
app.get('/api/tickets', auth, async (req, res) => {
  const tickets = await db.getTickets();
  res.json(tickets);
});

app.get('/api/tickets/:id', auth, async (req, res) => {
  const ticket = await db.getTicketById(req.params.id);
  if (!ticket) return res.status(404).json({ error: '工单不存在' });
  res.json(ticket);
});

app.post('/api/tickets', auth, async (req, res) => {
  const ticket = req.body;
  if (!ticket.creatorId) {
    ticket.creatorId = req.user.id;
  }
  // 后端统一生成工单编号
  if (!ticket.id || !ticket.id.includes('-')) {
    ticket.id = db.generateTicketId(ticket.ticketType || 'RVC');
  }
  const newTicket = await db.createTicket(ticket);
  res.status(201).json(newTicket);
});

app.put('/api/tickets/:id', auth, async (req, res) => {
  const { id } = req.params;
  const ticket = await db.getTicketById(id);
  if (!ticket) return res.status(404).json({ error: '工单不存在' });
  // 权限：管理员、创建人、负责人可以编辑
  const isAdmin = req.user.role === 'admin';
  const isCreator = ticket.creatorId === req.user.id;
  const isEngineer = ticket.engineerId === req.user.id;
  if (!isAdmin && !isCreator && !isEngineer) {
    return res.status(403).json({ error: '无权编辑此工单' });
  }
  const fields = req.body;
  delete fields.id;
  fields.updatedAt = new Date().toISOString();
  await db.updateTicket(id, fields);
  res.json({ success: true });
});

app.delete('/api/tickets/:id', auth, async (req, res) => {
  const { id } = req.params;
  const ticket = await db.getTicketById(id);
  if (!ticket) return res.status(404).json({ error: '工单不存在' });
  // 权限：仅管理员或创建人可删除
  const isAdmin = req.user.role === 'admin';
  const isCreator = ticket.creatorId === req.user.id;
  if (!isAdmin && !isCreator) {
    return res.status(403).json({ error: '无权删除此工单' });
  }
  // 级联清理：硬删除关联的提醒
  await db.deleteRemindersByTicketId(id);
  await db.deleteTicket(id);
  res.json({ success: true });
});

app.post('/api/tickets/:id/comments', auth, async (req, res) => {
  const ticket = await db.getTicketById(req.params.id);
  if (!ticket) return res.status(404).json({ error: '工单不存在' });
  // 权限：管理员、创建人、负责人可以评论
  const isAdmin = req.user.role === 'admin';
  const isCreator = ticket.creatorId === req.user.id;
  const isEngineer = ticket.engineerId === req.user.id;
  if (!isAdmin && !isCreator && !isEngineer) {
    return res.status(403).json({ error: '无权评论此工单' });
  }
  const comment = { ...req.body, userId: req.user.id, userName: req.user.name, createdAt: new Date().toISOString() };
  ticket.comments = ticket.comments || [];
  ticket.comments.push(comment);
  await db.updateTicket(req.params.id, { comments: ticket.comments, updatedAt: new Date().toISOString() });
  res.json({ success: true });
});

// ===== Worklog Routes =====
app.get('/api/worklogs', auth, async (req, res) => {
  const worklogs = await db.getWorklogs();
  // 工程师只能看自己创建的，管理员可以看全部
  const user = req.user;
  const filtered = user.role === 'admin' ? worklogs : worklogs.filter(w => w.userId === user.id);
  res.json(filtered.sort((a, b) => new Date(b.time) - new Date(a.time)));
});

app.get('/api/worklogs/:id', auth, async (req, res) => {
  const w = await db.getWorklogById(req.params.id);
  if (!w) return res.status(404).json({ error: '记录不存在' });
  // 权限检查
  if (req.user.role !== 'admin' && w.userId !== req.user.id) {
    return res.status(403).json({ error: '无权查看此记录' });
  }
  res.json(w);
});

app.post('/api/worklogs', auth, async (req, res) => {
  const worklog = req.body;
  if (!worklog.time || !worklog.content) {
    return res.status(400).json({ error: '缺少必要字段' });
  }
  worklog.id = worklog.id || 'wl_' + Date.now().toString(36) + Math.random().toString(36).substring(2, 6);
  worklog.userId = req.user.id;
  worklog.createdAt = new Date().toISOString();
  worklog.updatedAt = new Date().toISOString();
  const newW = await db.createWorklog(worklog);
  res.status(201).json(newW);
});

app.put('/api/worklogs/:id', auth, async (req, res) => {
  const { id } = req.params;
  const w = await db.getWorklogById(id);
  if (!w) return res.status(404).json({ error: '记录不存在' });
  if (req.user.role !== 'admin' && w.userId !== req.user.id) {
    return res.status(403).json({ error: '无权编辑此记录' });
  }
  const fields = req.body;
  delete fields.id;
  fields.updatedAt = new Date().toISOString();
  await db.updateWorklog(id, fields);
  res.json({ success: true });
});

app.delete('/api/worklogs/:id', auth, async (req, res) => {
  const { id } = req.params;
  const w = await db.getWorklogById(id);
  if (!w) return res.status(404).json({ error: '记录不存在' });
  if (req.user.role !== 'admin' && w.userId !== req.user.id) {
    return res.status(403).json({ error: '无权删除此记录' });
  }
  await db.deleteWorklog(id);
  res.json({ success: true });
});

// ===== Customer Routes =====
app.get('/api/customers', auth, async (req, res) => {
  const customers = await db.getCustomers();
  res.json(customers);
});

app.get('/api/customers/:id', auth, async (req, res) => {
  const customer = await db.getCustomerById(req.params.id);
  if (!customer) return res.status(404).json({ error: '客户不存在' });
  res.json(customer);
});

app.post('/api/customers', auth, async (req, res) => {
  const customer = req.body;
  const newCustomer = await db.createCustomer(customer);
  res.status(201).json(newCustomer);
});

app.put('/api/customers/:id', auth, async (req, res) => {
  const { id } = req.params;
  const fields = req.body;
  delete fields.id;
  await db.updateCustomer(id, fields);
  res.json({ success: true });
});

app.delete('/api/customers/:id', auth, adminOnly, async (req, res) => {
  await db.deleteCustomer(req.params.id);
  res.json({ success: true });
});

// ===== Reminders =====
app.get('/api/reminders', auth, async (req, res) => {
  const list = await db.getReminders();
  res.json(list.filter(r => r.toUserId === req.user.id));
});
app.post('/api/reminders', auth, async (req, res) => {
  const reminder = { ...req.body, createdAt: new Date().toISOString(), read: false };
  const newR = await db.addReminder(reminder);
  res.status(201).json(newR);
});
app.put('/api/reminders/:id/read', auth, async (req, res) => {
  await db.markReminderRead(req.params.id);
  res.json({ success: true });
});
app.post('/api/reminders/clear', auth, async (req, res) => {
  await db.clearReminders(req.user.id);
  res.json({ success: true });
});

// ===== Stats =====
app.get('/api/stats', auth, async (req, res) => {
  const tickets = await db.getTickets();
  const users = (await db.getUsers()).filter(u => u.role === 'engineer');
  const customers = await db.getCustomers();
  const completed = tickets.filter(t => t.status === 'resolved');

  res.json({
    totalTickets: tickets.length,
    pending: tickets.filter(t => t.status === 'pending').length,
    processing: tickets.filter(t => t.status === 'processing').length,
    resolved: completed.length,
    urgent: tickets.filter(t => t.priority === 'high' && t.status !== 'resolved').length,
    engineerCount: users.length,
    customerCount: customers.length,
    engineers: users.map(u => {
      const ut = tickets.filter(t => t.engineerId === u.id);
      return {
        id: u.id,
        name: u.name,
        color: u.color,
        total: ut.length,
        resolved: ut.filter(t => t.status === 'resolved').length,
        processing: ut.filter(t => t.status === 'processing').length,
        pending: ut.filter(t => t.status === 'pending').length
      };
    })
  });
});

// ===== Export / Import =====
function toCSV(rows, headers) {
  const escape = (v) => {
    const s = v == null ? '' : String(v);
    if (s.includes(',') || s.includes('"') || s.includes('\n')) {
      return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  };
  const lines = [headers.map(h => h.label).join(',')];
  for (const row of rows) {
    lines.push(headers.map(h => escape(row[h.key])).join(','));
  }
  return '\ufeff' + lines.join('\n'); // BOM for Excel UTF-8
}

app.get('/api/export/tickets', auth, async (req, res) => {
  try {
    const tickets = await db.getTickets();
    const customers = await db.getCustomers();
    const users = await db.getUsers();
    const rows = tickets.map(t => {
      const c = customers.find(x => x.id === t.customerId);
      const u = users.find(x => x.id === t.engineerId);
      return {
        id: t.id,
        title: t.title,
        customer: c ? c.name : '',
        category: t.category || '',
        status: t.status,
        priority: t.priority,
        engineer: u ? u.name : '',
        createdAt: t.createdAt ? t.createdAt.slice(0,10) : '',
        dueDate: t.dueDate ? t.dueDate.slice(0,10) : ''
      };
    });
    const csv = toCSV(rows, [
      { key: 'id', label: '工单号' },
      { key: 'title', label: '标题' },
      { key: 'customer', label: '客户' },
      { key: 'category', label: '分类' },
      { key: 'status', label: '状态' },
      { key: 'priority', label: '优先级' },
      { key: 'engineer', label: '负责人' },
      { key: 'createdAt', label: '创建日期' },
      { key: 'dueDate', label: '截止日期' }
    ]);
    res.setHeader('Content-Disposition', `attachment; filename="tickets_${new Date().toISOString().slice(0,10)}.csv"`);
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.send(csv);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/export/customers', auth, async (req, res) => {
  try {
    const customers = await db.getCustomers();
    const rows = customers.map(c => ({
      name: c.name,
      contact: c.contact || '',
      phone: c.phone || '',
      email: c.email || '',
      industry: c.industry || '',
      level: c.level || ''
    }));
    const csv = toCSV(rows, [
      { key: 'name', label: '客户名称' },
      { key: 'contact', label: '联系人' },
      { key: 'phone', label: '电话' },
      { key: 'email', label: '邮箱' },
      { key: 'industry', label: '行业' },
      { key: 'level', label: '等级' }
    ]);
    res.setHeader('Content-Disposition', `attachment; filename="customers_${new Date().toISOString().slice(0,10)}.csv"`);
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.send(csv);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ===== Auto-close resolved tickets after 7 days =====
const AUTO_CLOSE_DAYS = 7;
const AUTO_CLOSE_MS = AUTO_CLOSE_DAYS * 24 * 60 * 60 * 1000;

async function autoCloseResolvedTickets() {
  try {
    const tickets = await db.getTickets();
    const now = Date.now();
    let closedCount = 0;
    for (const t of tickets) {
      if (t.status === 'resolved' && t.updatedAt) {
        const lastUpdate = new Date(t.updatedAt).getTime();
        if (now - lastUpdate > AUTO_CLOSE_MS) {
          await db.updateTicket(t.id, { status: 'closed', updatedAt: new Date().toISOString() });
          closedCount++;
          console.log(`[AutoClose] ${t.id} resolved→closed (last update: ${t.updatedAt})`);
        }
      }
    }
    if (closedCount > 0) {
      console.log(`[AutoClose] ${closedCount} ticket(s) auto-closed.`);
    }
  } catch (e) {
    console.error('[AutoClose] Error:', e.message);
  }
}

// ===== Start =====
app.listen(PORT, () => {
  console.log(`[CRM Server] http://localhost:${PORT}`);
  console.log(`[API Base] http://localhost:${PORT}/api`);
  console.log(`[DB] ${path.resolve(__dirname, 'data', 'crm.db')}`);
  // 启动时立即检查一次，然后每24小时检查一次
  autoCloseResolvedTickets();
  setInterval(autoCloseResolvedTickets, 24 * 60 * 60 * 1000);
});
