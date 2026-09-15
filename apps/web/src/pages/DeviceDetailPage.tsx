import { ArrowLeft, ChevronRight, Cpu, Pencil, RefreshCcw, Wrench, Handshake } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { StatusBadge } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { deviceHealthLabels, deviceOwnerLabel } from '../lib/labels'
import type { Device, DeviceHealth } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'
import { DeviceFormModal, DeviceStatusBadge } from './DevicesPage'
import { LoanStatusBadge } from './LoansPage'
import { RepairStatusBadge } from './RepairsPage'

interface HistoryItem {
  kind: 'ticket' | 'loan' | 'repair'
  id: string
  number: string
  title: string
  status: string
  customerName: string
  date: string
  dueAt?: string
  href: string
}

interface DeviceDetail {
  device: Device
  stats: { loanCount: number; repairCount: number; customerCount: number; health: DeviceHealth }
  chain: { name: string; count: number }[]
  history: HistoryItem[]
}

const kindLabels: Record<HistoryItem['kind'], string> = { ticket: '工单', loan: '借测', repair: '返修' }

export function DeviceDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const remote = useRemote(() => api<DeviceDetail>(`/devices/${id}/detail`), [id], true)
  const [editing, setEditing] = useState(false)
  const canManage = user?.role === 'admin' || user?.role === 'support'
  if (remote.loading) return <PageLoading />
  if (remote.error || !remote.data) return <PageError message={remote.error} retry={remote.refresh} />
  const { device, stats, chain, history } = remote.data
  const healthLabel = deviceHealthLabels[stats.health] ?? stats.health
  const warrantyState = !device.warrantyUntil ? null : new Date(device.warrantyUntil) < new Date() ? 'expired' : new Date(device.warrantyUntil).getTime() - Date.now() < 30 * 86400000 ? 'soon' : null
  return <div className="page-stack">
    <header className="detail-header"><button className="icon-button" onClick={() => navigate('/devices')}><ArrowLeft size={20} /></button>
      <div><span className="eyebrow">设备详情</span><h1>{device.name}</h1><div className="inline-meta">
        <DeviceStatusBadge status={device.status} ownerType={device.ownerType} />
        <span className={`badge health-${stats.health.toLowerCase()}`}>{healthLabel}</span>
        <span>{deviceOwnerLabel(device.ownerType)}</span>
        <span>{device.cameraModel || device.product || '未设置型号'}</span>
        <span className="mono">{device.serialNumber || '未录入 SN'}</span>
        {device.organization && <button className="link-like" onClick={() => navigate(`/customers/${device.organization!.id}`)}>{device.organization.name}</button>}
      </div></div>
      <div className="header-actions">
        <button className="icon-button" title="刷新" onClick={() => void remote.refresh()}><RefreshCcw size={16} /></button>
        {canManage && <button className="button" onClick={() => setEditing(true)}><Pencil size={15} />编辑设备</button>}
      </div>
    </header>
    <section className="customer-summary device-summary">
      <div><span>当前状态</span><strong><DeviceStatusBadge status={device.status} ownerType={device.ownerType} /></strong></div>
      <div><span>健康度</span><strong><span className={`badge health-${stats.health.toLowerCase()}`}>{healthLabel}</span></strong></div>
      <div><span><Handshake size={12} /> 累计借测</span><strong>{stats.loanCount} 次</strong></div>
      <div><span><Wrench size={12} /> 累计维修</span><strong>{stats.repairCount} 次</strong></div>
      <div><span>服务客户数</span><strong>{stats.customerCount} 家</strong></div>
      <div className="wide"><span><Cpu size={12} /> 所属客户</span><strong>{device.organization?.name ?? '公司库存 / 未关联'}</strong></div>
    </section>
    <div className="two-columns">
      <div className="page-stack">
        <section className="panel"><div className="section-heading"><div><h2>基本信息</h2></div></div>
          <dl className="info-grid">
            <div><dt>资产编号</dt><dd className="mono">{device.assetNo || '-'}</dd></div>
            <div><dt>产品</dt><dd>{device.product || '-'}</dd></div>
            <div><dt>相机型号</dt><dd>{device.cameraModel || '-'}</dd></div>
            <div><dt>序列号</dt><dd className="mono">{device.serialNumber || '-'}</dd></div>
            <div><dt>归属</dt><dd>{deviceOwnerLabel(device.ownerType)}</dd></div>
            <div><dt>安装位置</dt><dd>{device.location || '-'}</dd></div>
            <div><dt>采购日期</dt><dd>{formatDate(device.purchaseDate)}</dd></div>
            <div><dt>保修到期</dt><dd>{formatDate(device.warrantyUntil)}{warrantyState === 'expired' ? <span className="mini-tag danger-tag">已过保</span> : warrantyState === 'soon' ? <span className="mini-tag warn-tag">即将到期</span> : null}</dd></div>
          </dl>
          {device.notes && <p className="pre-wrap muted-notes">{device.notes}</p>}
        </section>
        <section className="panel"><div className="section-heading"><div><h2>服务历史</h2><p>工单、借测、返修合并时间线（最近 50 条）</p></div></div>
          {!history.length && <Empty text="暂无服务记录" />}
          <div className="history-list">{history.map((item) => {
            const kindClass = `kind-${item.kind}`
            const statusBadge = item.kind === 'ticket'
              ? <StatusBadge status={item.status as Parameters<typeof StatusBadge>[0]['status']} />
              : item.kind === 'loan'
                ? <LoanStatusBadge status={item.status as Parameters<typeof LoanStatusBadge>[0]['status']} />
                : <RepairStatusBadge status={item.status as Parameters<typeof RepairStatusBadge>[0]['status']} />
            const body = <div className="history-row" key={`${item.kind}-${item.id}`}>
              <span className={`mini-tag ${kindClass}`}>{kindLabels[item.kind]}</span>
              <div className="history-main"><span className="mono history-no">{item.number}</span><strong>{item.title}</strong><span className="history-meta">{item.customerName || '未关联客户'} · {formatDate(item.date)}{item.kind === 'loan' && item.dueAt ? ` · 预计归还 ${formatDate(item.dueAt)}` : ''}</span></div>
              <div className="history-side">{statusBadge}<span className="history-date">{formatDate(item.date)}</span></div>
            </div>
            return item.href ? <button className="history-link" key={`${item.kind}-${item.id}`} onClick={() => navigate(item.href)}>{body}</button> : <div key={`${item.kind}-${item.id}`}>{body}</div>
          })}</div>
        </section>
      </div>
      <aside className="detail-aside">
        <section><h3>客户流转链</h3>{chain.length ? <div className="chain-list">{chain.map((node, index) => <div className="chain-node" key={`${node.name}-${index}`}>
          <span className="chain-order">{index + 1}</span>
          <div><strong>{node.name}</strong><span>{node.count} 条服务记录</span></div>
          {index < chain.length - 1 && <ChevronRight size={14} className="chain-arrow" />}
        </div>)}</div> : <p className="placeholder-text">暂无客户流转记录</p>}<p className="muted-text">按服务时间顺序展示该设备经历的客户。</p></section>
        <section><h3>健康度规则</h3><p>累计维修 ≥2 次或累计借测 ≥10 次 → 建议检查；维修 1 次或借测 ≥6 次 → 关注；否则正常。当前：<strong>{healthLabel}</strong>。</p></section>
      </aside>
    </div>
    {editing && <DeviceFormModal title={`编辑设备：${device.name}`} initial={device} onClose={() => setEditing(false)} onSubmit={async (payload) => { await api(`/devices/${device.id}`, { method: 'PATCH', body: JSON.stringify(payload) }); setEditing(false); await remote.refresh() }} />}
  </div>
}
