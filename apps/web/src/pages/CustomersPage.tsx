import { Building2, ChevronLeft, ChevronRight, Cpu, FolderKanban, Plus, Search } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import { customerLevelBadgeTitle } from '../lib/labels'
import type { Customer } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

const PAGE_SIZE = 20
const LEVEL_FILTERS = [
  { value: '', label: '全部等级' },
  { value: 'S', label: 'S 级' },
  { value: 'A', label: 'A 级' },
  { value: 'B', label: 'B 级' },
  { value: 'C', label: 'C 级' },
]

interface PagedCustomers { items: Customer[]; total: number; page: number; pageSize: number }

export function CustomersPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  // 搜索输入防抖，避免每个按键都请求
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(keyword.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [keyword])
  useEffect(() => { setPage(1) }, [search, levelFilter])
  const remote = useRemote(() => api<PagedCustomers>(`/customers?page=${page}&pageSize=${PAGE_SIZE}&search=${encodeURIComponent(search)}&level=${levelFilter}`), [page, search, levelFilter])
  if (remote.loading && !remote.data) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const data = remote.data ?? { items: [], total: 0, page: 1, pageSize: PAGE_SIZE }
  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const canManage = user?.role === 'admin' || user?.role === 'support'
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">CUSTOMER CONTEXT</span><h1>客户管理</h1><p>公司、联系人、设备和项目形成统一支持上下文。</p></div>{canManage && <button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增客户</button>}</header>
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索客户、行业或地区" /></div>
      <select className="cell-select" aria-label="按等级筛选" value={levelFilter} onChange={(event) => setLevelFilter(event.target.value)}>{LEVEL_FILTERS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
      <span className="result-count">{data.total} 家客户</span></section>
    <section className="customer-grid">{data.items.map((customer) => <button className="customer-row" key={customer.id} onClick={() => navigate(`/customers/${customer.id}`)}><div className="customer-monogram">{customer.name.slice(0, 1)}</div><div className="customer-title"><strong>{customer.name}</strong><span>{customer.industry || '未设置行业'} · {customer.region || '未设置地区'}</span></div><span className={`level level-${(customer.level ?? '').toLowerCase()}`} title={customerLevelBadgeTitle(customer)}>{customer.level || '-'}</span><div className="customer-count"><Cpu size={15} />{customer._count?.devices ?? 0} 设备</div><div className="customer-count"><FolderKanban size={15} />{customer._count?.projects ?? 0} 项目</div><div className="customer-count"><Building2 size={15} />{customer._count?.tickets ?? 0} 工单</div></button>)}</section>
    {!data.items.length && <Empty text="没有符合条件的客户" />}
    {totalPages > 1 && <div className="pager"><span className="muted">共 {data.total} 家客户</span><div className="pager-buttons"><button type="button" className="button small" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}><ChevronLeft size={14} />上一页</button><span className="muted">第 {safePage} / {totalPages} 页</span><button type="button" className="button small" disabled={safePage >= totalPages} onClick={() => setPage(safePage + 1)}>下一页<ChevronRight size={14} /></button></div></div>}
    {creating && <SimpleFormModal title="新增客户公司" fields={[['name', '公司名称', true], ['region', '地区'], ['industry', '行业'], ['notes', '备注']]} onClose={() => setCreating(false)} onSubmit={async (payload) => { await api('/customers', { method: 'POST', body: JSON.stringify(payload) }); setCreating(false); await remote.refresh() }} />}
  </div>
}

type Field = [string, string, boolean?]
export function SimpleFormModal({ title, fields, onClose, onSubmit }: { title: string; fields: Field[]; onClose: () => void; onSubmit: (payload: Record<string, string>) => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setBusy(true); setError(''); const form = new FormData(event.currentTarget); const payload = Object.fromEntries(fields.map(([key]) => [key, String(form.get(key) ?? '')]).filter(([, value]) => value)); try { await onSubmit(payload) } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) } }
  return <Modal title={title} onClose={onClose}><form className="form-grid" onSubmit={submit}>{fields.map(([key, label, required]) => <label className={key === 'notes' || key === 'application' ? 'span-2' : ''} key={key}>{label}{key === 'notes' || key === 'application' ? <textarea name={key} rows={3} required={required} /> : <input name={key} required={required} />}</label>)}{error && <div className="form-error span-2">{error}</div>}<div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存' : '保存'}</button></div></form></Modal>
}
