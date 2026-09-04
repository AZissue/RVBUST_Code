import { ArrowLeft, Check, Pencil, Plus, RefreshCw, Save, Trash2, Zap } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import { sealApiKey } from '../lib/ai-key'
import { PageError, PageLoading } from './DashboardPage'
import './ai-settings.css'

interface Provider {
  id: string; provider: string; name: string; enabled: boolean; baseUrl: string; defaultModel: string;
  temperature: number; maxTokens: number; timeout: number; isDefault: boolean; omitTemperature: boolean;
  jsonMode: boolean; tokenParameter: string; hasApiKey: boolean; apiKeyMasked: string
}
type Draft = Omit<Provider, 'id' | 'hasApiKey' | 'apiKeyMasked'> & { apiKey?: string }
interface Feature { featureKey: string; label: string; active: boolean; useSystemDefault: boolean; providerId: string | null; model: string | null; temperature: number | null; maxTokens: number | null }
interface Usage { requestId: string; createdAt: string; user: { name: string } | null; feature: string; provider: string | null; model: string | null; success: boolean; errorType: string | null; latencyMs: number; totalTokens: number | null; attempts: number }
interface Result<T> { success: boolean; data: T; error?: string; model?: string; latencyMs: number }
const presets: Record<string, { name: string; baseUrl: string }> = { deepseek: { name: 'DeepSeek', baseUrl: 'https://api.deepseek.com' }, kimi: { name: 'Kimi / Moonshot', baseUrl: 'https://api.moonshot.ai/v1' }, openai: { name: 'OpenAI', baseUrl: 'https://api.openai.com/v1' }, 'openai-compatible': { name: 'OpenAI-Compatible', baseUrl: '' } }
const initial: Draft = { provider: 'deepseek', ...presets.deepseek, enabled: false, defaultModel: '', temperature: .1, maxTokens: 1024, timeout: 30000, isDefault: false, omitTemperature: false, jsonMode: true, tokenParameter: 'max_tokens' }
function draftOf(p: Provider): Draft { return { provider: p.provider, name: p.name, enabled: p.enabled, baseUrl: p.baseUrl, defaultModel: p.defaultModel, temperature: p.temperature, maxTokens: p.maxTokens, timeout: p.timeout, isDefault: p.isDefault, omitTemperature: p.omitTemperature, jsonMode: p.jsonMode, tokenParameter: p.tokenParameter } }
const message = (e: unknown) => e instanceof Error ? e.message : '操作失败'

export function AISettingsPage() {
  const { user } = useAuth()
  return user?.role === 'admin' ? <AISettings /> : <div role="alert">仅管理员可管理 AI 配置。</div>
}

