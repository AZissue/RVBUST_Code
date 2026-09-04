import { Check, Clock3, Plus, Search, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { splitWorklogDrafts } from '../lib/worklog'
import type { Customer, Project, Ticket, WorkItem, Worklog, WorkType } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

export function WorklogsPage() {
  const [params, setParams] = useSearchParams()
  const [creating, setCreating] = useState(params.get('create') === '1')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const remote = useRemote(() => api<Worklog[]>('/worklogs'), [])
  useEffect(() => { if (params.get('create') === '1') setCreating(true) }, [params])
  const logs = useMemo(() => (remote.data ?? []).filter((log) => `${log.summary} ${log.workType.label} ${log.organization?.name ?? ''} ${log.result ?? ''}`.toLowerCase().includes(search.toLowerCase()) && (!status || log.status === status)), [remote.data, search, status])
  const totalMinutes = logs.filter((item) => item.status === 'CONFIRMED').reduce((sum, item) => sum + (item.durationMinutes ?? 0), 0)
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">WORK FACTS</span><h1>工作记录</h1><p>记录实际发生的工作；可关联工单、工作事项、客户或项目，也可独立存在。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />快速记录</button></header>
    <section className="metric-strip compact"><div className="metric"><Clock3 size={17} /><span>当前结果</span><strong>{logs.length} 条</strong></div><div className="metric"><Check size={17} /><span>已确认耗时</span><strong>{Math.round(totalMinutes / 6) / 10} 小时</strong></div><div className="metric"><Sparkles size={17} /><span>待确认草稿</span><strong>{(remote.data ?? []).filter((item) => item.status === 'DRAFT').length}</strong></div></section>
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索工作、分类、客户或结果" /></div><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option><option value="CONFIRMED">已确认</option><option value="DRAFT">草稿</option></select></section>
    <section className="worklog-list">{logs.map((log) => <article key={log.id}><time>{formatDate(log.occurredAt)}</time><div><header><strong>{log.summary}</strong><span className="badge">{log.workType.label}</span>{log.status === 'DRAFT' && <span className="badge priority-high">待确认</span>}</header><p>{log.actions || log.problem || log.rawText || '未填写处理过程'}</p><footer><span>{log.organization?.name || '内部工作'}</span><span>{log.ticket?.number || log.workItem?.title || log.project?.name || '独立记录'}</span><span>{log.durationMinutes ? `${log.durationMinutes} 分钟` : '未填写耗时'}</span>{log.result && <span className="result-text">结果：{log.result}</span>}<button className="icon-button danger" title="删除记录" onClick={async () => { if (window.confirm('确认删除这条工作记录？')) { await api(`/worklogs/${log.id}`, { method: 'DELETE' }); await remote.refresh() } }}><Trash2 size={14} /></button></footer></div></article>)}</section>
    {!logs.length && <Empty text="暂无工作记录" />}
    {creating && <WorklogModal initialWorkItemId={params.get('workItemId') ?? ''} onClose={() => { setCreating(false); params.delete('create'); params.delete('workItemId'); setParams(params) }} onSaved={async () => { setCreating(false); params.delete('create'); params.delete('workItemId'); setParams(params); await remote.refresh() }} />}
  </div>
}

function WorklogModal({ initialWorkItemId, onClose, onSaved }: { initialWorkItemId: string; onClose: () => void; onSaved: () => Promise<void> }) {
  const [mode, setMode] = useState<'quick' | 'structured'>(initialWorkItemId ? 'structured' : 'quick')
  const [workTypes, setWorkTypes] = useState<WorkType[]>([]); const [customers, setCustomers] = useState<Customer[]>([]); const [tickets, setTickets] = useState<Ticket[]>([]); const [workItems, setWorkItems] = useState<WorkItem[]>([]); const [projects, setProjects] = useState<Project[]>([])
  const [rawText, setRawText] = useState(() => { const value = sessionStorage.getItem('quick-capture') ?? ''; sessionStorage.removeItem('quick-capture'); return value }); const [drafts, setDrafts] = useState<string[]>([]); const [quickTypeId, setQuickTypeId] = useState('')
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { void Promise.all([api<WorkType[]>('/work-types'), api<Customer[]>('/customers'), api<Ticket[]>('/tickets'), api<WorkItem[]>('/work-items'), api<Project[]>('/projects')]).then(([types, customerRows, ticketRows, itemRows, projectRows]) => { setWorkTypes(types); setQuickTypeId(types[0]?.id ?? ''); setCustomers(customerRows); setTickets(ticketRows); setWorkItems(itemRows); setProjects(projectRows) }).catch((reason) => setError(reason instanceof Error ? reason.message : '加载关联数据失败')) }, [])
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
  const splitDrafts = () => {
    const values = splitWorklogDrafts(rawText)
    setDrafts(values.length ? values : rawText.trim() ? [rawText.trim()] : [])
  }
  const confirmQuick = async () => {
    if (!quickTypeId || !rawText.trim() || !drafts.length) { setError('请填写原始记录并生成至少一条草稿'); return }
    setBusy(true); setError('')
    try {
      const created = await api<Worklog[]>('/worklogs/drafts', { method: 'POST', body: JSON.stringify({ rawText, occurredAt: new Date().toISOString(), workTypeId: quickTypeId, summaries: drafts }) })
      await api(`/worklogs/drafts/${created[0].aiExtractionId}/confirm`, { method: 'POST' })
      await onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  const submitStructured = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError(''); const form = new FormData(event.currentTarget); const value = (key: string) => String(form.get(key) ?? '').trim()
    try { await api('/worklogs', { method: 'POST', body: JSON.stringify({ occurredAt: new Date(value('occurredAt')).toISOString(), workTypeId: value('workTypeId'), summary: value('summary'), organizationId: value('organizationId') || undefined, ticketId: value('ticketId') || undefined, workItemId: value('workItemId') || undefined, projectId: value('projectId') || undefined, problem: value('problem') || undefined, actions: value('actions') || undefined, result: value('result') || undefined, nextStep: value('nextStep') || undefined, durationMinutes: value('durationMinutes') ? Number(value('durationMinutes')) : undefined, rawText: value('rawText') || undefined, source: 'WEB' }) }); await onSaved() } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  return <Modal title="记录实际工作" onClose={onClose} wide><div className="segmented"><button className={mode === 'quick' ? 'active' : ''} onClick={() => setMode('quick')}>快速记录</button><button className={mode === 'structured' ? 'active' : ''} onClick={() => setMode('structured')}>结构化记录</button></div>
    {mode === 'quick' ? <div className="quick-capture"><label>原始工作描述<textarea rows={5} value={rawText} onChange={(event) => { setRawText(event.target.value); setDrafts([]) }} placeholder="上午完成SDK安装教程第二版，下午帮浙江智享排查M2600无点云，调整巨帧后恢复。" /></label><div className="quick-controls"><label>暂定分类<select value={quickTypeId} onChange={(event) => setQuickTypeId(event.target.value)}>{workTypes.map((type) => <option value={type.id} key={type.id}>{type.label}</option>)}</select></label><button className="button" onClick={splitDrafts}><Sparkles size={15} />生成草稿</button></div>{drafts.length > 0 && <div className="draft-review"><div><strong>确认拆分结果</strong><span>第一阶段按标点拆分，未来由 AI 提取结构化字段。</span></div>{drafts.map((draft, index) => <label key={index}>记录 {index + 1}<input value={draft} onChange={(event) => setDrafts((current) => current.map((value, position) => position === index ? event.target.value : value))} /></label>)}</div>}{error && <div className="form-error">{error}</div>}<div className="form-actions"><button className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy || !drafts.length} onClick={() => void confirmQuick()}>{busy ? '正在保存' : '确认并保存'}</button></div></div>
      : <form className="form-grid" onSubmit={submitStructured}><label className="span-2">原始文本<textarea name="rawText" rows={2} /></label><label>时间<input name="occurredAt" type="datetime-local" defaultValue={now} required /></label><label>工作分类<select name="workTypeId" required>{workTypes.map((type) => <option value={type.id} key={type.id}>{type.label}</option>)}</select></label><label>关联客户<select name="organizationId" defaultValue=""><option value="">不关联客户</option>{customers.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>关联项目<select name="projectId" defaultValue=""><option value="">不关联项目</option>{projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>关联工单<select name="ticketId" defaultValue=""><option value="">不关联工单</option>{tickets.map((item) => <option value={item.id} key={item.id}>{item.number} · {item.title}</option>)}</select></label><label>关联工作事项<select name="workItemId" defaultValue={initialWorkItemId}><option value="">不关联工作事项</option>{workItems.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label><label className="span-2">摘要<input name="summary" required /></label><label>问题<textarea name="problem" rows={3} /></label><label>处理过程<textarea name="actions" rows={3} /></label><label>结果<textarea name="result" rows={3} /></label><label>下一步<textarea name="nextStep" rows={3} /></label><label>耗时（分钟）<input name="durationMinutes" type="number" min="0" max="1440" /></label>{error && <div className="form-error span-2">{error}</div>}<div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存' : '保存记录'}</button></div></form>}
  </Modal>
}
