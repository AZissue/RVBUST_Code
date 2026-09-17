import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import { DeviceOwnerType, DeviceSource, DeviceStatus, FollowUpSource, LoanStatus, Prisma, RepairStatus, Visibility } from '@prisma/client';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, unlink, writeFile } from 'node:fs/promises';
import { basename, extname, resolve } from 'node:path';
import { dateSerialPrefix, nextSerial } from '../common/numbering.js';
import { PrismaService } from '../prisma/prisma.service.js';

type FlowFollowup = { id: string; person?: string; date?: string; text?: string; source?: string };
type FlowRecord = Record<string, unknown> & {
  id: string;
  type?: string;
  photos?: Record<string, unknown>;
  agreement?: { name?: string; data?: unknown } | null;
  followUps?: FlowFollowup[];
};
type FlowDevice = Record<string, unknown> & { id: string };
type FlowState = {
  records: FlowRecord[];
  devices: FlowDevice[];
  recycle: { records: FlowRecord[]; devices: FlowDevice[] };
  settings: Record<string, unknown>;
};

/** 快照/同步共用的附件行结构（Attachment 表，photoKey 指向 html_flow_files.id） */
type AttachmentRow = {
  id: string;
  loanItemId: string | null;
  repairOrderId: string | null;
  photoCategory: string | null;
  photoSlot: number | null;
  photoKey: string | null;
  originalName: string;
};

const emptyState = (): FlowState => ({ records: [], devices: [], recycle: { records: [], devices: [] }, settings: {} });
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const asText = (value: unknown) => typeof value === 'string' ? value : '';
const storedFileId = (value: unknown) => typeof value === 'string' ? /^\/api\/html-device-flow\/files\/([a-f0-9-]{36})$/i.exec(value)?.[1]?.toLowerCase() : undefined;
/** 从 'R-<uuid>' / 'D-<uuid>' / 'FU-<uuid>' 形态解析出关系行主键；前端新生成 id 不命中（随机串非 uuid） */
const flowRowUuid = (id: string, prefix: 'R' | 'D' | 'FU') =>
  new RegExp(`^${prefix}-([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$`, 'i').exec(id)?.[1]?.toLowerCase();
function decodedUploadName(value: string) {
  if (/[^\u0000-\u00ff]/.test(value)) return value;
  try { return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.from(value, 'latin1')); }
  catch { return value; }
}

const pad2 = (value: number) => String(value).padStart(2, '0');
const fmtYmd = (value: Date | null | undefined) => value ? `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}` : '';
const fmtYmdhms = (value: Date | null | undefined) => value ? `${fmtYmd(value)} ${pad2(value.getHours())}:${pad2(value.getMinutes())}:${pad2(value.getSeconds())}` : '';
const parseDate = (value: unknown): Date | null => {
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const LOAN_STATUS_TO_LABEL: Record<LoanStatus, string> = {
  [LoanStatus.QUEUED]: '借测中', [LoanStatus.ONGOING]: '借测中', [LoanStatus.OVERDUE]: '借测中',
  [LoanStatus.RETURNED]: '已归还', [LoanStatus.CANCELLED]: '已归还',
};
const REPAIR_STATUS_TO_LABEL: Record<RepairStatus, string> = {
  [RepairStatus.RECEIVED]: '待寄回', [RepairStatus.DIAGNOSING]: '维修中',
  [RepairStatus.REPAIRING]: '维修中', [RepairStatus.SHIPPED]: '维修中', [RepairStatus.CLOSED]: '已完成',
};
const DEVICE_OWNERSHIP_TO_LABEL: Record<DeviceOwnerType, string> = {
  [DeviceOwnerType.COMPANY]: '公司资产', [DeviceOwnerType.CUSTOMER]: '客户设备',
};
const DEVICE_STATUS_TO_LABEL: Record<DeviceStatus, string> = {
  [DeviceStatus.IN_STOCK]: '在库', [DeviceStatus.RETIRED]: '在库',
  [DeviceStatus.LOANED]: '借测中', [DeviceStatus.REPAIRING]: '维修中',
};
/** 页面状态 → 关系库状态（页面仅两种借测态，其余一律按进行中处理） */
const loanStatusFromLabel = (value: unknown) => value === '已归还' ? LoanStatus.RETURNED : LoanStatus.ONGOING;
const repairStatusFromLabel = (value: unknown) =>
  value === '已完成' ? RepairStatus.CLOSED : value === '维修中' ? RepairStatus.REPAIRING : RepairStatus.RECEIVED;
const deviceOwnerFromLabel = (value: unknown) => value === '公司资产' ? DeviceOwnerType.COMPANY : DeviceOwnerType.CUSTOMER;
const deviceStatusFromLabel = (value: unknown) =>
  value === '借测中' ? DeviceStatus.LOANED : value === '维修中' ? DeviceStatus.REPAIRING : DeviceStatus.IN_STOCK;
/** 页面跟进来源：'系统新增' 归一为 WEB；合法枚举原样保留，其余兜底 WEB（FollowUpSource 仅 WEB/IMPORT/SYSTEM） */
const followUpSourceFromLabel = (value: unknown): FollowUpSource => {
  if (value === '系统新增') return FollowUpSource.WEB;
  return Object.values(FollowUpSource).includes(value as FollowUpSource) ? value as FollowUpSource : FollowUpSource.WEB;
};

function referencedFileIds(state: FlowState) {
  const ids = new Set<string>();
  for (const record of [...state.records, ...state.recycle.records]) {
    const agreement = record.agreement as { data?: unknown } | undefined;
    const values = Object.values((record.photos ?? {}) as Record<string, unknown>);
    values.push(agreement?.data);
    for (const value of values) {
      const id = storedFileId(value);
      if (id) ids.add(id);
    }
  }
  return ids;
}

function validateState(value: unknown): FlowState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new BadRequestException('数据格式无效');
  const state = value as FlowState;
  if (!Array.isArray(state.records) || !Array.isArray(state.devices) || !state.recycle ||
      !Array.isArray(state.recycle.records) || !Array.isArray(state.recycle.devices) ||
      !state.settings || typeof state.settings !== 'object' || Array.isArray(state.settings)) {
    throw new BadRequestException('数据结构无效');
  }
  if (state.records.length > 20000 || state.devices.length > 20000 || state.recycle.records.length > 20000 || state.recycle.devices.length > 20000) {
    throw new BadRequestException('记录数量超出限制');
  }
  for (const item of [...state.records, ...state.devices, ...state.recycle.records, ...state.recycle.devices]) {
    if (!item || typeof item.id !== 'string' || !item.id || item.id.length > 100) throw new BadRequestException('记录 ID 无效');
  }
  if (/"data":\s*"data:(?:image|application)\//i.test(JSON.stringify(state))) {
    throw new BadRequestException('请先上传附件，不能将文件内容写入业务数据');
  }
  return state;
}

