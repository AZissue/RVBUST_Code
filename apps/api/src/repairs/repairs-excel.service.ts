import { Injectable } from '@nestjs/common';
import { RepairStatus } from '@prisma/client';
import ExcelJS from 'exceljs';
import { PrismaService } from '../prisma/prisma.service.js';

const REPAIR_STATUS_LABELS: Record<RepairStatus, string> = { RECEIVED: '已收货', DIAGNOSING: '检测中', REPAIRING: '维修中', SHIPPED: '已寄回', CLOSED: '已关闭' };

@Injectable()
export class RepairsExcelService {
  constructor(private readonly prisma: PrismaService) {}

  async buildExportBuffer() {
    const orders = await this.prisma.repairOrder.findMany({
      include: { organization: { select: { name: true } }, contact: { select: { name: true } }, assignee: { select: { name: true } }, device: { select: { name: true, serialNumber: true, cameraModel: true } } },
      orderBy: { receivedAt: 'desc' },
      take: 5000,
    });
    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet('维修记录');
    sheet.columns = [
      { header: '维修单号', key: 'repairNo', width: 18 },
      { header: '客户', key: 'customer', width: 26 },
      { header: '联系人', key: 'contact', width: 12 },
      { header: '跟进工程师', key: 'assignee', width: 12 },
      { header: '设备（SN）', key: 'sn', width: 20 },
      { header: '型号', key: 'model', width: 14 },
      { header: '收货日期', key: 'receivedAt', width: 12 },
      { header: '状态', key: 'status', width: 10 },
      { header: '保内/保外', key: 'warranty', width: 10 },
      { header: '故障现象', key: 'symptom', width: 40 },
      { header: '故障原因', key: 'faultCause', width: 30 },
      { header: '处理结果', key: 'resolution', width: 30 },
      { header: '物流单号', key: 'trackingNo', width: 18 },
      { header: '寄回时间', key: 'shippedAt', width: 12 },
      { header: '关闭时间', key: 'closedAt', width: 12 },
      { header: '备注', key: 'note', width: 24 },
    ];
    for (const order of orders) {
      sheet.addRow({
        repairNo: order.repairNo,
        customer: order.organization.name,
        contact: order.contact?.name ?? '',
        assignee: order.assignee?.name ?? '',
        sn: order.serialNumber || order.device?.serialNumber || '',
        model: order.device?.cameraModel || '',
        receivedAt: order.receivedAt.toISOString().slice(0, 10),
        status: REPAIR_STATUS_LABELS[order.status],
        warranty: order.inWarranty == null ? '待判定' : order.inWarranty ? '保内' : '保外',
        symptom: order.symptom,
        faultCause: order.faultCause ?? '',
        resolution: order.resolution ?? '',
        trackingNo: order.trackingNo ?? '',
        shippedAt: order.shippedAt ? order.shippedAt.toISOString().slice(0, 10) : '',
        closedAt: order.closedAt ? order.closedAt.toISOString().slice(0, 10) : '',
        note: order.note ?? '',
      });
    }
    sheet.getRow(1).font = { bold: true };
    sheet.views = [{ state: 'frozen', ySplit: 1 }];
    sheet.autoFilter = { from: 'A1', to: { row: 1, column: sheet.columns.length } };
    return Buffer.from(await workbook.xlsx.writeBuffer());
  }
}
