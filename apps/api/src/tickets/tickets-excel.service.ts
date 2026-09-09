import { BadRequestException, Injectable } from '@nestjs/common';
import { TicketCategory, TicketEventType, TicketPriority, TicketStatus, Visibility, type Prisma } from '@prisma/client';
import ExcelJS from 'exceljs';
import type { AuthUser } from '../auth/auth.types.js';
import { ticketCategoryFromLabel, TICKET_CATEGORY_LABELS, TICKET_CATEGORIES } from '../common/ticket-categories.js';
import { nextSerial } from '../common/numbering.js';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';

/** 导入模板列契约（第 1 行表头，语义按表头名称识别，顺序可变） */
const COLUMNS = [
  { header: '时间', key: 'occurredAt', required: true, width: 18, comment: '工单发生/记录时间，决定工单编号日期，格式 YYYY-MM-DD' },
  { header: '客户公司', key: 'organization', required: true, width: 24, comment: '客户全称，匹配不到时自动新建' },
  { header: '问题标题', key: 'title', required: false, width: 30, comment: '留空则取问题描述前 50 字' },
  { header: '问题描述', key: 'description', required: true, width: 46, comment: '问题现象、复现步骤等' },
  { header: '问题分类', key: 'category', required: false, width: 14, comment: `下拉选择：${TICKET_CATEGORIES.map((c) => TICKET_CATEGORY_LABELS[c]).join('/')}` },
  { header: '负责人', key: 'assignee', required: false, width: 12, comment: '姓名，留空则为导入人' },
  { header: '优先级', key: 'priority', required: false, width: 10, comment: '低/中/高/紧急，留空为中' },
  { header: '相机型号', key: 'cameraModel', required: false, width: 14, comment: '如 M2600' },
  { header: '序列号', key: 'serialNumber', required: false, width: 18, comment: '设备 SN 码' },
  { header: 'SDK 版本', key: 'sdkVersion', required: false, width: 12, comment: '' },
  { header: '系统环境', key: 'systemEnvironment', required: false, width: 24, comment: 'OS/网络/运行环境' },
  { header: '计划完成时间', key: 'plannedAt', required: false, width: 18, comment: 'YYYY-MM-DD，可留空' },
  { header: '原始记录', key: 'rawText', required: false, width: 40, comment: '原始描述，原样保留' },
] as const;

type ColumnKey = (typeof COLUMNS)[number]['key'];
const HEADER_ALIASES: Record<ColumnKey, string[]> = {
  occurredAt: ['时间', '工单时间', '发生时间', '记录时间', '日期'],
  organization: ['客户公司', '客户名称', '客户', '公司名称'],
  title: ['问题标题', '标题'],
  description: ['问题描述', '描述', '详细描述', '问题详情'],
  category: ['问题分类', '分类'],
  assignee: ['负责人', '处理人', '工程师', '指派'],
  priority: ['优先级', '紧急程度'],
  cameraModel: ['相机型号', '型号', '相机'],
  serialNumber: ['序列号', 'SN', 'SN码', 'SN 码', '设备序列号'],
  sdkVersion: ['SDK 版本', 'SDK版本', 'SDK'],
  systemEnvironment: ['系统环境', '环境', '运行环境'],
  plannedAt: ['计划完成时间', '计划完成', '计划时间'],
  rawText: ['原始记录', '原始描述', '备注'],
};
const normalizeHeader = (value: unknown) => String(value ?? '').replace(/[*＊\s]/g, '');
const PRIORITY_LABELS: Record<string, TicketPriority> = { 低: TicketPriority.LOW, 中: TicketPriority.MEDIUM, 普通: TicketPriority.MEDIUM, 高: TicketPriority.HIGH, 紧急: TicketPriority.URGENT };
const MAX_ROWS = 200;

const ymdOf = (date: Date) => `${String(date.getFullYear()).slice(2)}${String(date.getMonth() + 1).padStart(2, '0')}${String(date.getDate()).padStart(2, '0')}`;

@Injectable()
export class TicketsExcelService {
  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

