import { Plus, ShieldCheck, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Modal } from '../components/Modal'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import type { Role, UserStatus } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

interface ManagedUser { id: string; username: string; name: string; email?: string | null; phone?: string | null; department?: string | null; status: UserStatus; role: Role | { name: string; label: string }; createdAt?: string }

const roleLabels: Record<Role, string> = { admin: '管理员', support: '技术支持', employee: '员工', customer: '客户' }
const roleName = (user: ManagedUser): Role => (typeof user.role === 'string' ? user.role : user.role.name as Role)
const statusLabels: Record<UserStatus, string> = { PENDING: '待审批', ACTIVE: '正常', DISABLED: '已禁用' }
export function UserStatusBadge({ status }: { status: UserStatus }) {
  return <span className={`badge ${status === 'ACTIVE' ? 'ok' : status === 'PENDING' ? 'warn' : ''}`}>{statusLabels[status]}</span>
}

type Tab = '' | 'PENDING' | 'DISABLED'

export function UsersPage() {
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<ManagedUser | null>(null)
  const [resetting, setResetting] = useState<ManagedUser | null>(null)
  const [error, setError] = useState('')
  const remote = useRemote(() => api<ManagedUser[]>('/users'), [])
  if (user?.role !== 'admin') return <div className="state-page"><ShieldCheck /><strong>仅管理员可访问</strong></div>
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const all = remote.data ?? []
  const users = all.filter((item) => !tab || item.status === tab)
  const pendingCount = all.filter((item) => item.status === 'PENDING').length
  const run = async (action: () => Promise<unknown>) => { setError(''); try { await action(); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') } }
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">IDENTITY & ACCESS</span><h1>用户管理</h1><p>账号审批、停用和角色变更都由后端执行并进入审计。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增用户</button></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <div className="tabs">
      <button className={tab === '' ? 'active' : ''} onClick={() => setTab('')}>全部</button>
      <button className={tab === 'PENDING' ? 'active' : ''} onClick={() => setTab('PENDING')}>待审批{pendingCount > 0 && <span className="count-badge">{pendingCount}</span>}</button>
      <button className={tab === 'DISABLED' ? 'active' : ''} onClick={() => setTab('DISABLED')}>已禁用</button>
    </div>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>用户名</th><th>姓名</th><th>部门</th><th>角色</th><th>状态</th><th>注册时间</th><th>操作</th></tr></thead><tbody>{users.map((item) => <tr key={item.id}>
      <td className="mono">{item.username}</td><td><strong>{item.name}</strong></td><td>{item.department || '-'}</td><td>{roleLabels[roleName(item)] ?? roleName(item)}</td><td><UserStatusBadge status={item.status} /></td><td>{formatDate(item.createdAt)}</td>
      <td><div className="row-actions">
        {item.status === 'PENDING' && <><button className="button small" onClick={() => void run(() => api(`/users/${item.id}/approve`, { method: 'POST' }))}>通过</button><button className="button small" onClick={() => void run(() => api(`/users/${item.id}/reject`, { method: 'POST' }))}>拒绝</button></>}
        {item.status === 'ACTIVE' && <><button className="button small" onClick={() => setEditing(item)}>编辑</button><button className="button small" disabled={item.id === user.id} onClick={() => void run(() => api(`/users/${item.id}/disable`, { method: 'POST' }))}>禁用</button><button className="button small" onClick={() => setResetting(item)}>重置密码</button></>}
        {item.status === 'DISABLED' && <button className="button small" onClick={() => void run(() => api(`/users/${item.id}/enable`, { method: 'POST' }))}>启用</button>}
      </div></td>
    </tr>)}</tbody></table></div></section>
    {!users.length && <Empty text="暂无用户" />}
    {creating && <UserFormModal title="新增用户" onClose={() => setCreating(false)} onSubmit={async (payload) => { await api('/users', { method: 'POST', body: JSON.stringify(payload) }); setCreating(false); await remote.refresh() }} />}
    {editing && <UserFormModal title={`编辑用户：${editing.name}`} initial={editing} onClose={() => setEditing(null)} onSubmit={async (payload) => { await api(`/users/${editing.id}`, { method: 'PATCH', body: JSON.stringify(payload) }); setEditing(null); await remote.refresh() }} />}
    {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} onDone={async () => { setResetting(null); await remote.refresh() }} />}
  </div>
}

function UserFormModal({ title, initial, onClose, onSubmit }: { title: string; initial?: ManagedUser; onClose: () => void; onSubmit: (payload: Record<string, string>) => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    const payload: Record<string, string> = { name: value('name'), role: value('role') }
    if (!initial) { payload.username = value('username'); payload.password = value('password') }
    if (value('department')) payload.department = value('department')
    if (value('email')) payload.email = value('email')
    if (value('phone')) payload.phone = value('phone')
    try { await onSubmit(payload) } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  return <Modal title={title} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    {!initial && <label>账号<input name="username" required minLength={4} maxLength={30} pattern="[A-Za-z0-9_]+" /></label>}
    {!initial && <label>初始密码（至少 10 位）<input name="password" type="password" required minLength={10} /></label>}
    <label>姓名<input name="name" required defaultValue={initial?.name} /></label>
    <label>角色<select name="role" defaultValue={initial ? roleName(initial) : 'employee'}><option value="admin">管理员</option><option value="support">技术支持</option><option value="employee">员工</option></select></label>
    <label>部门<input name="department" defaultValue={initial?.department ?? ''} /></label>
    <label>邮箱<input name="email" type="email" defaultValue={initial?.email ?? ''} /></label>
    <label>手机<input name="phone" defaultValue={initial?.phone ?? ''} /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存' : '保存'}</button></div>
  </form></Modal>
}

function ResetPasswordModal({ user, onClose, onDone }: { user: ManagedUser; onClose: () => void; onDone: () => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const password = String(new FormData(event.currentTarget).get('password') ?? '')
    try { await api(`/users/${user.id}/reset-password`, { method: 'POST', body: JSON.stringify({ password }) }); await onDone() } catch (reason) { setError(reason instanceof Error ? reason.message : '重置失败') } finally { setBusy(false) }
  }
  return <Modal title={`重置密码：${user.name}`} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <label className="span-2">新密码（至少 10 位）<input name="password" type="password" required minLength={10} autoFocus /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在重置' : '确认重置'}</button></div>
  </form></Modal>
}