function AISettings() {
  const remote = useRemote(async () => ({ ...(await api<{ encryptionReady: boolean; providers: Provider[] }>('/ai/providers')), features: await api<Feature[]>('/ai/features'), usage: await api<Usage[]>('/ai/usage') }), [])
  const [tab, setTab] = useState('providers'); const [editing, setEditing] = useState<Provider | 'new' | null>(null)
  const [busy, setBusy] = useState(''); const [notice, setNotice] = useState(''); const [error, setError] = useState('')
  if (remote.loading) return <PageLoading />
  if (remote.error || !remote.data) return <PageError message={remote.error || '加载失败'} retry={remote.refresh} />
  const { providers, features, usage, encryptionReady } = remote.data
  const action = async (id: string, work: () => Promise<void>) => { setBusy(id); setError(''); setNotice(''); try { await work(); await remote.refresh() } catch (e) { setError(message(e)) } finally { setBusy('') } }
  return <div className="page-stack ai-settings">
    <header className="page-header"><div><Link className="ai-back" to="/settings"><ArrowLeft size={14} />系统设置</Link><h1>AI 模型设置</h1></div><button className="button primary" onClick={() => setEditing('new')}><Plus size={16} />新增 Provider</button></header>
    {!encryptionReady && <div role="alert" className="form-error">后端加密密钥未配置，暂不能保存 API Key。</div>}
    {!providers.some((p) => p.isDefault && p.enabled) && <div role="status" className="ai-notice">尚未选择默认 AI，快速工单使用规则解析。</div>}
    {error && <div role="alert" className="form-error">{error}</div>}{notice && <div role="status" className="ai-notice">{notice}</div>}
    <div role="tablist" className="ai-tabs">{[['providers', 'AI Providers'], ['features', 'AI 功能分配'], ['usage', '调用日志']].map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>)}<button title="刷新配置" aria-label="刷新配置" className="icon-button" disabled={Boolean(busy)} onClick={() => void remote.refresh()}><RefreshCw size={16} /></button></div>
    {tab === 'providers' && <section aria-label="AI Providers" className="ai-provider-list">{providers.length === 0 && <div className="empty-state">暂无 AI Provider</div>}{providers.map((p) => <article key={p.id} className="ai-provider-row">
      <div className="ai-provider-title"><strong>{p.name}</strong><span>{presets[p.provider]?.name || p.provider}</span>{p.isDefault && <span className="ai-default"><Check size={13} />系统默认</span>}</div>
      <dl><dt>模型</dt><dd>{p.defaultModel}</dd><dt>Base URL</dt><dd>{p.baseUrl}</dd><dt>API Key</dt><dd>{p.apiKeyMasked || '未配置'}</dd></dl>
      <div className="ai-provider-actions"><label className="ai-checkbox"><input type="checkbox" aria-label={`启用 ${p.name}`} checked={p.enabled} disabled={Boolean(busy)} onChange={() => { if (p.isDefault && !window.confirm('停用后将清除默认 AI，未指定可用 Provider 的功能会降级。继续？')) return; void action(p.id, async () => { await api(`/ai/providers/${p.id}`, { method: 'PUT', body: JSON.stringify({ ...draftOf(p), enabled: !p.enabled, isDefault: p.enabled ? false : p.isDefault }) }) }) }} />{p.enabled ? '已启用' : '已停用'}</label>
        <button className="button small" disabled={Boolean(busy) || !p.hasApiKey} onClick={() => void action(p.id, async () => { const r = await api<Result<unknown>>(`/ai/providers/${p.id}/test`, { method: 'POST' }); if (!r.success) throw new Error(r.error); setNotice(`连接成功：${p.name} / ${r.model}，${r.latencyMs} ms`) })}><Zap size={14} />{busy === p.id ? '处理中' : '测试连接'}</button>
        <button className="icon-button" title={`编辑 ${p.name}`} aria-label={`编辑 ${p.name}`} disabled={Boolean(busy)} onClick={() => setEditing(p)}><Pencil size={16} /></button>
        <button className="icon-button" title={`删除 ${p.name}`} aria-label={`删除 ${p.name}`} disabled={Boolean(busy)} onClick={() => { if (window.confirm(`删除 ${p.name}？默认设置和功能关联可能失效，需要重新指定。`)) void action(p.id, async () => { await api(`/ai/providers/${p.id}`, { method: 'DELETE' }) }) }}><Trash2 size={16} /></button>
      </div>
    </article>)}</section>}
    {tab === 'features' && <section aria-label="AI 功能分配" className="ai-feature-list">{features.map((f) => <FeatureRow key={f.featureKey} feature={f} providers={providers} onSaved={remote.refresh} />)}</section>}
    {tab === 'usage' && <section aria-label="AI 调用日志" className="table-wrap"><table><thead><tr><th>时间 / 用户</th><th>功能 / 请求</th><th>Provider / 模型</th><th>状态</th><th>耗时</th><th>Tokens</th></tr></thead><tbody>{usage.map((u) => <tr key={u.requestId}><td>{new Date(u.createdAt).toLocaleString()}<small>{u.user?.name || '已删除用户'}</small></td><td>{features.find((f) => f.featureKey === u.feature)?.label || ({ connection_test: '测试连接', list_models: '模型列表' } as Record<string, string>)[u.feature] || u.feature}<small className="mono">{u.requestId}</small></td><td>{u.provider || '-'}<small>{u.model || '-'}</small></td><td>{u.success ? '成功' : u.errorType}<small>{u.attempts} 次请求</small></td><td>{u.latencyMs} ms</td><td>{u.totalTokens ?? '-'}</td></tr>)}</tbody></table>{usage.length === 0 && <div className="empty-state">暂无调用日志</div>}</section>}
    {editing && <ProviderEditor provider={editing === 'new' ? null : editing} encryptionReady={encryptionReady} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await remote.refresh() }} />}
  </div>
}

