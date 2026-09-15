import { Injectable } from '@nestjs/common';
import { LoanStatus } from '@prisma/client';
import ExcelJS from 'exceljs';
import { PrismaService } from '../prisma/prisma.service.js';

const LOAN_STATUS_LABELS: Record<LoanStatus, string> = { QUEUED: '排队中', ONGOING: '借测中', OVERDUE: '已逾期', RETURNED: '已归还', CANCELLED: '已取消' };
const dayMs = 86400000;
const dayOf = (date: Date) => Math.floor((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) - Date.UTC(1970, 0, 1)) / dayMs);
const overdueDays = (dueAt: Date) => dayOf(new Date()) - dayOf(dueAt);

@Injectable()
export class LoansExcelService {
  constructor(private readonly prisma: PrismaService) {}

  async buildExportBuffer() {
    const orders = await this.prisma.loanOrder.findMany({
      include: { organization: { select: { name: true } }, contact: { select: { name: true } }, assignee: { select: { name: true } }, items: { include: { device: { select: { name: true, serialNumber: true, cameraModel: true } } } } },
      orderBy: { loanedAt: 'desc' },
      take: 5000,
    });
    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet('借测记录');
    sheet.columns = [
      { header: '借测单号', key: 'loanNo', width: 18 },
      { header: '客户', key: 'customer', width: 26 },
      { header: '联系人', key: 'contact', width: 12 },
      { header: '跟进工程师', key: 'assignee', width: 12 },
      { header: '设备（SN）', key: 'devices', width: 36 },
      { header: '借出日期', key: 'loanedAt', width: 12 },
      { header: '预计归还', key: 'dueAt', width: 12 },
      { header: '实际归还', key: 'returnedAt', width: 12 },
      { header: '状态', key: 'status', width: 10 },
      { header: '逾期天数', key: 'overdue', width: 10 },
      { header: '借测目的', key: 'purpose', width: 40 },
      { header: '协议编号', key: 'agreementNo', width: 16 },
      { header: '备注', key: 'note', width: 24 },
    ];
    for (const order of orders) {
      const active = order.status === LoanStatus.ONGOING || order.status === LoanStatus.OVERDUE;
      sheet.addRow({
        loanNo: order.loanNo,
        customer: order.organization.name,
        contact: order.contact?.name ?? '',
        assignee: order.assignee?.name ?? '',
        devices: order.items.map((item) => item.device.serialNumber || item.device.name).join('，'),
        loanedAt: order.loanedAt ? order.loanedAt.toISOString().slice(0, 10) : '',
        dueAt: order.dueAt ? order.dueAt.toISOString().slice(0, 10) : '',
        returnedAt: order.returnedAt ? order.returnedAt.toISOString().slice(0, 10) : '',
        status: LOAN_STATUS_LABELS[order.status],
        overdue: active && order.dueAt ? Math.max(0, overdueDays(order.dueAt)) : '',
        purpose: order.purpose,
        agreementNo: order.agreementNo ?? '',
        note: order.note ?? '',
      });
    }
    sheet.getRow(1).font = { bold: true };
    sheet.views = [{ state: 'frozen', ySplit: 1 }];
    sheet.autoFilter = { from: 'A1', to: { row: 1, column: sheet.columns.length } };

    // 统计汇总
    const active = orders.filter((o) => o.status === LoanStatus.ONGOING || o.status === LoanStatus.OVERDUE);
    const overdueList = active.filter((o) => o.dueAt && overdueDays(o.dueAt) > 0);
    const dueSoonList = active.filter((o) => o.dueAt && (() => { const d = overdueDays(o.dueAt as Date); return d >= 0 && d <= 7 })());
    const returned = orders.filter((o) => o.status === LoanStatus.RETURNED);
    const avgDays = active.length ? Math.round(active.filter((o) => o.loanedAt).reduce((sum, o) => sum + overdueDays(o.loanedAt as Date), 0) / active.length) : 0;
    const modelCount = new Map<string, number>();
    for (const o of active) for (const item of o.items) { const m = item.device.cameraModel || '未登记型号'; modelCount.set(m, (modelCount.get(m) ?? 0) + 1) }
    const topModel = [...modelCount.entries()].sort((a, b) => b[1] - a[1])[0];
    const summary = workbook.addWorksheet('统计汇总');
    summary.columns = [{ header: '指标', key: 'k', width: 20 }, { header: '数值', key: 'v', width: 24 }];
    summary.addRows([
      { k: '导出记录数', v: orders.length },
      { k: '借测中', v: active.length },
      { k: '已逾期', v: overdueList.length },
      { k: '7天内到期', v: dueSoonList.length },
      { k: '已归还', v: returned.length },
      { k: '平均借测天数（在借）', v: avgDays },
      { k: '借测最多型号', v: topModel ? `${topModel[0]}（${topModel[1]} 台）` : '-' },
    ]);
    summary.getRow(1).font = { bold: true };
    return Buffer.from(await workbook.xlsx.writeBuffer());
  }
}