  /** 生成空模板：表头 + 数据验证下拉 + 示例行 + 填写说明 Sheet */
  async buildTemplateBuffer(): Promise<Buffer> {
    const workbook = new ExcelJS.Workbook();
    workbook.creator = 'Tech Support V2';
    const sheet = workbook.addWorksheet('工单导入模板');
    sheet.columns = COLUMNS.map((column) => ({ header: column.header, key: column.key, width: column.width }));
    sheet.getRow(1).font = { bold: true };
    sheet.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF2F2F2' } };
    // 日期列格式
    sheet.getColumn('occurredAt').numFmt = 'yyyy-mm-dd';
    sheet.getColumn('plannedAt').numFmt = 'yyyy-mm-dd';
    // 下拉选项（与创建表单同一白名单）；exceljs typings 未声明 dataValidations，运行时支持
    const validations = (sheet as unknown as { dataValidations: { add(range: string, rule: Record<string, unknown>): void } }).dataValidations;
    const lastRow = String(MAX_ROWS + 1);
    validations.add(`E2:E${lastRow}`, {
      type: 'list', allowBlank: true, showErrorMessage: true,
      formulae: [`"${TICKET_CATEGORIES.map((c) => TICKET_CATEGORY_LABELS[c]).join(',')}"`],
      errorTitle: '问题分类', error: `请选择：${TICKET_CATEGORIES.map((c) => TICKET_CATEGORY_LABELS[c]).join('/')}`,
    });
    validations.add(`G2:G${lastRow}`, { type: 'list', allowBlank: true, showErrorMessage: true, formulae: ['"低,中,高,紧急"'] });
    // 日期校验：桌面版 Excel 靠日期格式+校验约束输入；Excel 网页版/手机版点击单元格会出现日历选择器
    // 注意：exceljs 写 date 校验公式时会 new Date(formula) 再转序列号，所以必须传 Date 对象而不是序列号数字
    validations.add(`A2:A${lastRow}`, {
      type: 'date', operator: 'between', allowBlank: false, showInputMessage: true,
      formulae: [new Date(2020, 0, 1), new Date(2100, 11, 31)],
      promptTitle: '时间', prompt: '决定工单编号日期（RVC-YYMMDD-NNN）；Excel 网页版/手机版点击本单元格会出现日历选择；桌面版请按 YYYY-MM-DD 输入',
      showErrorMessage: true, errorTitle: '时间格式', error: '请输入有效日期，如 2026-09-08',
    });
    validations.add(`L2:L${lastRow}`, {
      type: 'date', operator: 'between', allowBlank: true, showErrorMessage: true,
      formulae: [new Date(2020, 0, 1), new Date(2100, 11, 31)],
      errorTitle: '计划完成时间', error: '请输入有效日期，如 2026-09-30',
    });
    // 示例行（导入时整行忽略）
    const example = sheet.getRow(2);
    example.values = ['2026-09-08', '示例客户公司（示例行，导入时自动忽略）', 'M2600 连接超时（示例，请删除本行）', '相机通电后网络搜索不到设备，已换网线复现（示例）', '硬件故障', '', '高', 'M2600', 'SN123456', 'RVC 2.8', 'Windows 11 / 千兆网', '', ''];
    example.eachCell((cell) => { cell.font = { color: { argb: 'FF979797' }, italic: true }; });

    const guide = workbook.addWorksheet('填写说明');
    guide.columns = [{ width: 16 }, { width: 10 }, { width: 60 }];
    guide.addRow(['列名', '必填', '说明']);
    guide.getRow(1).font = { bold: true };
    for (const column of COLUMNS) guide.addRow([column.header, column.required ? '是' : '否', column.comment]);
    guide.addRow([]);
    guide.addRow(['规则', '', `每张工单占一行，最多 ${MAX_ROWS} 行；表头名称自动识别（顺序可调）；时间列决定工单编号（RVC-YYMMDD-NNN）；客户名称匹配不到时自动新建客户。`]);
    return Buffer.from(await workbook.xlsx.writeBuffer());
  }

