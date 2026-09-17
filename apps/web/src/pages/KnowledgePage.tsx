import { ArrowLeft, ChevronRight, Download, FileArchive, FileAudio, FileText, FileVideo, Folder, Pencil, RefreshCw, Save, X } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { Empty, PageError, PageLoading } from './DashboardPage'

type PreviewKind = 'image' | 'pdf' | 'text' | 'video' | 'audio' | 'none'
type Entry = { name: string; kind: 'dir' | 'file'; size: number; modifiedAt: string; previewKind: PreviewKind; editable: boolean }
type ListResult = { path: string; parent: string | null; breadcrumbs: { name: string; path: string }[]; entries: Entry[] }

const fmtSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const joinPath = (base: string, name: string) => (base ? `${base}/${name}` : name)
const qs = (path: string) => `path=${encodeURIComponent(path)}`

function EntryIcon({ entry }: { entry: Entry }) {
  if (entry.kind === 'dir') return <Folder size={17} />
  switch (entry.previewKind) {
    case 'image': return <FileText size={17} />
    case 'pdf': return <FileText size={17} />
    case 'video': return <FileVideo size={17} />
    case 'audio': return <FileAudio size={17} />
    case 'none': return <FileArchive size={17} />
    default: return <FileText size={17} />
  }
}

