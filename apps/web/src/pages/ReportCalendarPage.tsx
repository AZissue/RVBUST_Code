import { CalendarDays, ChevronLeft, ChevronRight, Download } from 'lucide-react'
import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { StatusBadge, statusLabel } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import { ticketCategoryLabel } from '../lib/labels'
import type { TicketStatus } from '../types'
import { PageError, PageLoading } from './DashboardPage'

interface MyTicket {
  id: string; number: string; title: string; status: TicketStatus; category: string
  createdAt: string; resolvedAt: string | null; organization: { id: string; name: string }
}

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const addDays = (d: Date, n: number) => { const next = new Date(d); next.setDate(next.getDate() + n); return next }
const startOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1)
/** 周一为一周之始 */
const mondayOf = (d: Date) => addDays(d, -((d.getDay() + 6) % 7))
const WEEKDAY_NAMES = ['一', '二', '三', '四', '五', '六', '日']
const SCOPE_NAMES = { day: '日报', week: '周报', month: '月报' } as const

interface Selection { type: keyof typeof SCOPE_NAMES; date: Date }

/** 生成月视图的周行（每行周一~周日），覆盖当月前后补全的日期 */
function buildWeeks(monthFirst: Date, monthLast: Date): Date[][] {
  const firstDay = mondayOf(monthFirst);
  const weeks: Date[][] = [];
  for (let row = new Date(firstDay); row <= monthLast; row = addDays(row, 7)) {
    weeks.push(Array.from({ length: 7 }, (_, index) => addDays(row, index)));
  }
  return weeks;
}

function selectionWindow(selection: Selection, cursor: Date): { from: Date; to: Date } {
  if (selection.type === 'day') return { from: selection.date, to: addDays(selection.date, 1) };
  if (selection.type === 'week') { const monday = mondayOf(selection.date); return { from: monday, to: addDays(monday, 7) }; }
  const first = startOfMonth(cursor);
  return { from: first, to: addDays(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1), 0) };
}