  /** 解析 Excel 并逐行建单：成功行落库，失败行收集原因，整体返回汇总 */
  async importBuffer(user: AuthUser, buffer: Buffer) {
    if (buffer.length > 2 * 1024 * 1024) throw new BadRequestException('文件不能超过 2MB');
    let workbook: ExcelJS.Workbook;
    try { workbook = await new ExcelJS.Workbook().xlsx.load(buffer as unknown as ExcelJS.Buffer); }
    catch { throw new BadRequestException('文件解析失败，请使用系统导出的 xlsx 模板'); }
    const sheet = workbook.worksheets[0];
    if (!sheet) throw new BadRequestException('Excel 中没有工作表');

    // 表头识别：按别名归一化匹配
    const headerRow = sheet.getRow(1);
    const columnIndex = new Map<ColumnKey, number>();
    headerRow.eachCell({ includeEmpty: false }, (cell, columnNumber) => {
      const header = normalizeHeader(cell.text || cell.value);
      for (const column of COLUMNS) {
        if (columnIndex.has(column.key)) continue;
        if (HEADER_ALIASES[column.key].some((alias) => normalizeHeader(alias) === header)) columnIndex.set(column.key, columnNumber);
      }
    });
    const missing = COLUMNS.filter((column) => column.required && !columnIndex.has(column.key)).map((column) => column.header);
    if (missing.length) throw new BadRequestException(`表头缺少必填列：${missing.join('、')}。请使用系统导出的最新模板`);

    const failures: Array<{ row: number; customer: string; reason: string }> = [];
    const orgCache = new Map<string, Promise<string>>();
    const assigneeCache = new Map<string, string | null>();
    const serialCache = new Map<string, string | null>();
    let created = 0;

    const text = (row: ExcelJS.Row, key: ColumnKey): string => {
      const index = columnIndex.get(key);
      if (!index) return '';
      const cell = row.getCell(index);
      if (cell.value instanceof Date) return cell.value.toISOString();
      return (cell.text ?? '').trim();
    };
    const dateCell = (row: ExcelJS.Row, key: ColumnKey): Date | null => {
      const index = columnIndex.get(key);
      if (!index) return null;
      const cell = row.getCell(index);
      const value = cell.value;
      if (value == null || value === '') return null;
      // Excel 日期单元格（cellDates 加载后通常为 Date）
      if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
      // Excel 序列值（1899-12-30 起算）
      if (typeof value === 'number') {
        const parsed = new Date(Date.UTC(1899, 11, 30) + value * 86400000);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
      }
      const raw = (cell.text ?? '').trim();
      let match = raw.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?/);
      if (match) return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4] ?? 0), Number(match[5] ?? 0));
      match = raw.match(/^(\d{2})(\d{2})(\d{2})$/);
      if (match) return new Date(2000 + Number(match[1]), Number(match[2]) - 1, Number(match[3]));
      const fallback = new Date(raw);
      return Number.isNaN(fallback.getTime()) ? null : fallback;
    };
    const getOrgId = (name: string) => {
      let pending = orgCache.get(name);
      if (!pending) {
        pending = (async () => {
          const existing = await this.prisma.customerOrganization.findFirst({ where: { name: { equals: name, mode: 'insensitive' } }, select: { id: true } });
          if (existing) return existing.id;
          const createdOrg = await this.prisma.customerOrganization.create({ data: { name, notes: 'Excel 批量导入创建' } });
          return createdOrg.id;
        })();
        orgCache.set(name, pending);
      }
      return pending;
    };
    const resolveAssignee = async (name: string): Promise<string | null> => {
      if (!name) return null;
      if (!assigneeCache.has(name)) {
        const found = await this.prisma.user.findFirst({ where: { name: { equals: name, mode: 'insensitive' }, status: 'ACTIVE' }, select: { id: true } });
        assigneeCache.set(name, found?.id ?? null);
      }
      return assigneeCache.get(name) ?? null;
    };
    const nextNumber = async (occurredAt: Date) => {
      const prefix = `RVC-${ymdOf(occurredAt)}-`;
      const cached = serialCache.get(prefix);
      if (cached !== undefined) { const next = nextSerial(cached, prefix); serialCache.set(prefix, next); return next; }
      const last = await this.prisma.ticket.findFirst({ where: { number: { startsWith: prefix } }, orderBy: { number: 'desc' }, select: { number: true } });
      const next = nextSerial(last?.number ?? null, prefix);
      serialCache.set(prefix, next);
      return next;
    };

    for (let rowNumber = 2; rowNumber <= Math.min(sheet.rowCount, MAX_ROWS + 1); rowNumber++) {
      const row = sheet.getRow(rowNumber);
      const rawText = text(row, 'rawText');
      // 整行空白跳过；示例行（客户列含"示例"提示）跳过
      const isBlank = [...columnIndex.values()].every((index) => row.getCell(index).value == null || String(row.getCell(index).value).trim() === '');
      if (isBlank) continue;
      const customerName = text(row, 'organization');
      if (customerName.includes('示例')) continue;
      const fail = (reason: string) => failures.push({ row: rowNumber, customer: customerName, reason });

      const occurredAt = dateCell(row, 'occurredAt');
      if (!occurredAt) { fail('时间无效，支持 YYYY-MM-DD、YYYY/M/D 或 YYMMDD'); continue; }
      if (!customerName) { fail('客户公司为空'); continue; }
      const description = text(row, 'description');
      if (description.length < 3) { fail('问题描述为空或过短'); continue; }
      const title = text(row, 'title') || description.slice(0, 50);
      const categoryLabel = text(row, 'category');
      const category: TicketCategory = categoryLabel ? ticketCategoryFromLabel(categoryLabel) : TicketCategory.OTHER;
      if (categoryLabel && category === TicketCategory.OTHER && categoryLabel !== TICKET_CATEGORY_LABELS.OTHER) { fail(`问题分类「${categoryLabel}」无法识别，请用模板下拉选项`); continue; }
      const priorityLabel = text(row, 'priority');
      const priority = priorityLabel ? PRIORITY_LABELS[priorityLabel] : undefined;
      if (priorityLabel && !priority) { fail(`优先级「${priorityLabel}」无效，可选：低/中/高/紧急`); continue; }
      const assigneeName = text(row, 'assignee');
      const assigneeId = await resolveAssignee(assigneeName);
      if (assigneeName && !assigneeId) { fail(`负责人「${assigneeName}」不存在`); continue; }
      const plannedAt = dateCell(row, 'plannedAt');

      const organizationId = await getOrgId(customerName);
      try {
        for (let attempt = 0; attempt < 4; attempt++) {
          try {
            const ticket = await this.prisma.ticket.create({
              data: {
                number: await nextNumber(occurredAt), title: title.slice(0, 240), description, category,
                priority: priority ?? TicketPriority.MEDIUM,
                cameraModel: text(row, 'cameraModel') || undefined,
                serialNumber: text(row, 'serialNumber') || undefined,
                sdkVersion: text(row, 'sdkVersion') || undefined,
                systemEnvironment: text(row, 'systemEnvironment') || undefined,
                rawText: rawText || undefined,
                plannedAt: plannedAt ?? undefined,
                createdAt: occurredAt,
                status: TicketStatus.PENDING,
                organization: { connect: { id: organizationId } },
                createdBy: { connect: { id: user.id } },
                assignee: { connect: { id: assigneeId ?? user.id } },
                events: { create: { author: { connect: { id: user.id } }, type: TicketEventType.WORK_RECORD, visibility: Visibility.INTERNAL, content: '工单已创建（Excel 批量导入）' } },
              },
              select: { id: true, number: true, assigneeId: true },
            });
            created++;
            if (ticket.assigneeId && ticket.assigneeId !== user.id) {
              await this.notifications.notify({
                recipientId: ticket.assigneeId, ticketId: ticket.id, type: NOTIFICATION_TYPES.TICKET_ASSIGNED,
                title: '工单已指派给你', body: `工单 ${ticket.number} 已指派给你处理。`, dedupeKey: `ticket-assign:${ticket.id}:${ticket.assigneeId}`,
              });
            }
            break;
          } catch (error) {
            if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error;
          }
        }
      } catch (error) {
        if ((error as { code?: string }).code === 'P2002') fail('工单编号冲突，请重新导入');
        else throw error;
      }
    }
    return { created, failed: failures };
  }
}