@Injectable()
export class HtmlDeviceFlowService {
  constructor(private readonly db: PrismaService) {}

  /** 分批执行 IN 查询，避免大集合超出参数上限 */
  private async inBatches<T>(ids: string[], size: number, query: (batch: string[]) => Promise<T[]>) {
    const out: T[] = [];
    for (let i = 0; i < ids.length; i += size) out.push(...await query(ids.slice(i, i + size)));
    return out;
  }

  /** 从附件行组装页面协议 photos（槽位字符串 0-7）与 agreement */
  private buildPhotos(attachments: AttachmentRow[]) {
    const photos: Record<string, string> = {};
    let agreement: { name: string; data: string } | null = null;
    for (const attachment of attachments) {
      if (!attachment.photoKey) continue;
      const url = `/api/html-device-flow/files/${attachment.photoKey}`;
      if (attachment.photoCategory === 'AGREEMENT') agreement = { name: attachment.originalName, data: url };
      else if (attachment.photoCategory === 'VIEWS' && attachment.photoSlot != null) photos[String(attachment.photoSlot - 1)] = url;
    }
    return { photos, agreement };
  }

  /**
   * 路线 C：关系库为唯一数据源。revision/settings 仍存 html_flow_state 行，
   * records/devices/recycle 一律实时从 LoanOrder/RepairOrder/Device/FollowUp/Attachment 组装，不回写 blob。
   * 注：html_flow_followups 表停止读写（保留兼容），跟进统一由 FollowUp 表承担。
   */
  async snapshot() {
    const row = await this.db.htmlFlowState.findUnique({ where: { id: 'main' } });
    const revision = row?.revision ?? 0;
    const storedSettings = (row?.data as { settings?: Record<string, unknown> } | null)?.settings;
    const settings = storedSettings && typeof storedSettings === 'object' && !Array.isArray(storedSettings) ? storedSettings : {};

    const [loans, repairs, devices] = await Promise.all([
      this.db.loanOrder.findMany({
        include: {
          organization: { select: { name: true } },
          contact: { select: { name: true, phone: true } },
          items: { orderBy: { createdAt: 'asc' }, include: { device: { select: { serialNumber: true, cameraModel: true, product: true } } } },
        },
      }),
      this.db.repairOrder.findMany({
        include: {
          organization: { select: { name: true } },
          contact: { select: { name: true, phone: true } },
          device: { select: { serialNumber: true, cameraModel: true, product: true } },
        },
      }),
      this.db.device.findMany({ include: { organization: { select: { name: true } } } }),
    ]);
    const loanIds = loans.map((loan) => loan.id);
    const repairIds = repairs.map((repair) => repair.id);
    const loanItemIds = loans.flatMap((loan) => loan.items.map((item) => item.id));
    // 附件统一从 Attachment 表查：借测挂 LoanItem、维修挂 RepairOrder；量大分批
    const attachments: AttachmentRow[] = [
      ...await this.inBatches(loanItemIds, 500, (batch) => this.db.attachment.findMany({ where: { loanItemId: { in: batch } } })),
      ...await this.inBatches(repairIds, 500, (batch) => this.db.attachment.findMany({ where: { repairOrderId: { in: batch } } })),
    ];
    // FollowUp 无 deletedAt 列，直接全取目标集合，按 occurredAt 升序
    const followUps = [
      ...await this.inBatches(loanIds, 500, (batch) => this.db.followUp.findMany({ where: { loanOrderId: { in: batch } }, include: { author: { select: { name: true } } }, orderBy: { occurredAt: 'asc' } })),
      ...await this.inBatches(repairIds, 500, (batch) => this.db.followUp.findMany({ where: { repairOrderId: { in: batch } }, include: { author: { select: { name: true } } }, orderBy: { occurredAt: 'asc' } })),
    ];
    const followUpsByOrder = new Map<string, FlowFollowup[]>();
    for (const followUp of followUps) {
      const key = followUp.loanOrderId ?? followUp.repairOrderId ?? '';
      const list = followUpsByOrder.get(key) ?? [];
      list.push({ id: followUp.flowId ?? `FU-${followUp.id}`, person: followUp.author?.name ?? '', date: fmtYmdhms(followUp.occurredAt), text: followUp.content, source: followUp.source ?? '' });
      followUpsByOrder.set(key, list);
    }
    const attachmentsByLoanItem = new Map<string, AttachmentRow[]>();
    const attachmentsByRepair = new Map<string, AttachmentRow[]>();
    for (const attachment of attachments) {
      if (attachment.loanItemId) {
        const list = attachmentsByLoanItem.get(attachment.loanItemId) ?? [];
        list.push(attachment);
        attachmentsByLoanItem.set(attachment.loanItemId, list);
      }
      if (attachment.repairOrderId) {
        const list = attachmentsByRepair.get(attachment.repairOrderId) ?? [];
        list.push(attachment);
        attachmentsByRepair.set(attachment.repairOrderId, list);
      }
    }

    const records: FlowRecord[] = [];
    const recycleRecords: FlowRecord[] = [];
    const pushRecord = (record: FlowRecord, deletedAt: Date | null) => {
      (deletedAt ? recycleRecords : records).push(record);
    };
    for (const loan of loans) {
      // 一单多设备收拢为首件：SN/型号取首件设备、附件取首件明细，与 sync 的写回口径一致
      const firstItem = loan.items[0];
      const { photos, agreement } = this.buildPhotos(firstItem ? attachmentsByLoanItem.get(firstItem.id) ?? [] : []);
      const device = firstItem?.device ?? null;
      pushRecord({
        id: loan.flowId ?? `R-${loan.id}`,
        orderNo: loan.loanNo,
        type: 'loan',
        sn: device?.serialNumber ?? '',
        model: device?.cameraModel ?? device?.product ?? '',
        customer: loan.organization?.name ?? '',
        contact: loan.contact?.name ?? '',
        phone: loan.contact?.phone ?? '',
        address: '',
        reportDate: '',
        appearance: '',
        reason: '',
        loanStart: fmtYmd(loan.loanedAt),
        loanDue: fmtYmd(loan.dueAt),
        loanPurpose: loan.purpose ?? '',
        inboundCarrier: loan.returnCarrier ?? '',
        inboundTracking: loan.returnTracking ?? '',
        outboundCarrier: loan.outboundCarrier ?? '',
        outboundTracking: loan.outboundTracking ?? '',
        status: LOAN_STATUS_TO_LABEL[loan.status] ?? '借测中',
        owner: '',
        accessories: loan.items.map((item) => item.accessories).filter(Boolean).join('、'),
        notes: loan.note ?? '',
        photos,
        agreement,
        followUps: followUpsByOrder.get(loan.id) ?? [],
        createdAt: fmtYmdhms(loan.createdAt),
        updatedAt: fmtYmdhms(loan.updatedAt),
        ...(loan.deletedAt ? { deletedAt: loan.deletedAt.toISOString() } : {}),
      }, loan.deletedAt);
    }
    for (const repair of repairs) {
      const { photos, agreement } = this.buildPhotos(attachmentsByRepair.get(repair.id) ?? []);
      pushRecord({
        id: repair.flowId ?? `R-${repair.id}`,
        orderNo: repair.repairNo,
        type: 'repair',
        sn: repair.serialNumber ?? repair.device?.serialNumber ?? '',
        model: repair.device?.cameraModel ?? repair.device?.product ?? '',
        customer: repair.organization?.name ?? '',
        contact: repair.contact?.name ?? '',
        phone: repair.contact?.phone ?? '',
        address: '',
        reportDate: fmtYmd(repair.receivedAt),
        appearance: '',
        reason: repair.symptom ?? '',
        loanStart: '',
        loanDue: '',
        loanPurpose: '',
        inboundCarrier: repair.inboundCarrier ?? '',
        inboundTracking: repair.inboundTracking ?? '',
        outboundCarrier: repair.outboundCarrier ?? '',
        outboundTracking: repair.trackingNo ?? '',
        status: REPAIR_STATUS_TO_LABEL[repair.status] ?? '待寄回',
        owner: '',
        accessories: repair.partsReturned ?? '',
        notes: repair.note ?? '',
        photos,
        agreement,
        followUps: followUpsByOrder.get(repair.id) ?? [],
        createdAt: fmtYmdhms(repair.createdAt),
        updatedAt: fmtYmdhms(repair.updatedAt),
        ...(repair.deletedAt ? { deletedAt: repair.deletedAt.toISOString() } : {}),
      }, repair.deletedAt);
    }
    const byCreatedDesc = (a: FlowRecord, b: FlowRecord) => String(b.createdAt).localeCompare(String(a.createdAt));
    records.sort(byCreatedDesc);
    recycleRecords.sort(byCreatedDesc);

    const deviceRows: FlowDevice[] = [];
    const recycleDevices: FlowDevice[] = [];
    for (const device of devices) {
      const row: FlowDevice = {
        id: device.flowId ?? `D-${device.id}`,
        sn: device.serialNumber ?? '',
        model: device.cameraModel ?? device.product ?? '',
        ownership: DEVICE_OWNERSHIP_TO_LABEL[device.ownerType] ?? '客户设备',
        status: DEVICE_STATUS_TO_LABEL[device.status] ?? '在库',
        customer: device.organization?.name ?? '',
        assetNo: device.assetNo ?? '',
        note: device.notes ?? '',
        createdAt: fmtYmdhms(device.createdAt),
        ...(device.deletedAt ? { deletedAt: device.deletedAt.toISOString() } : {}),
      };
      (device.deletedAt ? recycleDevices : deviceRows).push(row);
    }
    deviceRows.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
    recycleDevices.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));

    return { revision, data: { records, devices: deviceRows, recycle: { records: recycleRecords, devices: recycleDevices }, settings } };
  }

  /**
   * 将页面全量数据翻译回关系表（单事务）。revision 乐观锁语义不变；
   * state 行 blob 只保留 settings。html_flow_followups 表停止读写，跟进由 FollowUp 表承担。
   */
  async sync(payload: unknown, actorHint?: string) {
    if (!payload || typeof payload !== 'object') throw new BadRequestException('同步格式无效');
    const { revision, data } = payload as { revision?: number; data?: unknown };
    if (!Number.isInteger(revision) || (revision as number) < 0) throw new BadRequestException('版本号无效');
    const next = validateState(data);
    const json = JSON.stringify(next);
    if (Buffer.byteLength(json) > 15 * 1024 * 1024) throw new BadRequestException('业务数据超出限制');

    let removedFiles: { storageKey: string }[] = [];
    const result = await this.db.$transaction(async (tx) => {
      let row = await tx.htmlFlowState.findUnique({ where: { id: 'main' } });
      if (!row) {
        try {
          row = await tx.htmlFlowState.create({ data: { id: 'main', revision: 0, data: emptyState() as unknown as Prisma.InputJsonValue } });
        } catch {
          throw new ConflictException('数据已被其他人更新，请刷新后重试');
        }
      }
      if (row.revision !== revision) throw new ConflictException('数据已被其他人更新，请刷新后重试');
      const updated = await tx.htmlFlowState.updateMany({
        where: { id: 'main', revision },
        data: { revision: { increment: 1 }, data: { settings: next.settings } as unknown as Prisma.InputJsonValue },
      });
      if (!updated.count) throw new ConflictException('数据已被其他人更新，请刷新后重试');

      // sync 协议本身无用户字段：优先用会话用户（controller 注入），缺失时以系统最早用户兜底
      const actor = (actorHint ? await tx.user.findUnique({ where: { id: actorHint }, select: { id: true } }) : null)
        ?? await tx.user.findFirst({ orderBy: { createdAt: 'asc' }, select: { id: true } });
      if (!actor) throw new ConflictException('系统无可用用户，无法同步');
      const actorId = actor.id;
      const now = new Date();

      // 现有行双索引：flowId（页面来源）与主键（'R-<uuid>' 形态解析）
      const existingLoans = await tx.loanOrder.findMany({ select: { id: true, flowId: true, loanNo: true } });
      const existingRepairs = await tx.repairOrder.findMany({ select: { id: true, flowId: true, repairNo: true, closedAt: true } });
      const existingDevices = await tx.device.findMany({ select: { id: true, flowId: true, serialNumber: true } });
      const loanByFlowId = new Map(existingLoans.filter((l) => l.flowId).map((l) => [l.flowId as string, l]));
      const loanById = new Map(existingLoans.map((l) => [l.id, l]));
      const repairByFlowId = new Map(existingRepairs.filter((r) => r.flowId).map((r) => [r.flowId as string, r]));
      const repairById = new Map(existingRepairs.map((r) => [r.id, r]));
      const deviceByFlowId = new Map(existingDevices.filter((d) => d.flowId).map((d) => [d.flowId as string, d]));
      const deviceById = new Map(existingDevices.map((d) => [d.id, d]));
      const deviceIdBySn = new Map(existingDevices.filter((d) => d.serialNumber).map((d) => [d.serialNumber as string, d.id]));

      const orgIdByName = new Map<string, string | null>();
      const resolveOrg = async (name: string): Promise<string | null> => {
        const key = name.trim().toLowerCase();
        if (orgIdByName.has(key)) return orgIdByName.get(key) as string | null;
        let orgId: string | null = null;
        if (key) {
          const found = await tx.customerOrganization.findFirst({ where: { name: { equals: key, mode: 'insensitive' } }, select: { id: true } });
          orgId = found?.id ?? (await tx.customerOrganization.create({ data: { name: name.trim() }, select: { id: true } })).id;
        }
        orgIdByName.set(key, orgId);
        return orgId;
      };
      const contactIdByKey = new Map<string, string | null>();
      const resolveContact = async (organizationId: string | null, name: string, phone: string): Promise<string | null> => {
        const trimmed = name.trim();
        if (!organizationId || !trimmed) return null;
        const key = `${organizationId}|${trimmed.toLowerCase()}|${phone.trim()}`;
        if (contactIdByKey.has(key)) return contactIdByKey.get(key) as string | null;
        const byPhone = phone.trim() ? await tx.contact.findFirst({ where: { organizationId, name: trimmed, phone: phone.trim() }, select: { id: true } }) : null;
        const found = byPhone ?? await tx.contact.findFirst({ where: { organizationId, name: trimmed }, select: { id: true } });
        const contactId = found?.id ?? (await tx.contact.create({ data: { organizationId, name: trimmed, phone: phone.trim() || null }, select: { id: true } })).id;
        contactIdByKey.set(key, contactId);
        return contactId;
      };
      const userIdByName = new Map<string, string | null>();
      const resolveUserByName = async (name: string): Promise<string | null> => {
        const key = name.trim().toLowerCase();
        if (!key) return null;
        if (userIdByName.has(key)) return userIdByName.get(key) as string | null;
        const found = await tx.user.findFirst({ where: { name: { equals: name.trim(), mode: 'insensitive' } }, select: { id: true } });
        userIdByName.set(key, found?.id ?? null);
        return found?.id ?? null;
      };
      /** SN → deviceId；无则按业务来源建最小设备（借测=公司样机、维修=客户设备） */
      const resolveDeviceBySn = async (sn: string, model: string, kind: 'loan' | 'repair', organizationId: string | null): Promise<string | null> => {
        if (!sn) return null;
        const hit = deviceIdBySn.get(sn);
        if (hit) return hit;
        const created = await tx.device.create({
          data: {
            name: model || sn,
            serialNumber: sn,
            cameraModel: model || null,
            ownerType: kind === 'repair' ? DeviceOwnerType.CUSTOMER : DeviceOwnerType.COMPANY,
            source: DeviceSource.MANUAL,
            organizationId: kind === 'repair' ? organizationId : null,
          },
          select: { id: true },
        });
        deviceIdBySn.set(sn, created.id);
        return created.id;
      };
      const generateLoanNo = async () => {
        const prefix = dateSerialPrefix('LN');
        const last = await tx.loanOrder.findFirst({ where: { loanNo: { startsWith: prefix } }, orderBy: { loanNo: 'desc' }, select: { loanNo: true } });
        return nextSerial(last?.loanNo ?? null, prefix);
      };
      const generateRepairNo = async () => {
        const prefix = dateSerialPrefix('RP');
        const last = await tx.repairOrder.findFirst({ where: { repairNo: { startsWith: prefix } }, orderBy: { repairNo: 'desc' }, select: { repairNo: true } });
        return nextSerial(last?.repairNo ?? null, prefix);
      };
      const loanNoTaken = (loanNo: string, selfId?: string) => existingLoans.some((l) => l.loanNo === loanNo && l.id !== selfId);
      const repairNoTaken = (repairNo: string, selfId?: string) => existingRepairs.some((r) => r.repairNo === repairNo && r.id !== selfId);

      const syncFollowUps = async (record: FlowRecord, orderRef: { loanOrderId?: string; repairOrderId?: string }) => {
        const incoming = Array.isArray(record.followUps) ? record.followUps : [];
        for (const followUp of incoming) {
          if (!followUp || typeof followUp.id !== 'string' || !followUp.id || followUp.id.length > 100 || typeof followUp.text !== 'string') {
            throw new BadRequestException('跟进记录无效');
          }
        }
        const existing = await tx.followUp.findMany({ where: orderRef, select: { id: true, flowId: true } });
        const byFlowId = new Map(existing.filter((f) => f.flowId).map((f) => [f.flowId as string, f]));
        const byId = new Map(existing.map((f) => [f.id, f]));
        const keepIds = new Set<string>();
        for (const followUp of incoming) {
          const matchedFlow = byFlowId.get(followUp.id);
          const uuid = flowRowUuid(followUp.id, 'FU');
          const id = matchedFlow ? matchedFlow.id : uuid && byId.has(uuid) ? uuid : randomUUID();
          keepIds.add(id);
          const authorId = (followUp.person ? await resolveUserByName(followUp.person) : null) ?? actorId;
          const data = {
            ...orderRef,
            authorId,
            occurredAt: parseDate(followUp.date) ?? now,
            content: followUp.text as string,
            source: followUpSourceFromLabel(followUp.source),
            flowId: followUp.id,
          };
          await tx.followUp.upsert({ where: { id }, update: data, create: { ...data, id } });
        }
        const staleIds = existing.filter((f) => !keepIds.has(f.id)).map((f) => f.id);
        if (staleIds.length) await tx.followUp.deleteMany({ where: { id: { in: staleIds } } });
      };

      const syncAttachments = async (record: FlowRecord, scope: { loanItemId?: string; repairOrderId?: string }) => {
        const existing = await tx.attachment.findMany({ where: { ...scope, photoCategory: { in: ['VIEWS', 'AGREEMENT'] } } });
        // 先算保留集并删除失效行，再 upsert：同槽位换图时若先 upsert 会撞
        // (loan_item_id|repair_order_id, photo_category, photo_slot) 唯一索引（P2002）
        const keepKeys = new Set<string>();
        for (const url of Object.values(record.photos ?? {})) {
          const fileId = storedFileId(url as string);
          if (fileId) keepKeys.add(fileId);
        }
        const agreementFileId = storedFileId(record.agreement?.data);
        if (agreementFileId) keepKeys.add(agreementFileId);
        const staleIds = existing.filter((a) => a.photoKey && !keepKeys.has(a.photoKey)).map((a) => a.id);
        if (staleIds.length) await tx.attachment.deleteMany({ where: { id: { in: staleIds } } });
        const upsertFileAttachment = async (fileId: string, category: 'VIEWS' | 'AGREEMENT', slot: number) => {
          const file = await tx.htmlFlowFile.findUnique({ where: { id: fileId } });
          if (!file) return; // 文件行缺失（如已被清理）则跳过该照片
          const data = {
            ...scope,
            storageKey: file.storageKey,
            originalName: file.originalName,
            mimeType: file.mimeType,
            sizeBytes: file.sizeBytes,
            visibility: Visibility.INTERNAL,
            photoCategory: category,
            photoSlot: slot,
          };
          await tx.attachment.upsert({ where: { photoKey: fileId }, update: data, create: { ...data, photoKey: fileId } });
        };
        for (const [slot, url] of Object.entries(record.photos ?? {})) {
          const slotNumber = Number(slot);
          if (!Number.isInteger(slotNumber) || slotNumber < 0) continue;
          const fileId = storedFileId(url);
          if (fileId) await upsertFileAttachment(fileId, 'VIEWS', slotNumber + 1);
        }
        if (agreementFileId) await upsertFileAttachment(agreementFileId, 'AGREEMENT', 1);
      };

      const upsertLoanRecord = async (record: FlowRecord) => {
        const matchedFlow = loanByFlowId.get(record.id);
        const uuid = flowRowUuid(record.id, 'R');
        const rowId = matchedFlow ? matchedFlow.id : uuid && loanById.has(uuid) ? uuid : randomUUID();
        const organizationId = await resolveOrg(asText(record.customer));
        if (!organizationId) throw new BadRequestException(`记录 ${record.id} 缺少客户名称`);
        const contactId = await resolveContact(organizationId, asText(record.contact), asText(record.phone));
        const status = loanStatusFromLabel(record.status);
        const data = {
          organizationId,
          contactId,
          purpose: asText(record.loanPurpose) || '设备借测',
          note: asText(record.notes) || null,
          loanedAt: parseDate(record.loanStart),
          dueAt: parseDate(record.loanDue),
          outboundCarrier: asText(record.outboundCarrier) || null,
          outboundTracking: asText(record.outboundTracking) || null,
          returnCarrier: asText(record.inboundCarrier) || null,
          returnTracking: asText(record.inboundTracking) || null,
          status,
          flowId: record.id,
          deletedAt: null,
        };
        const orderNo = asText(record.orderNo);
        const create = {
          ...data,
          loanNo: orderNo && !loanNoTaken(orderNo, rowId) ? orderNo : await generateLoanNo(),
          createdById: actorId,
        };
        await tx.loanOrder.upsert({ where: { id: rowId }, update: data, create: { ...create, id: rowId } });
        // LoanItem 按 SN 解析设备；SN 为空的历史排队单允许无明细（accessories 不落库）
        const deviceId = await resolveDeviceBySn(asText(record.sn), asText(record.model), 'loan', organizationId);
        if (deviceId) {
          const item = await tx.loanItem.upsert({
            where: { loanOrderId_deviceId: { loanOrderId: rowId, deviceId } },
            update: { accessories: asText(record.accessories) || null },
            create: { loanOrderId: rowId, deviceId, accessories: asText(record.accessories) || null },
          });
          await syncAttachments(record, { loanItemId: item.id });
        }
        await syncFollowUps(record, { loanOrderId: rowId });
      };

      const upsertRepairRecord = async (record: FlowRecord) => {
        const matchedFlow = repairByFlowId.get(record.id);
        const uuid = flowRowUuid(record.id, 'R');
        const rowId = matchedFlow ? matchedFlow.id : uuid && repairById.has(uuid) ? uuid : randomUUID();
        const organizationId = await resolveOrg(asText(record.customer));
        if (!organizationId) throw new BadRequestException(`记录 ${record.id} 缺少客户名称`);
        const contactId = await resolveContact(organizationId, asText(record.contact), asText(record.phone));
        const status = repairStatusFromLabel(record.status);
        const existing = repairById.get(rowId);
        const data = {
          organizationId,
          contactId,
          serialNumber: asText(record.sn) || null,
          symptom: asText(record.reason) || '',
          receivedAt: parseDate(record.reportDate) ?? now,
          inboundCarrier: asText(record.inboundCarrier) || null,
          inboundTracking: asText(record.inboundTracking) || null,
          outboundCarrier: asText(record.outboundCarrier) || null,
          trackingNo: asText(record.outboundTracking) || null,
          partsReturned: asText(record.accessories) || null,
          note: asText(record.notes) || null,
          status,
          deviceId: await resolveDeviceBySn(asText(record.sn), asText(record.model), 'repair', organizationId),
          flowId: record.id,
          deletedAt: null,
          ...(status === RepairStatus.CLOSED && !existing?.closedAt ? { closedAt: now } : {}),
        };
        const orderNo = asText(record.orderNo);
        const create = {
          ...data,
          repairNo: orderNo && !repairNoTaken(orderNo, rowId) ? orderNo : await generateRepairNo(),
          createdById: actorId,
        };
        await tx.repairOrder.upsert({ where: { id: rowId }, update: data, create: { ...create, id: rowId } });
        await syncAttachments(record, { repairOrderId: rowId });
        await syncFollowUps(record, { repairOrderId: rowId });
      };

      // 活跃区 records：逐条翻译回关系表（含回收恢复 deletedAt=null）
      for (const record of next.records) {
        if (record.type === 'repair') await upsertRepairRecord(record);
        else await upsertLoanRecord(record);
      }

      // 活跃区 devices：页面台账与记录联动（记录侧新建的设备按 SN 被 adopt 并补 flowId）
      const deviceRefId = (device: FlowDevice) => {
        const matchedFlow = deviceByFlowId.get(device.id);
        if (matchedFlow) return matchedFlow.id;
        const uuid = flowRowUuid(device.id, 'D');
        if (uuid && deviceById.has(uuid)) return uuid;
        const sn = asText(device.sn);
        return (sn && deviceIdBySn.get(sn)) || randomUUID();
      };
      for (const device of next.devices) {
        const rowId = deviceRefId(device);
        const organizationId = await resolveOrg(asText(device.customer));
        const data = {
          name: asText(device.model) || asText(device.sn) || '设备',
          cameraModel: asText(device.model) || null,
          ownerType: deviceOwnerFromLabel(device.ownership),
          status: deviceStatusFromLabel(device.status),
          assetNo: asText(device.assetNo) || null,
          notes: asText(device.note) || null,
          organizationId,
          flowId: device.id,
          deletedAt: null,
        };
        // serialNumber 仅在建行时写入，避免更新分支触碰唯一约束（SN 变更走记录联动建新行）
        await tx.device.upsert({
          where: { id: rowId },
          update: data,
          create: { ...data, serialNumber: asText(device.sn) || null, source: DeviceSource.MANUAL },
        });
      }

      // 回收区：软删对应关系行（仅处理 flowId 行或 payload 中以 'R-<uuid>'/'D-<uuid>' 指到的行）
      for (const record of next.recycle.records) {
        if (record.type === 'repair') {
          const matchedFlow = repairByFlowId.get(record.id);
          const uuid = flowRowUuid(record.id, 'R');
          const rowId = matchedFlow ? matchedFlow.id : uuid && repairById.has(uuid) ? uuid : null;
          if (rowId) await tx.repairOrder.update({ where: { id: rowId }, data: { deletedAt: now } });
        } else {
          const matchedFlow = loanByFlowId.get(record.id);
          const uuid = flowRowUuid(record.id, 'R');
          const rowId = matchedFlow ? matchedFlow.id : uuid && loanById.has(uuid) ? uuid : null;
          if (rowId) await tx.loanOrder.update({ where: { id: rowId }, data: { deletedAt: now } });
        }
      }
      for (const device of next.recycle.devices) {
        const rowId = deviceByFlowId.get(device.id)?.id ?? (() => {
          const uuid = flowRowUuid(device.id, 'D');
          return uuid && deviceById.has(uuid) ? uuid : null;
        })();
        if (rowId) await tx.device.update({ where: { id: rowId }, data: { deletedAt: now } });
      }

      // 删除保护：sync 后既不在活跃区也不在回收区的行——仅 flowId 非空（源自页面）才物理删除；
      // flowId 为空的行（工单联动等关系库原生创建）一律不动，防止快照后新建行被旧状态误删
      const payloadRecordIds = new Set([...next.records, ...next.recycle.records].map((r) => r.id));
      const payloadDeviceIds = new Set([...next.devices, ...next.recycle.devices].map((d) => d.id));
      for (const loan of existingLoans) {
        if (loan.flowId && !payloadRecordIds.has(loan.flowId)) await tx.loanOrder.delete({ where: { id: loan.id } });
      }
      for (const repair of existingRepairs) {
        if (repair.flowId && !payloadRecordIds.has(repair.flowId)) await tx.repairOrder.delete({ where: { id: repair.id } });
      }
      for (const device of existingDevices) {
        if (device.flowId && !payloadDeviceIds.has(device.flowId)) await tx.device.delete({ where: { id: device.id } });
      }

      // 孤儿文件清理：不被「本次 payload 引用 ∪ Attachment.photoKey 集合」引用且上传超 24h 的文件
      const referenced = referencedFileIds(next);
      const attachedKeys = await tx.attachment.findMany({ where: { photoKey: { not: null } }, select: { photoKey: true } });
      for (const key of attachedKeys) if (key.photoKey) referenced.add(key.photoKey.toLowerCase());
      const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000);
      const orphans = await tx.htmlFlowFile.findMany({ where: { id: { notIn: [...referenced] }, createdAt: { lt: cutoff } }, select: { id: true, storageKey: true } });
      if (orphans.length) {
        await tx.htmlFlowFile.deleteMany({ where: { id: { in: orphans.map((o) => o.id) } } });
        removedFiles = orphans;
      }
      return { revision: (revision as number) + 1 };
    }, { timeout: 30000 });
    await Promise.all(removedFiles.map((file) => unlink(resolve(this.uploadRoot(), file.storageKey)).catch(() => undefined)));
    return result;
  }

  private uploadRoot() { return resolve(process.env.UPLOAD_DIR ?? './uploads', 'html-device-flow'); }

  async upload(file: Express.Multer.File, userId: string) {
    if (!file) throw new BadRequestException('请选择文件');
    const allowed = new Set(['image/jpeg', 'image/png', 'image/webp', 'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']);
    if (!allowed.has(file.mimetype)) throw new BadRequestException('仅支持 PDF、Word、JPG、PNG 和 WebP');
    const id = randomUUID();
    const originalName = decodedUploadName(file.originalname);
    const suffix = extname(originalName).toLowerCase().slice(0, 12);
    const storageKey = id + suffix;
    await mkdir(this.uploadRoot(), { recursive: true });
    await writeFile(resolve(this.uploadRoot(), storageKey), file.buffer, { flag: 'wx' });
    try {
      await this.db.htmlFlowFile.create({ data: { id, storageKey, originalName: basename(originalName).slice(0, 255), mimeType: file.mimetype, sizeBytes: file.size, createdById: userId } });
    } catch (error) {
      await import('node:fs/promises').then((fs) => fs.unlink(resolve(this.uploadRoot(), storageKey)).catch(() => undefined));
      throw error;
    }
    return { id, url: `/api/html-device-flow/files/${id}`, name: originalName, type: file.mimetype, size: file.size };
  }

  async file(id: string) {
    const metadata = await this.db.htmlFlowFile.findUnique({ where: { id } });
    if (!metadata) throw new NotFoundException('文件不存在');
    const bytes = await readFile(resolve(this.uploadRoot(), metadata.storageKey)).catch(() => null);
    if (!bytes) throw new NotFoundException('文件不存在');
    return { metadata, bytes };
  }
}
