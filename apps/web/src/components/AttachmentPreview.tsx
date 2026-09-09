import { Download, FileText, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Attachment } from '../types'
import './attachment-preview.css'

export function AttachmentPreview({ item }: { item: Attachment }) {
  const [open, setOpen] = useState(false)
  const [failed, setFailed] = useState(false)
  const dialog = useRef<HTMLElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const isImage = ['image/jpeg', 'image/png', 'image/webp'].includes(item.mimeType)
  const url = `/api/files/${item.id}`
  useEffect(() => {
    if (!open) return
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.current?.focus()
    return () => { document.body.style.overflow = oldOverflow; trigger.current?.focus() }
  }, [open])
  return <>
    <button ref={trigger} type="button" className="attachment-preview-trigger" aria-label={`预览 ${item.originalName}`} title={`预览 ${item.originalName}`} onClick={() => { setFailed(false); setOpen(true) }}>
      {isImage ? <img src={`${url}?preview=1`} alt={item.originalName} loading="lazy" /> : <FileText size={28} />}
      <span>{item.originalName}</span>
    </button>
    {open && createPortal(<div className="attachment-preview-backdrop" onClick={e => { e.stopPropagation(); if (e.target === e.currentTarget) setOpen(false) }}>
      <section className="attachment-preview-dialog" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label={`预览 ${item.originalName}`} onKeyDown={e => {
        if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) }
        if (e.key === 'Tab') {
          const elements = dialog.current?.querySelectorAll<HTMLElement>('a[href],button,iframe')
          if (!elements?.length) return
          const first = elements[0]; const last = elements[elements.length - 1]
          if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { e.preventDefault(); last.focus() }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
        }
      }}>
        <header><strong>{item.originalName}</strong><a className="button" href={url} download><Download size={16} />下载</a><button type="button" className="icon-button" title="关闭预览" onClick={() => setOpen(false)}><X size={20} /></button></header>
        <div className="attachment-preview-content">
          {failed ? <p role="alert">预览加载失败，请关闭后重试。</p> : isImage ? <img src={`${url}?preview=1`} alt={item.originalName} onError={() => setFailed(true)} /> : item.mimeType === 'application/pdf' ? <iframe src={`${url}?preview=1`} title={item.originalName} /> : <p>此类型暂不支持预览。</p>}
        </div>
      </section>
    </div>, document.body)}
  </>
}
