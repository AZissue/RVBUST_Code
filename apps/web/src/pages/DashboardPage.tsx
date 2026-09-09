import { AlertTriangle, ArrowRight, CheckCircle2, CircleDot, Clock3, FileDown, FileUp, MessageSquare, Plus, RefreshCw, Share2, Wrench } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PriorityBadge, StatusBadge } from '../components/Status'
import { Modal } from '../components/Modal'
import { QuickTicketInput } from '../components/QuickTicketInput'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import type { Ticket, Worklog } from '../types'

interface ImportResult { created: number; failed: Array<{ row: number; customer: string; reason: string }> }

interface Summary {
  ticketCounts: { todayTodo: number; pending: number; inProgress: number; highPriority: number; waitingCustomer: number; waitingRnd: number; todayCompleted: number }
  myTickets: Ticket[]; todayWorklogs: Worklog[]
  overdueLoanCount: number; repairingCount: number
  alerts: { stale: Ticket[]; overduePlan: Ticket[]; waitingTimeout: Ticket[] }
}
export function DashboardPage() {
  const navigate = useNavigate()
  const remote = useRemote(() => api<Summary>('/dashboard'), [], true)
  const importInput = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState('')
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const runImport = async (file: File) => {
    setImporting(true); setImportError(''); setImportResult(null)
    try {
      const body = new FormData(); body.append('file', file)
      setImportResult(await api<ImportResult>('/tickets/import', { method: 'POST', body }))
      await remote.refresh()
    } catch (reason) { setImportError(reason instanceof Error ? reason.message : '导入失败') } finally { setImporting(false) }
  }
  const data = remote.data
  if (remote.loading) return <PageLoading />
  if (!data) return <PageError message={remote.error} retry={remote.refresh} />
  const c = data.ticketCounts
  const metrics: Array<[string, number, typeof CircleDot, string]> = [
    ['今日待办', c.todayTodo, CircleDot, '/my-work?status=PENDING'],
    ['待处理工单', c.pending, Clock3, '/tickets?status=PENDING'],
    ['处理中工单', c.inProgress, RefreshCw, '/my-work?status=IN_PROGRESS'],
    ['等待反馈', c.waitingCustomer + c.waitingRnd, MessageSquare, '/my-work?status=WAITING'],
    ['今日已完成', c.todayCompleted, CheckCircle2, '/my-work?status=DONE'],
    ['我的借测逾期', data.overdueLoanCount, Share2, '/loans?status=OVERDUE&mine=1'],
    ['返修进行中', data.repairingCount, Wrench, '/repairs?mine=1'],
  ]
  const alertGroups = [
    { label: '计划逾期', items: data.alerts.overduePlan, hint: (t: Ticket) => `计划完成 ${formatDate(t.plannedAt)}` },
    { label: '停滞超 3 天', items: data.alerts.stale, hint: (t: Ticket) => `最近更新 ${formatDate(t.updatedAt)}` },
    { label: '等待超时', items: data.alerts.waitingTimeout, hint: (t: Ticket) => `等待${t.status === 'WAITING_CUSTOMER' ? '客户' : '研发'} · ${formatDate(t.updatedAt)}` },
  ]
  const hasAlerts = alertGroups.some((group) => group.items.length > 0)
  return <div className="page-stack dashboard-page">
    <header className="page-header"><div><span className="eyebrow">TODAY</span><h1>今日工作台</h1></div><div className="header-actions"><a className="button" href="/api/tickets/import-template" download><FileDown size={16} />导出模版</a><button className="button" disabled={importing} onClick={() => importInput.current?.click()}><FileUp size={16} />{importing ? '导入中' : '批量导入工单'}</button><button className="button" onClick={() => void remote.refresh()}><RefreshCw size={16} />刷新</button><button className="button primary" onClick={() => navigate('/tickets?create=1')}><Plus size={16} />新建工单</button></div>
      <input ref={importInput} type="file" accept=".xlsx" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void runImport(file); event.target.value = '' }} /></header>
    {importError && <div role="alert" className="form-error">{importError}</div>}
    {remote.error && <div role="alert" className="form-error">{remote.error}</div>}
    <section className="today-overview">{metrics.map(([label, value, Icon, to]) => <Link key={label} to={to} title={`查看${label}`}><Icon size={16} /><span>{label}</span><strong>{value}</strong></Link>)}</section>
    <div className="workbench-layout"><main className="workbench-main">
      <section className="workspace-section"><div className="section-heading"><h2>我的未解决工单</h2><Link to="/my-work">我的工作<ArrowRight size={15} /></Link></div><TicketRows tickets={data.myTickets} />{!data.myTickets.length && <Empty text="当前没有未解决的工单，干得漂亮" />}</section>
      <section className="workspace-section"><div className="section-heading"><h2>需要关注</h2></div>
        {!hasAlerts && <Empty text="没有停滞、计划逾期或等待超时的工单" />}
        {alertGroups.filter((group) => group.items.length > 0).map((group) => <div className="alert-group" key={group.label}><h3>{group.label}<span>{group.items.length}</span></h3><TicketRows tickets={group.items} hint={group.hint} /></div>)}
      </section>
    </main><aside className="workbench-aside"><QuickTicketInput />
      <section className="workspace-section"><div className="section-heading"><h2>今日工作记录</h2><Link to="/worklogs">全部记录<ArrowRight size={15} /></Link></div><div className="today-timeline">{data.todayWorklogs.map((log) => <button key={log.id} onClick={() => navigate('/worklogs')}><time>{new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(log.occurredAt))}</time><i /><div><span>{log.workType.label}</span><strong>{log.summary}</strong>{(log.result || log.organization?.name) && <p>{[log.organization?.name, log.result].filter(Boolean).join(' · ')}</p>}</div></button>)}{!data.todayWorklogs.length && <Empty text="今天还没有确认记录" />}</div></section>
    </aside></div>
    {importResult && <Modal title="批量导入结果" onClose={() => setImportResult(null)}>
      <div className="import-summary">
        <p>成功创建 <strong>{importResult.created}</strong> 张工单{importResult.failed.length > 0 && <>，<span className="import-failed-count">{importResult.failed.length} 行失败</span></>}。</p>
        {!!importResult.failed.length && <div className="import-failures">{importResult.failed.map((item) => <div key={item.row}><span className="mono">第 {item.row} 行</span><span>{item.customer || '-'}</span><span className="muted">{item.reason}</span></div>)}</div>}
      </div>
    </Modal>}
  </div>
}
function TicketRows({ tickets, hint }: { tickets: Ticket[]; hint?: (ticket: Ticket) => string }) {
  const navigate = useNavigate()
  return <div className="attention-list">{tickets.map((t) => <button key={t.id} onClick={() => navigate(`/tickets/${t.id}`)}><span className="mono">{t.number}</span><div><strong>{t.title}</strong><small>{hint ? `${t.organization.name} · ${hint(t)}` : `${t.organization.name} · ${t.assignee?.name ?? '未分配'}`}</small></div><StatusBadge status={t.status} /><PriorityBadge priority={t.priority} /></button>)}</div>
}
export function PageLoading() { return <div className="state-page"><span className="spinner" />正在加载</div> }
export function PageError({ message, retry }: { message: string; retry: () => void }) { return <div className="state-page"><AlertTriangle size={24} /><strong>数据加载失败</strong><span>{message}</span><button className="button" onClick={retry}>重试</button></div> }
export function Empty({ text }: { text: string }) { return <div className="empty-compact">{text}</div> }