function scopeTitle(selection: Selection, cursor: Date): string {
  const d = selection.date;
  if (selection.type === 'day') return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEKDAY_NAMES[(d.getDay() + 6) % 7]}`;
  if (selection.type === 'week') { const monday = mondayOf(d); const sunday = addDays(monday, 6); return `${pad(monday.getMonth() + 1)}月${pad(monday.getDate())}日 ~ ${pad(sunday.getMonth() + 1)}月${sunday.getDate()}日`; }
  return `${cursor.getFullYear()}年${cursor.getMonth() + 1}月`;
}

export function ReportCalendarPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
  const [selection, setSelection] = useState<Selection>({ type: 'day', date: new Date() });
  const monthFirst = startOfMonth(cursor);
  const monthLast = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
  const weeks = buildWeeks(monthFirst, monthLast);
  const gridFrom = weeks[0][0];
  const gridTo = addDays(weeks[weeks.length - 1][6], 1);
  const rangeKey = `${ymd(gridFrom)}_${ymd(gridTo)}`;
  const remote = useRemote(() => api<MyTicket[]>(`/dashboard/my-tickets?from=${ymd(gridFrom)}&to=${ymd(addDays(gridTo, -1))}`), [rangeKey]);
  const tickets = remote.data ?? [];
  const todayKey = ymd(new Date());

  const countOfDay = (day: Date) => tickets.reduce((sum, ticket) => sum + (ymd(new Date(ticket.createdAt)) === ymd(day) ? 1 : 0), 0);
  const shiftMonth = (offset: number) => {
    const next = new Date(cursor.getFullYear(), cursor.getMonth() + offset, 1);
    setCursor(next);
    setSelection({ type: 'month', date: next });
  };
  const goToday = () => { const now = new Date(); setCursor(startOfMonth(now)); setSelection({ type: 'day', date: now }); };

  // 选中范围（日/周/月）内的工单；选择可能落在相邻月（点格子里的补全日期），直接用窗口过滤
  const { from, to } = selectionWindow(selection, cursor);
  const inWindow = tickets.filter((ticket) => { const created = new Date(ticket.createdAt); return created >= from && created < to; });
  const activeCount = inWindow.filter((ticket) => !['RESOLVED', 'CLOSED'].includes(ticket.status)).length;
  const doneCount = inWindow.length - activeCount;
  const customerCount = new Set(inWindow.map((ticket) => ticket.organization.id)).size;

  const exportReport = () => {
    const scope = SCOPE_NAMES[selection.type];
    const lines = [
      `技术支持${scope}（${scopeTitle(selection, cursor)}）　负责人：${user?.name ?? ''}`,
      `工单 ${inWindow.length} 张：进行中 ${activeCount}，已完成 ${doneCount}，涉及客户 ${customerCount} 家`,
      '',
      ...inWindow.map((ticket, index) => `${index + 1}. ${ticket.number}　${ticket.title}　[${statusLabel(ticket.status)}]　${ticket.organization.name}`),
      '',
      '（临时文本格式，正式导出模板后续提供）',
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const anchor = document.createElement('a');
    anchor.href = URL.createObjectURL(blob);
    anchor.download = `${scope}_${ymd(from)}.txt`;
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  };

  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />;
  return (
    <div className="page-stack reports-calendar-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">REPORTS</span>
          <h1>日报 / 周报 / 月报</h1>
          <p>仅统计挂靠在我名下（我负责）的工单，点击日期、周或月查看明细并导出。</p>
        </div>
        <div className="header-actions">
          <button type="button" className="button" onClick={goToday}><CalendarDays size={15} />今天</button>
        </div>
      </header>

      <div className="reports-calendar">
        <section className="panel no-padding calendar-panel">
          <div className="calendar-head">
            <button type="button" className="icon-button" aria-label="上一月" onClick={() => shiftMonth(-1)}><ChevronLeft size={20} /></button>
            <strong>{cursor.getFullYear()} 年 {cursor.getMonth() + 1} 月</strong>
            <button type="button" className="icon-button" aria-label="下一月" onClick={() => shiftMonth(1)}><ChevronRight size={20} /></button>
          </div>
          <div className="calendar-grid">
            <span className="cal-weekday">周</span>
            {WEEKDAY_NAMES.map((name) => <span key={name} className="cal-weekday">周{name}</span>)}
            {weeks.map((week) => {
              const weekCount = week.reduce((sum, day) => sum + countOfDay(day), 0);
              const monday = week[0];
              const isSelectedWeek = selection.type === 'week' && ymd(mondayOf(selection.date)) === ymd(monday);
              return (
                <Fragment key={ymd(monday)}>
                  <button type="button" className={`cal-weekno ${isSelectedWeek ? 'selected' : ''}`} onClick={() => setSelection({ type: 'week', date: monday })}>
                    {weekCount > 0 ? `${weekCount} 单` : '—'}
                  </button>
                  {week.map((day) => {
                    const key = ymd(day);
                    const count = countOfDay(day);
                    const classes = ['cal-day'];
                    if (day.getMonth() !== cursor.getMonth()) classes.push('dim');
                    if (key === todayKey) classes.push('today');
                    if (selection.type === 'day' && ymd(selection.date) === key) classes.push('selected');
                    return (
                      <button key={key} type="button" className={classes.join(' ')} onClick={() => setSelection({ type: 'day', date: day })}>
                        <span className="cal-date">{day.getDate()}</span>
                        {count > 0 && <span className="cal-count">{count}</span>}
                      </button>
                    );
                  })}
                </Fragment>
              );
            })}
          </div>
          <div className="calendar-foot">
            <button type="button" className={`button small ${selection.type === 'month' ? 'primary' : ''}`} onClick={() => setSelection({ type: 'month', date: monthFirst })}>查看全月</button>
          </div>
        </section>

        <aside className="panel report-side">
          <div className="section-heading">
            <div>
              <h2>{SCOPE_NAMES[selection.type]} · {scopeTitle(selection, cursor)}</h2>
              <p>仅我负责的工单{remote.loading ? '，加载中…' : ''}</p>
            </div>
            <button type="button" className="button small" disabled={!inWindow.length} onClick={exportReport}><Download size={14} />导出{SCOPE_NAMES[selection.type]}</button>
          </div>
          <div className="report-stats">
            <div><span>工单</span><strong>{inWindow.length}</strong></div>
            <div><span>进行中</span><strong>{activeCount}</strong></div>
            <div><span>已完成</span><strong>{doneCount}</strong></div>
            <div><span>客户</span><strong>{customerCount}</strong></div>
          </div>
          {inWindow.length === 0 && !remote.loading && <p className="muted report-empty">该时段没有我负责的工单</p>}
          <div className="report-ticket-list">
            {inWindow.map((ticket) => (
              <button key={ticket.id} type="button" className="report-ticket" onClick={() => navigate(`/tickets/${ticket.id}`)}>
                <header>
                  <span className="mono">{ticket.number}</span>
                  <StatusBadge status={ticket.status} />
                </header>
                <strong>{ticket.title}</strong>
                <small>{ticket.organization.name} · {ticketCategoryLabel(ticket.category)} · {pad(new Date(ticket.createdAt).getMonth() + 1)}-{pad(new Date(ticket.createdAt).getDate())} {pad(new Date(ticket.createdAt).getHours())}:{pad(new Date(ticket.createdAt).getMinutes())}</small>
              </button>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
