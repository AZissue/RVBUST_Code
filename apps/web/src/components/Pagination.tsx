import { ChevronLeft, ChevronRight } from 'lucide-react'

/** 通用分页条：上一页/下一页 + 页码信息，数据不足一页时不渲染 */
export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= 0) return null
  return <div className="pagination-bar">
    <span className="pagination-info">共 {total} 条 · 第 {page} / {pages} 页</span>
    <div className="pagination-actions">
      <button type="button" className="button" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={15} />上一页</button>
      <button type="button" className="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页<ChevronRight size={15} /></button>
    </div>
  </div>
}
