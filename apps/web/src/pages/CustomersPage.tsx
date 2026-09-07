import { Building2, Cpu, FolderKanban, Plus, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import type { Customer } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

export function CustomersPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const remote = useRemote(() => api<Customer[]>('/customers'), [])
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const customers = (remote.data ?? []).filter((customer) => `${customer.name} ${customer.industry ?? ''} ${customer.region ?? ''}`.toLowerCase().includes(search.toLowerCase()))
  const canManage = user?.role === 'admin' || user?.role === 'support'
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">CUSTOMER CONTEXT</span><h1>客户管理</h1><p>公司、联系人、设备和项目形成统一支持上下文。</p></div>{canManage && <button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增客户</button>}</header>
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索客户、行业或地区" /></div><span className="result-count">{customers.length} 家客户</span></section>
    <section className="customer-grid">{customers.map((customer) => <button className="customer-row" key={customer.id} onClick={() => navigate(`/customers/${customer.id}`)}><div className="customer-monogram">{customer.name.slice(0, 1)}</div><div className="customer-title"><strong>{customer.name}</strong><span>{customer.industry || '未设置行业'} · {customer.region || '未设置地区'}</span></div><span className={`level level-${customer.level?.toLowerCase()}`}>{customer.level || '-'}</span><div className="customer-count"><Cpu size={15} />{customer._count?.devices ?? 0} 设备</div><div className="customer-count"><FolderKanban size={15} />{customer._count?.projects ?? 0} 项目</div><div className="customer-count"><Building2 size={15} />{customer._count?.tickets ?? 0} 工单</div></button>)}</section>
    {!customers.length && <Empty text="没有符合条件的客户" />}
    {creating && <SimpleFormModal title="新增客户公司" fields={[['name', '公司名称', true], ['region', '地区'], ['industry', '行业'], ['level', '等级（A/B/C/D）'], ['notes', '备注']]} onClose={() => setCreating(false)} onSubmit={async (payload) => { await api('/customers', { method: 'POST', body: JSON.stringify(payload) }); setCreating(false); await remote.refresh() }} />}
  </div>
}

type Field = [string, string, boolean?]
export function SimpleFormModal({ title, fields, onClose, onSubmit }: { title: string; fields: Field[]; onClose: () => void; onSubmit: (payload: Record<string, string>) => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setBusy(true); setError(''); const form = new FormData(event.currentTarget); const payload = Object.fromEntries(fields.map(([key]) => [key, String(form.get(key) ?? '')]).filter(([, value]) => value)); try { await onSubmit(payload) } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) } }
  return <Modal title={title} onClose={onClose}><form className="form-grid" onSubmit={submit}>{fields.map(([key, label, required]) => <label className={key === 'notes' || key === 'application' ? 'span-2' : ''} key={key}>{label}{key === 'notes' || key === 'application' ? <textarea name={key} rows={3} required={required} /> : <input name={key} required={required} />}</label>)}{error && <div className="form-error span-2">{error}</div>}<div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存' : '保存'}</button></div></form></Modal>
}