function ProviderEditor({ provider, encryptionReady, onClose, onSaved }: { provider: Provider | null; encryptionReady: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState<Draft>(provider ? draftOf(provider) : initial); const [models, setModels] = useState<string[]>([])
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => { setDraft((d) => ({ ...d, [key]: value })); if (['baseUrl', 'apiKey', 'provider'].includes(key)) setModels([]) }
  const canFetchModels = Boolean(draft.baseUrl && (draft.apiKey || (provider?.hasApiKey && draft.baseUrl.replace(/\/$/, '') === provider.baseUrl && draft.provider === provider.provider)))
  const fetchModels = async () => {
    setBusy(true); setError(''); setModels([])
    try {
      const sealedApiKey = draft.apiKey ? await sealApiKey(draft.apiKey) : undefined
      const r = await api<Result<string[]>>('/ai/models/discover', { method: 'POST', body: JSON.stringify({ provider: draft.provider, baseUrl: draft.baseUrl, sealedApiKey, providerId: provider?.id, timeout: draft.timeout }) })
      if (!r.success) throw new Error(`${r.error}；可手动填写模型名称`)
      if (!r.data.length) throw new Error('接口未返回可用模型，可手动填写模型名称')
      setModels(r.data)
    } catch (e) { setError(message(e)) } finally { setBusy(false) }
  }
  return <Modal title={provider ? '编辑 AI Provider' : '新增 AI Provider'} onClose={() => { if (!busy) onClose() }} wide><form className="ai-provider-form" onSubmit={async (event) => { event.preventDefault(); setBusy(true); setError(''); try { const { apiKey, ...values } = draft; const sealedApiKey = apiKey ? await sealApiKey(apiKey) : undefined; await api(provider ? `/ai/providers/${provider.id}` : '/ai/providers', { method: provider ? 'PUT' : 'POST', body: JSON.stringify({ ...values, sealedApiKey }) }); setDraft((d) => ({ ...d, apiKey: undefined })); await onSaved() } catch (e) { setError(message(e)) } finally { setBusy(false) } }}>
    <fieldset disabled={busy} className="form-grid">
      <label>Provider 类型<select value={draft.provider} onChange={(e) => { const provider = e.target.value; setModels([]); setDraft((d) => ({ ...d, provider, ...presets[provider], defaultModel: '', tokenParameter: provider === 'openai' ? 'max_completion_tokens' : 'max_tokens' })) }}>{Object.entries(presets).map(([key, p]) => <option key={key} value={key}>{p.name}</option>)}</select></label>
      <label>显示名称<input required maxLength={100} value={draft.name} onChange={(e) => set('name', e.target.value)} /></label>
      <label className="span-2">API Base URL<input type="url" required maxLength={500} value={draft.baseUrl} onChange={(e) => set('baseUrl', e.target.value)} /></label>
      <label className="span-2">API Key{provider?.hasApiKey ? '（已保存，留空不修改）' : ''}<input aria-label="API Key" type="password" autoComplete="new-password" maxLength={2048} disabled={!encryptionReady} value={draft.apiKey || ''} onChange={(e) => set('apiKey', e.target.value)} /></label>
      <label className="span-2">默认模型<div className="ai-model-input"><input required aria-label="默认模型" maxLength={160} value={draft.defaultModel} onChange={(e) => set('defaultModel', e.target.value)} /><button type="button" className="button" title="使用当前填写的配置获取模型，无需先保存" disabled={!canFetchModels} onClick={() => void fetchModels()}><RefreshCw size={14} />获取模型</button></div>{models.length > 0 && <select aria-label="可用模型" value={models.includes(draft.defaultModel) ? draft.defaultModel : ''} onChange={(e) => { if (e.target.value) set('defaultModel', e.target.value) }}><option value="">选择模型（{models.length}）</option>{models.map((m) => <option key={m} value={m}>{m}</option>)}</select>}</label>
      <label>Temperature<input type="number" min={0} max={2} step={.1} required value={draft.temperature} onChange={(e) => set('temperature', Number(e.target.value))} /></label>
      <label>最大输出 Token<input type="number" min={64} max={32768} required value={draft.maxTokens} onChange={(e) => set('maxTokens', Number(e.target.value))} /></label>
      <label>超时（秒）<input type="number" min={1} max={60} required value={draft.timeout / 1000} onChange={(e) => set('timeout', Number(e.target.value) * 1000)} /></label>
      <label>Token 参数<select value={draft.tokenParameter} onChange={(e) => set('tokenParameter', e.target.value)}><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>
      <div className="span-2 ai-checks"><label><input type="checkbox" checked={draft.enabled} onChange={(e) => { set('enabled', e.target.checked); if (!e.target.checked) set('isDefault', false) }} />启用</label><label><input type="checkbox" checked={draft.isDefault} disabled={!draft.enabled} onChange={(e) => set('isDefault', e.target.checked)} />系统默认 AI</label><label><input type="checkbox" checked={draft.jsonMode} onChange={(e) => set('jsonMode', e.target.checked)} />JSON 模式</label><label><input type="checkbox" checked={draft.omitTemperature} onChange={(e) => set('omitTemperature', e.target.checked)} />省略 Temperature 参数</label></div>
    </fieldset>
    {draft.enabled && <div className="ai-notice">启用后，快速工单原文及相关候选名称会发送到此服务商。请确认符合公司数据政策。</div>}
    {error && <div role="alert" className="form-error">{error}</div>}
    <div className="form-actions"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy}><Save size={15} />{busy ? '处理中' : '保存配置'}</button></div>
  </form></Modal>
}

