const express = require('express');
const cors = require('cors');
const path = require('path');
const db = require('./database');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, '..', 'project')));

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
  const newTicket = await db.createTicket(ticket);
  res.status(201).json(newTicket);
});

app.put('/api/tickets/:id', auth, async (req, res) => {
  const { id } = req.params;
  const fields = req.body;
  delete fields.id;
  fields.updatedAt = new Date().toISOString();
  await db.updateTicket(id, fields);
  res.json({ success: true });
});

app.delete('/api/tickets/:id', auth, adminOnly, async (req, res) => {
  await db.deleteTicket(req.params.id);
  res.json({ success: true });
});

// ===== Ticket Comments =====
app.post('/api/tickets/:id/comments', auth, async (req, res) => {
  const ticket = await db.getTicketById(req.params.id);
  if (!ticket) return res.status(404).json({ error: '工单不存在' });
  const comment = { ...req.body, userId: req.user.id, userName: req.user.name, createdAt: new Date().toISOString() };
  ticket.comments = ticket.comments || [];
  ticket.comments.push(comment);
  await db.updateTicket(req.params.id, { comments: ticket.comments, updatedAt: new Date().toISOString() });
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

// ===== Start =====
app.listen(PORT, () => {
  console.log(`[CRM Server] http://localhost:${PORT}`);
  console.log(`[API Base] http://localhost:${PORT}/api`);
  console.log(`[DB] ${path.resolve(__dirname, 'data', 'crm.db')}`);
});