export function KnowledgePage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [params, setParams] = useState(() => new URLSearchParams(window.location.search))
  const currentPath = params.get('p') ?? ''
  const [preview, setPreview] = useState<Entry | null>(null)
  const [error, setError] = useState('')
  const remote = useRemote(() => api<ListResult>(`/kb/list?${qs(currentPath)}`), [currentPath], true)
  useEffect(() => {
    const onPop = () => setParams(new URLSearchParams(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = (path: string) => {
    const next = new URLSearchParams(window.location.search)
    path ? next.set('p', path) : next.delete('p')
    window.history.pushState(null, '', `${window.location.pathname}?${next.toString()}`)
    setParams(next)
  }
  const refresh = async () => { await remote.refresh() }
  const remove = async (entry: Entry) => {
    if (!window.confirm(`确认删除「${entry.name}」？\n将移入回收目录（.trash），可在服务器上恢复。`)) return
    setError('')
    try { await api('/kb/delete', { method: 'POST', body: JSON.stringify({ path: joinPath(currentPath, entry.name) }) }); await refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '删除失败') }
  }
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={refresh} />
  const data = remote.data!
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">KNOWLEDGE BASE</span><h1>知识库</h1><p>共享文档浏览与预览；内容维护请在文件系统侧整理。</p></div></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <section className="toolbar">
      <nav className="kb-breadcrumb" aria-label="目录路径">
        <button className="icon-button" title="上级目录" disabled={data.parent === null} onClick={() => data.parent !== null && navigate(data.parent)}><ArrowLeft size={16} /></button>
        <button className="kb-crumb" onClick={() => navigate('')}>根目录</button>
        {data.breadcrumbs.map((crumb) => <span key={crumb.path} className="kb-crumb-wrap"><ChevronRight size={13} /><button className={`kb-crumb ${crumb.path === data.path ? 'current' : ''}`} onClick={() => navigate(crumb.path)}>{crumb.name}</button></span>)}
      </nav>
      <button className="icon-button" type="button" title="刷新" onClick={() => void refresh()}><RefreshCw size={17} /></button>
      <span className="result-count">{data.entries.length} 个条目</span>
    </section>
    <section className="panel no-padding"><div className="table-wrap"><table>
      <thead><tr><th>名称</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead>
      <tbody>{data.entries.map((entry) => {
        const fullPath = joinPath(data.path, entry.name)
        const open = () => entry.kind === 'dir' ? navigate(fullPath) : entry.previewKind === 'none' ? window.open(`/api/kb/download?${qs(fullPath)}`, '_blank') : setPreview({ ...entry, name: entry.name })
        return <tr key={entry.name} className="clickable-row" onClick={open}>
          <td><strong className="with-icon"><EntryIcon entry={entry} />{entry.name}</strong></td>
          <td className="muted">{entry.kind === 'dir' ? '-' : fmtSize(entry.size)}</td>
          <td className="muted nowrap">{formatDate(entry.modifiedAt)}</td>
          <td><div className="row-actions" onClick={(event) => event.stopPropagation()}>
            {entry.kind === 'file' && entry.previewKind !== 'none' && <button className="button small" onClick={() => setPreview(entry)}>预览</button>}
            {entry.kind === 'file' && <a className="button small" href={`/api/kb/download?${qs(fullPath)}`} download>下载</a>}
            {isAdmin && entry.kind === 'file' && entry.previewKind === 'text' && <button className="button small" onClick={() => setPreview(entry)}>编辑</button>}
            {isAdmin && <button className="button small danger" onClick={() => void remove(entry)}>删除</button>}
          </div></td>
        </tr>
      })}</tbody>
    </table>{!data.entries.length && <Empty text="空目录" />}</div></section>
    {preview && <KbPreviewModal path={joinPath(data.path, preview.name)} entry={preview} isAdmin={isAdmin} onClose={() => setPreview(null)} onChanged={refresh} />}
  </div>
}

/** 预览/编辑弹窗：图片 iframe 视频 音频 文本（管理员可编辑） */
function KbPreviewModal({ path, entry, isAdmin, onClose, onChanged }: { path: string; entry: Entry; isAdmin: boolean; onClose: () => void; onChanged: () => Promise<unknown> }) {
  const dialog = useRef<HTMLElement>(null)
  const [failed, setFailed] = useState(false)
  const [editing, setEditing] = useState(false)
  const [content, setContent] = useState('')
  const [loadingText, setLoadingText] = useState(entry.previewKind === 'text')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.current?.focus()
    return () => { document.body.style.overflow = oldOverflow }
  }, [])
  useEffect(() => {
    if (entry.previewKind !== 'text') return
    let active = true
    setLoadingText(true)
    api<{ content: string }>(`/kb/content?${qs(path)}`).then((result) => { if (active) { setContent(result.content); setLoadingText(false) } }).catch((reason: Error) => { if (active) { setError(reason.message); setLoadingText(false) } })
    return () => { active = false }
  }, [entry.previewKind, path])
  const save = async () => {
    if (busy) return
    if (!window.confirm('确认保存？原文件将自动备份到历史目录（.history）。')) return
    setBusy(true); setError('')
    try { await api('/kb/content', { method: 'PUT', body: JSON.stringify({ path, content }) }); setEditing(false); await onChanged() } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') { event.stopPropagation(); if (!busy) onClose() }
  }
  const previewUrl = `/api/kb/preview?${qs(path)}`
  return createPortal(<div className="attachment-preview-backdrop" onClick={(event) => { event.stopPropagation(); if (event.target === event.currentTarget && !busy) onClose() }}>
    <section className="attachment-preview-dialog kb-dialog" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label={`预览 ${entry.name}`} onKeyDown={onKeyDown}>
      <header>
        <strong>{entry.name}</strong>
        <a className="button" href={`/api/kb/download?${qs(path)}`} download><Download size={16} />下载原文件</a>
        <button type="button" className="icon-button" title="关闭" onClick={onClose}><X size={20} /></button>
      </header>
      {entry.previewKind === 'text' && isAdmin && !editing && <div className="kb-edit-bar"><button className="button small" onClick={() => setEditing(true)}><Pencil size={14} />编辑</button></div>}
      {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
      <div className="attachment-preview-content">
        {failed ? <p role="alert">预览加载失败，请下载后查看。</p>
          : entry.previewKind === 'image' ? <img src={previewUrl} alt={entry.name} onError={() => setFailed(true)} />
          : entry.previewKind === 'pdf' ? <iframe src={previewUrl} title={entry.name} />
          : entry.previewKind === 'video' ? <video controls src={previewUrl} onError={() => setFailed(true)} />
          : entry.previewKind === 'audio' ? <audio controls src={previewUrl} onError={() => setFailed(true)} />
          : entry.previewKind === 'text' ? loadingText ? <p className="muted">正在加载文本…</p>
            : editing ? <textarea className="kb-editor" value={content} onChange={(event) => setContent(event.target.value)} rows={22} spellCheck={false} />
            : <pre className="kb-text">{content}</pre>
          : <p>此类型不支持预览，请下载后查看。</p>}
      </div>
      {entry.previewKind === 'text' && editing && <footer className="kb-editor-actions">
        <button className="button" disabled={busy} onClick={() => { setEditing(false); setError('') }}>取消</button>
        <button className="button primary" disabled={busy || loadingText} onClick={() => void save()}><Save size={15} />{busy ? '正在保存' : '保存修改'}</button>
      </footer>}
    </section>
  </div>, document.body)
}
