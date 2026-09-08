import { Bug, CheckCircle2, ImagePlus, Paperclip, X } from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { Modal } from '../components/Modal'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { bugStatusLabel } from '../lib/labels'
import type { Attachment, BugReport, BugStatus } from '../types'

const statusBadgeClass: Record<BugStatus, string> = { OPEN: 'status-pending', IN_PROGRESS: 'status-in_progress', FIXED: 'status-resolved' }
const filters: Array<{ key: '' | BugStatus | 'mine'; label: string }> = [
  { key: '', label: '全部' }, { key: 'OPEN', label: '待处理' }, { key: 'IN_PROGRESS', label: '修复中' }, { key: 'FIXED', label: '已修复' }, { key: 'mine', label: '我提交的' },
]

const MAX_EDGE = 1600

/** 过大图片用 canvas 等比压缩为 JPEG；小图原样返回 */
async function compressImage(file: File): Promise<File> {
  if (file.size <= 500 * 1024) return file
  const bitmap = await createImageBitmap(file).catch(() => null)
  if (!bitmap) return file
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
  if (scale >= 1 && file.size <= 1024 * 1024) { bitmap.close(); return file }
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d')
  if (!context) { bitmap.close(); return file }
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85))
  if (!blob || blob.size >= file.size) return file
  return new File([blob], file.name.replace(/\.(png|webp)$/i, '.jpg'), { type: 'image/jpeg' })
}

interface PendingImage { id: string; file: File; url: string }

/** 附件图片需带会话拉取为 blob 后本地展示（下载接口带 attachment 头，直接 <img> 会触发下载） */
function useAttachmentUrl(id: string): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    void fetch(`/api/files/${id}`)
      .then((response) => (response.ok ? response.blob() : Promise.reject(new Error('附件加载失败'))))
      .then((blob) => { if (cancelled) return; objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) })
      .catch(() => undefined)
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [id])
  return url
}

function AttachmentImage({ id, alt }: { id: string; alt: string }) {
  const url = useAttachmentUrl(id)
  if (!url) return <span className="shot-placeholder" />
  return <img src={url} alt={alt} />
}

