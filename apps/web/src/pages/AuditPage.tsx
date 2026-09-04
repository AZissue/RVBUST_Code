import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { Empty, PageError, PageLoading } from './DashboardPage'

interface Audit { id: string; action: string; entityType?: string; entityId?: string; ipAddress?: string; createdAt: string; actor?: { name: string; username: string } }

export function AuditPage() {
  const remote = useRemote(() => api<Audit[]>('/audit-logs'), [])
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">AUDIT TRAIL</span><h1>操作日志</h1><p>登录、退出和成功的数据变更集中留痕。</p></div></header><section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>对象 ID</th><th>IP</th></tr></thead><tbody>{remote.data?.map((item) => <tr key={item.id}><td>{formatDate(item.createdAt)}</td><td>{item.actor?.name || '系统/未知'}<small>{item.actor?.username}</small></td><td className="mono">{item.action}</td><td>{item.entityType || '-'}</td><td className="mono">{item.entityId || '-'}</td><td className="mono">{item.ipAddress || '-'}</td></tr>)}</tbody></table>{!remote.data?.length && <Empty text="暂无审计记录" />}</div></section></div>
}
