import { Cpu, Search } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import type { Device } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

export function DevicesPage() {
  const navigate = useNavigate(); const [search, setSearch] = useState('')
  const remote = useRemote(() => api<Device[]>('/devices'), [])
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const devices = (remote.data ?? []).filter((item) => `${item.name} ${item.cameraModel} ${item.serialNumber} ${item.organization?.name}`.toLowerCase().includes(search.toLowerCase()))
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">INSTALLED BASE</span><h1>设备管理</h1><p>按客户统一查看相机、SN、SDK 与安装位置。</p></div></header><section className="toolbar"><div className="searchbox"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索型号、SN 或客户" /></div><span className="result-count">{devices.length} 台设备</span></section><section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>设备</th><th>客户</th><th>产品</th><th>相机型号</th><th>序列号</th><th>SDK</th><th>位置</th></tr></thead><tbody>{devices.map((item) => <tr key={item.id} onClick={() => navigate(`/customers/${item.organization?.id}`)}><td><strong className="with-icon"><Cpu size={15} />{item.name}</strong></td><td>{item.organization?.name}</td><td>{item.product || '-'}</td><td>{item.cameraModel || '-'}</td><td className="mono">{item.serialNumber || '-'}</td><td>{item.sdkVersion || '-'}</td><td>{item.location || '-'}</td></tr>)}</tbody></table>{!devices.length && <Empty text="暂无设备" />}</div></section></div>
}