function FeatureRow({ feature, providers, onSaved }: { feature: Feature; providers: Provider[]; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState(feature); const [busy, setBusy] = useState(false); const [status, setStatus] = useState('')
  const selected = draft.useSystemDefault ? providers.find((p) => p.isDefault) : providers.find((p) => p.id === draft.providerId)
  return <form className="ai-feature-row" onSubmit={async (event) => { event.preventDefault(); setBusy(true); setStatus(''); try { const { useSystemDefault, providerId, model, temperature, maxTokens } = draft; await api(`/ai/features/${feature.featureKey}`, { method: 'PUT', body: JSON.stringify({ useSystemDefault, providerId, model: model || null, temperature, maxTokens }) }); setStatus('已保存'); await onSaved() } catch (e) { setStatus(message(e)) } finally { setBusy(false) } }}>
    <div className="ai-feature-title"><strong>{feature.label}</strong><span>{feature.active ? '已接入' : '预留'}</span><small>{selected?.enabled ? `${selected.name} / ${draft.useSystemDefault ? selected.defaultModel : draft.model || selected.defaultModel}` : '未配置可用 Provider'}</small></div>
    <fieldset disabled={busy} className="ai-feature-fields">
      <label>Provider<select aria-label={`${feature.label} Provider`} value={draft.useSystemDefault ? 'default' : draft.providerId || ''} onChange={(e) => setDraft((d) => ({ ...d, useSystemDefault: e.target.value === 'default', providerId: e.target.value === 'default' ? null : e.target.value, model: null }))}><option value="default">使用系统默认</option><option value="" disabled>请选择 Provider</option>{providers.map((p) => <option key={p.id} value={p.id} disabled={!p.enabled}>{p.name}{!p.enabled ? '（已停用）' : ''}</option>)}</select></label>
      <label>模型<input aria-label={`${feature.label} 模型`} disabled={draft.useSystemDefault} value={draft.model || ''} placeholder={selected?.defaultModel || ''} onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value || null }))} /></label>
      <label>Temperature<input type="number" min={0} max={2} step={.1} value={draft.temperature ?? ''} placeholder="继承" onChange={(e) => setDraft((d) => ({ ...d, temperature: e.target.value === '' ? null : Number(e.target.value) }))} /></label>
      <label>输出 Token<input type="number" min={64} max={32768} value={draft.maxTokens ?? ''} placeholder="继承" onChange={(e) => setDraft((d) => ({ ...d, maxTokens: e.target.value === '' ? null : Number(e.target.value) }))} /></label>
      <button className="icon-button" title={`保存 ${feature.label}`} aria-label={`保存 ${feature.label}`}><Save size={17} /></button>
    </fieldset>{status && <div role="status" className="ai-feature-status">{status}</div>}
  </form>
}
