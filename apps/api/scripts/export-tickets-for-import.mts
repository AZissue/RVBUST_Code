/**
 * 导出本地工单为「批量导入」模板格式的 xlsx（编号由导入器按时间列自动生成 RVC-YYMMDD-NNN）。
 * 用法：cd apps/api && npx tsx scripts/export-tickets-for-import.mts
 * 输出：仓库根目录 exports/工单批量导入_第N批.xlsx（每批最多 200 行，与导入上限一致）
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { PrismaClient, TicketCategory, TicketPriority, TicketStatus } from '@prisma/client';
import ExcelJS from 'exceljs';

const CATEGORY_LABELS: Record<TicketCategory, string> = {
  PRE_SALES: '售前咨询', TRAINING: '客户培训', POINTCLOUD_DEBUG: '点云调试',
  SDK_DEVELOPMENT: 'SDK 开发', HAND_EYE_CALIBRATION: '手眼标定', HARDWARE_FAILURE: '硬件故障', OTHER: '其他', LOAN_REQUEST: '借测申请',
};
const STATUS_LABELS: Record<TicketStatus, string> = {
  PENDING: '待处理', IN_PROGRESS: '处理中', WAITING_CUSTOMER: '等待客户', WAITING_RND: '等待研发', RESOLVED: '已解决', CLOSED: '已关闭',
};
const PRIORITY_LABELS: Record<TicketPriority, string> = { LOW: '低', MEDIUM: '中', HIGH: '高', URGENT: '紧急' };
const HEADERS = ['时间', '客户公司', '问题标题', '问题描述', '问题分类', '状态', '负责人', '优先级', '相机型号', '序列号', 'SDK 版本', '系统环境', '计划完成时间', '原始记录'];
const BATCH_SIZE = 200;

const pad = (n: number) => String(n).padStart(2, '0');
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

const db = new PrismaClient();
const tickets = await db.ticket.findMany({
  where: { deletedAt: null },
  select: {
    title: true, description: true, category: true, status: true, priority: true,
    cameraModel: true, serialNumber: true, sdkVersion: true, systemEnvironment: true,
    rawText: true, plannedAt: true, createdAt: true,
    organization: { select: { name: true } },
    assignee: { select: { name: true } },
  },
  orderBy: [{ createdAt: 'asc' }, { number: 'asc' }],
});

const skipped: Array<{ title: string; reason: string }> = [];
const rows = tickets.flatMap((ticket) => {
  const description = ticket.description.trim();
  if (description.length < 3) { skipped.push({ title: ticket.title, reason: '问题描述少于 3 个字符' }); return []; }
  return [{
    '时间': ymd(ticket.createdAt),
    '客户公司': ticket.organization.name,
    '问题标题': ticket.title.trim(),
    '问题描述': description,
    '问题分类': CATEGORY_LABELS[ticket.category],
    '状态': STATUS_LABELS[ticket.status],
    '负责人': ticket.assignee?.name ?? '',
    '优先级': PRIORITY_LABELS[ticket.priority],
    '相机型号': ticket.cameraModel ?? '',
    '序列号': ticket.serialNumber ?? '',
    'SDK 版本': ticket.sdkVersion ?? '',
    '系统环境': ticket.systemEnvironment ?? '',
    '计划完成时间': ticket.plannedAt ? ymd(ticket.plannedAt) : '',
    '原始记录': ticket.rawText ?? '',
  }];
});

const outDir = resolve(process.cwd(), '../../exports');
mkdirSync(outDir, { recursive: true });
const batches: Array<typeof rows> = [];
for (let index = 0; index < rows.length; index += BATCH_SIZE) batches.push(rows.slice(index, index + BATCH_SIZE));

for (let index = 0; index < batches.length; index++) {
  const workbook = new ExcelJS.Workbook();
  const sheet = workbook.addWorksheet('工单导入');
  sheet.addRow(HEADERS);
  sheet.getRow(1).font = { bold: true };
  for (const row of batches[index]) sheet.addRow(HEADERS.map((header) => row[header as keyof typeof row]));
  HEADERS.forEach((header, i) => { sheet.getColumn(i + 1).width = Math.max(header.length * 2 + 6, 14); });
  const file = resolve(outDir, `工单批量导入_第${index + 1}批.xlsx`);
  writeFileSync(file, Buffer.from(await workbook.xlsx.writeBuffer()));
  console.log(`已生成 ${file}（${batches[index].length} 行）`);
}
console.log(`共导出 ${rows.length} 张工单，跳过 ${skipped.length} 张`);
for (const item of skipped) console.log(`  跳过：「${item.title}」——${item.reason}`);
await db.$disconnect();
