import { Plus, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { Empty, PageError, PageLoading } from './DashboardPage'
import { SimpleFormModal } from './CustomersPage'

interface ManagedUser { id: string; username: string; name: string; email?: string; phone?: string; isActive: boolean; role: { name: string; label: string }; createdAt: string }

export function UsersPage() {
  const { user } = useAuth(); const [creating, setCreating] = useState(false)
  const remote = useRemote(() => api<ManagedUser[]>('/users'), [])
  if (user?.role !== 'admin') return <div className="state-page"><ShieldCheck /><strong>仅管理员可访问</strong></div>
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">IDENTITY & ACCESS</span><h1>用户管理</h1><p>账号停用和角色变更都由后端执行并进入审计。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增用户</button></header><section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>姓名</th><th>账号</th><th>角色</th><th>邮箱</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{remote.data?.map((item) => <tr key={item.id}><td><strong>{item.name}</strong></td><td className="mono">{item.username}</td><td>{item.role.label}</td><td>{item.email || '-'}</td><td><span className={`badge ${item.isActive ? 'status-resolved' : ''}`}>{item.isActive ? '启用' : '停用'}</span></td><td>{formatDate(item.createdAt)}</td><td><button className="button small" disabled={item.id === user.id} onClick={async () => { await api(`/users/${item.id}`, { method: 'PATCH', body: JSON.stringify({ isActive: !item.isActive }) }); await remote.refresh() }}>{item.isActive ? '停用' : '启用'}</button></td></tr>)}</tbody></table></div></section>{!remote.data?.length && <Empty text="暂无用户" />}
    {creating && <SimpleFormModal title="新增用户" fields={[['username', '账号', true], ['name', '姓名', true], ['password', '初始密码（至少 10 位）', true], ['role', '角色：admin/support/employee/customer', true], ['email', '邮箱']]} onClose={() => setCreating(false)} onSubmit={async (payload) => { await api('/users', { method: 'POST', body: JSON.stringify(payload) }); setCreating(false); await remote.refresh() }} />}
  </div>
}

