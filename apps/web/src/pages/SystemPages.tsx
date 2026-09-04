import { Plus, Settings, Users } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import { PageError, PageLoading } from './DashboardPage'
import { SimpleFormModal } from './CustomersPage'
import type { WorkType } from '../types'

interface Team { id: string; name: string; description?: string; members: Array<{ user: { id: string; name: string } }> }

export function TeamsPage() {
  const [creating, setCreating] = useState(false); const remote = useRemote(() => api<Team[]>('/system/teams'), [])
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">ORGANIZATION</span><h1>团队管理</h1><p>第一阶段提供团队实体和成员关系，为后续团队数据范围预留。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增团队</button></header><section className="customer-grid">{remote.data?.map((team) => <div className="customer-row static" key={team.id}><div className="customer-monogram"><Users size={18} /></div><div className="customer-title"><strong>{team.name}</strong><span>{team.description || '暂无描述'}</span></div><span>{team.members.length} 名成员</span></div>)}</section>{creating && <SimpleFormModal title="新增团队" fields={[['name', '团队名称', true], ['description', '描述']]} onClose={() => setCreating(false)} onSubmit={async (payload) => { await api('/system/teams', { method: 'POST', body: JSON.stringify(payload) }); setCreating(false); await remote.refresh() }} />}</div>
}

export function SettingsPage() {
  const remote = useRemote(() => api<Array<{ id: string; key: string; value: Record<string, unknown>; isPublic: boolean }>>('/system/settings'), [])
  const types = useRemote(() => api<WorkType[]>('/work-types?all=1'), [])
  const [saved, setSaved] = useState('')
  const [creatingType, setCreatingType] = useState(false)
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const workspace = remote.data?.find((item) => item.key === 'workspace')
  return <div className="page-stack"><header className="page-header"><div><span className="eyebrow">SYSTEM</span><h1>系统设置</h1><p>这里只保存非敏感工作区配置；密钥和密码不会通过此页面存储。</p></div><Link className="button" to="/settings/ai"><Settings size={16} />AI 模型设置</Link></header><section className="panel settings-panel"><div className="section-heading"><div><h2><Settings size={18} />工作区</h2><p>系统显示名称和地区设置</p></div></div><form onSubmit={async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); await api('/system/settings', { method: 'PUT', body: JSON.stringify({ key: 'workspace', isPublic: true, value: { name: form.get('name'), locale: form.get('locale') } }) }); setSaved('设置已保存'); await remote.refresh() }}><label>工作区名称<input name="name" defaultValue={String(workspace?.value?.name ?? '技术支持系统 V2')} /></label><label>语言<select name="locale" defaultValue={String(workspace?.value?.locale ?? 'zh-CN')}><option value="zh-CN">简体中文</option></select></label><button className="button primary">保存设置</button>{saved && <span className="success-text">{saved}</span>}</form></section><section className="panel settings-panel"><div className="section-heading"><div><h2>工作分类</h2><p>工作事项和工作记录共用，可停用但不删除历史分类。</p></div><button className="button" onClick={() => setCreatingType(true)}><Plus size={15} />新增分类</button></div><div className="relation-list">{types.data?.map((type) => <div className="relation-row" key={type.id}><div><strong>{type.label}</strong><span className="mono">{type.code}</span></div><button className="button small" onClick={async () => { await api(`/work-types/${type.id}`, { method: 'PATCH', body: JSON.stringify({ isActive: !type.isActive }) }); await types.refresh() }}>{type.isActive ? '停用' : '启用'}</button></div>)}</div></section>{creatingType && <SimpleFormModal title="新增工作分类" fields={[["label", "分类名称", true], ["code", "分类编码（小写英文和短横线）", true], ["description", "说明"]]} onClose={() => setCreatingType(false)} onSubmit={async (payload) => { await api('/work-types', { method: 'POST', body: JSON.stringify(payload) }); setCreatingType(false); await types.refresh() }} />}</div>
}