export function BugsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [filter, setFilter] = useState<'' | BugStatus | 'mine'>('')
  const query = filter === 'mine' ? 'mine=1' : filter ? `status=${filter}` : ''
  const remote = useRemote(() => api<BugReport[]>(`/bugs${query ? `?${query}` : ''}`), [query], true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [images, setImages] = useState<PendingImage[]>([])
  const [dragging, setDragging] = useState(false)
  const [preview, setPreview] = useState<Attachment | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const addImages = async (files: Iterable<File>) => {
    const added: PendingImage[] = []
    for (const raw of files) {
      if (!raw.type.startsWith('image/')) continue
      const file = await compressImage(raw)
      added.push({ id: crypto.randomUUID(), file, url: URL.createObjectURL(file) })
    }
    if (added.length) setImages((current) => [...current, ...added])
  }

  const removeImage = (id: string) => setImages((current) => {
    const target = current.find((item) => item.id === id)
    if (target) URL.revokeObjectURL(target.url)
    return current.filter((item) => item.id !== id)
  })

  // Ctrl+V 粘贴截图（页面挂载期间生效）
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const files = [...(event.clipboardData?.items ?? [])].filter((item) => item.type.startsWith('image/')).map((item) => item.getAsFile()).filter((file): file is File => Boolean(file))
      if (files.length) { event.preventDefault(); void addImages(files) }
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [])

  const onDrop = (event: DragEvent) => {
    event.preventDefault(); setDragging(false)
    void addImages(event.dataTransfer.files)
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const formEl = event.currentTarget
    const form = new FormData(formEl)
    const title = String(form.get('title') ?? '').trim()
    const description = String(form.get('description') ?? '').trim()
    try {
      const created = await api<BugReport>('/bugs', { method: 'POST', body: JSON.stringify({ title, description }) })
      for (const image of images) {
        const body = new FormData(); body.append('file', image.file)
        await api(`/files/bugs/${created.id}`, { method: 'POST', body })
      }
      images.forEach((image) => URL.revokeObjectURL(image.url))
      setImages([]); if (fileInput.current) fileInput.current.value = ''
      formEl.reset()
      await remote.refresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '提交失败') } finally { setBusy(false) }
  }

  const markStatus = async (id: string, status: BugStatus) => {
    setError('')
    try { await api(`/bugs/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态更新失败') }
  }

  const bugs = remote.data ?? []
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">BUG TRACKER</span><h1>BUG 反馈</h1><p>所有用户都可以提交使用中遇到的问题并查看处理进度；截图支持 jpg / png / webp。</p></div></header>
    <section className="panel bug-form-panel"><div className="section-heading"><div><h2><Bug size={18} />提交 BUG</h2><p>描述你遇到的问题，可附一张截图</p></div></div>
      {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
      <form onSubmit={submit} className="stack-form">
        <label>问题标题<input name="title" required minLength={3} maxLength={240} placeholder="一句话概括问题" /></label>
        <label>问题描述<textarea name="description" required minLength={3} rows={4} placeholder="复现步骤、期望行为、实际现象等" /></label>
        <label>截图<div className={`image-dropzone ${dragging ? 'dragging' : ''}`} onClick={() => fileInput.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
            <ImagePlus size={22} />
            <span>点击上传、拖拽或粘贴图片（Ctrl+V）</span>
            <small>支持 JPG/PNG/WebP，多张，自动压缩</small>
          </div>
          <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={(event) => { void addImages(event.target.files ?? []); event.target.value = '' }} />
          {!!images.length && <div className="image-previews">{images.map((image) => <div className="image-thumb" key={image.id}><img src={image.url} alt="截图预览" /><button type="button" title="移除" onClick={() => removeImage(image.id)}><X size={12} /></button></div>)}</div>}
        </label>
        <div className="drawer-actions"><button className="button primary" disabled={busy}>{busy ? '提交中' : '提交 BUG'}</button></div>
      </form>
    </section>
    <section className="panel"><div className="section-heading"><div><h2>已提交的 BUG</h2><p>{bugs.length} 条记录</p></div>
      <div className="filter-row">{filters.map((item) => <button key={item.key} className={`chip ${filter === item.key ? 'active' : ''}`} onClick={() => setFilter(item.key)}>{item.label}</button>)}</div></div>
      <div className="relation-list">{bugs.map((bug) => <article className="relation-row bug-row" key={bug.id}>
        <div className="bug-main">
          <div className="bug-title"><span className={`badge ${statusBadgeClass[bug.status]}`}>{bugStatusLabel(bug.status)}</span><strong>{bug.title}</strong><span className="mono muted">{bug.bugNo}</span></div>
          <p className="bug-desc">{bug.description}</p>
          <div className="inline-meta"><span>{bug.author.name} 提交于 {formatDate(bug.createdAt)}</span>{bug.status === 'FIXED' && bug.resolver && <span>由 {bug.resolver.name} 修复于 {formatDate(bug.resolvedAt ?? undefined)}</span>}</div>
          {bug.attachments.some((item) => !item.mimeType.startsWith('image/')) && <div className="thumb-list">{bug.attachments.filter((item) => !item.mimeType.startsWith('image/')).map((item) => <a key={item.id} href={`/api/files/${item.id}`} target="_blank" rel="noreferrer"><Paperclip size={13} />{item.originalName}</a>)}</div>}
        </div>
        {(!!bug.attachments.length || (isAdmin && bug.status !== 'FIXED')) && <div className="bug-side">
          {!!bug.attachments.length && <div className="bug-shots">{bug.attachments.filter((item) => item.mimeType.startsWith('image/')).map((item) => <button key={item.id} className="bug-shot" title={`查看 ${item.originalName}`} onClick={() => setPreview(item)}><AttachmentImage id={item.id} alt={item.originalName} /></button>)}</div>}
          {isAdmin && bug.status !== 'FIXED' && <div className="bug-actions">
            {bug.status === 'OPEN' && <button className="button small" onClick={() => void markStatus(bug.id, 'IN_PROGRESS')}>开始修复</button>}
            <button className="button small primary" onClick={() => void markStatus(bug.id, 'FIXED')}><CheckCircle2 size={14} />标记已修复</button>
          </div>}
        </div>}
      </article>)}{!bugs.length && <div className="empty-compact">暂无 BUG 记录</div>}</div>
    </section>
    {preview && <Modal title={preview.originalName} wide onClose={() => setPreview(null)}>
      <div className="shot-view"><AttachmentImage id={preview.id} alt={preview.originalName} /></div>
    </Modal>}
  </div>
}
