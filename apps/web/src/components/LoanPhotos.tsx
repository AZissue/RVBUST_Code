import { ImagePlus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { LoanItem, LoanPhoto } from '../types'

export const photoGroups = { VIEWS: { label: '设备六面图', max: 9 }, ACCESSORIES: { label: '配件图', max: 5 }, SERIAL: { label: '序列号图', max: 1 } } as const
export type PhotoCategory = keyof typeof photoGroups
export type PendingPhoto = { key: string; category: PhotoCategory; file: File; url: string }

export function PhotoPicker({ value, onChange, existing = [], disabled = false }: { value: PendingPhoto[]; onChange: (next: PendingPhoto[]) => void; existing?: LoanPhoto[]; disabled?: boolean }) {
  const [error, setError] = useState('')
  const add = (category: PhotoCategory, files: File[]) => {
    const count = existing.filter(p => p.photoCategory === category).length + value.filter(p => p.category === category).length
    if (count + files.length > photoGroups[category].max) { setError(`${photoGroups[category].label}最多 ${photoGroups[category].max} 张`); return }
    if (files.some(f => !['image/jpeg', 'image/png', 'image/webp'].includes(f.type) || f.size > 10 * 1024 * 1024)) { setError('请选择不超过 10 MB 的 JPG、PNG、WebP 图片'); return }
    setError(''); onChange([...value, ...files.map(file => ({ key: crypto.randomUUID(), category, file, url: URL.createObjectURL(file) }))])
  }
  return <div className="photo-groups">{(Object.keys(photoGroups) as PhotoCategory[]).map(category => <section className="photo-group" key={category}>
    <header><strong>{photoGroups[category].label}</strong><span>{value.filter(p => p.category === category).length + existing.filter(p => p.photoCategory === category).length} / {photoGroups[category].max}</span></header>
    <div className="photo-grid">
      {existing.filter(p => p.photoCategory === category).map(p => <a key={p.id} href={`/api/files/${p.id}`} target="_blank" rel="noreferrer" title={p.originalName}><img src={`/api/files/${p.id}`} alt={p.originalName} /></a>)}
      {value.filter(p => p.category === category).map(p => <div className="photo-thumb" key={p.key}><img src={p.url} alt={p.file.name} /><button type="button" className="icon-button" title={`移除 ${p.file.name}`} disabled={disabled} onClick={() => { URL.revokeObjectURL(p.url); onChange(value.filter(item => item.key !== p.key)) }}><X size={14} /></button></div>)}
      <label className="photo-add" title={`添加${photoGroups[category].label}`}><ImagePlus size={22} /><input aria-label={`上传${photoGroups[category].label}`} type="file" accept="image/jpeg,image/png,image/webp" multiple={category !== 'SERIAL'} disabled={disabled || value.filter(p => p.category === category).length + existing.filter(p => p.photoCategory === category).length >= photoGroups[category].max} onChange={e => { add(category, Array.from(e.target.files ?? [])); e.target.value = '' }} /></label>
    </div>
  </section>)}{error && <p role="alert" className="form-error">{error}</p>}</div>
}

export async function uploadLoanPhoto(itemId: string, photo: PendingPhoto) {
  const body = new FormData(); body.append('file', photo.file); body.append('category', photo.category); body.append('photoKey', photo.key)
  return api<LoanPhoto>(`/files/loan-items/${itemId}`, { method: 'POST', body })
}

export function LoanPhotoPanel({ item, onChanged }: { item: LoanItem; onChanged: () => Promise<void> }) {
  const [pending, setPending] = useState<PendingPhoto[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [uploaded, setUploaded] = useState<LoanPhoto[]>([])
  const urls = useRef<string[]>([])
  useEffect(() => { urls.current.push(...pending.map(p => p.url)) }, [pending])
  useEffect(() => () => { urls.current.forEach(url => URL.revokeObjectURL(url)) }, [])
  const existing = [...new Map([...(item.attachments ?? []), ...uploaded].map(p => [p.id, p])).values()]
  const save = async () => {
    setBusy(true); setError('')
    try {
      for (const photo of pending) {
        const saved = await uploadLoanPhoto(item.id, photo)
        setUploaded(current => [...current, saved]); setPending(current => current.filter(p => p.key !== photo.key))
      }
      await onChanged()
    } catch (e) { setError(e instanceof Error ? e.message : '上传失败，可重试剩余照片') }
    finally { setBusy(false) }
  }
  return <section className="loan-device-photos"><h3>{item.device.name} · {item.device.serialNumber || '无 SN'}</h3><PhotoPicker value={pending} onChange={setPending} existing={existing} disabled={busy} />{error && <p className="form-error">{error}</p>}{pending.length > 0 && <button type="button" className="button" disabled={busy} onClick={() => void save()}>{busy ? '上传中' : '保存照片'}</button>}</section>
}
