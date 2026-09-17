import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, unlink, writeFile } from 'node:fs/promises';
import { basename, extname, resolve } from 'node:path';
import { PrismaService } from '../prisma/prisma.service.js';

type FlowRecord = Record<string, unknown> & { id: string; followUps?: FlowFollowup[] };
type FlowFollowup = { id: string; date?: string; person?: string; text?: string; source?: string };
type FlowState = {
  records: FlowRecord[];
  devices: Record<string, unknown>[];
  recycle: { records: FlowRecord[]; devices: Record<string, unknown>[] };
  settings: Record<string, unknown>;
};

const emptyState = (): FlowState => ({ records: [], devices: [], recycle: { records: [], devices: [] }, settings: {} });
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const storedFileId = (value: unknown) => typeof value === 'string' ? /^\/api\/html-device-flow\/files\/([a-f0-9-]{36})$/i.exec(value)?.[1] : undefined;
function decodedUploadName(value: string) {
  if (/[^\u0000-\u00ff]/.test(value)) return value;
  try { return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.from(value, 'latin1')); }
  catch { return value; }
}

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

  async snapshot() {
    const row = await this.db.htmlFlowState.findUnique({ where: { id: 'main' } });
    const data = row ? clone(row.data) as FlowState : emptyState();
    const followups = await this.db.htmlFlowFollowup.findMany({ where: { deletedAt: null }, orderBy: [{ recordId: 'asc' }, { sequence: 'asc' }] });
    const byRecord = new Map<string, FlowFollowup[]>();
    for (const f of followups) {
      const list = byRecord.get(f.recordId) ?? [];
      list.push({ id: f.id, person: f.person ?? '', date: f.date ?? '', text: f.content, source: f.source ?? '' });
      byRecord.set(f.recordId, list);
    }
    for (const record of [...data.records, ...data.recycle.records]) record.followUps = byRecord.get(record.id) ?? [];
    return { revision: row?.revision ?? 0, data };
  }

  async sync(payload: unknown) {
    if (!payload || typeof payload !== 'object') throw new BadRequestException('同步格式无效');
    const { revision, data } = payload as { revision?: number; data?: unknown };
    if (!Number.isInteger(revision) || (revision as number) < 0) throw new BadRequestException('版本号无效');
    const next = validateState(data);
    const json = JSON.stringify(next);
    if (Buffer.byteLength(json) > 15 * 1024 * 1024) throw new BadRequestException('业务数据超出限制');
    const stored = clone(next);
    for (const record of [...stored.records, ...stored.recycle.records]) delete record.followUps;
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
        data: { revision: { increment: 1 }, data: stored as unknown as Prisma.InputJsonValue },
      });
      if (!updated.count) throw new ConflictException('数据已被其他人更新，请刷新后重试');

      const previous = clone(row.data) as FlowState;
      const oldIds = new Set([...previous.records, ...previous.recycle.records].map((r) => r.id));
      const nextById = new Map([...next.records, ...next.recycle.records].map((r) => [r.id, r]));
      const currentFollowups = await tx.htmlFlowFollowup.findMany({
        where: { deletedAt: null },
        orderBy: [{ recordId: 'asc' }, { sequence: 'asc' }],
      });
      const followupsByRecord = new Map<string, typeof currentFollowups>();
      for (const followup of currentFollowups) {
        const list = followupsByRecord.get(followup.recordId) ?? [];
        list.push(followup);
        followupsByRecord.set(followup.recordId, list);
      }
      for (const [recordId, record] of nextById) {
        const incoming = record.followUps ?? [];
        const current = followupsByRecord.get(recordId) ?? [];
        const prior = current.map((f) => ({ id: f.id, person: f.person ?? '', date: f.date ?? '', text: f.content, source: f.source ?? '' }));
        if (JSON.stringify(incoming) === JSON.stringify(prior)) continue;
        const ids = new Set(incoming.map((f) => f.id));
        await tx.htmlFlowFollowup.updateMany({ where: { recordId, id: { notIn: [...ids] }, deletedAt: null }, data: { deletedAt: new Date() } });
        for (const [sequence, f] of incoming.entries()) {
          if (!f.id || f.id.length > 100 || typeof f.text !== 'string') throw new BadRequestException('跟进记录无效');
          await tx.htmlFlowFollowup.upsert({
            where: { id: f.id },
            update: { recordId, sequence, person: f.person || null, date: f.date || null, content: f.text, source: f.source || null, deletedAt: null },
            create: { id: f.id, recordId, sequence, person: f.person || null, date: f.date || null, content: f.text, source: f.source || null },
          });
        }
      }
      for (const recordId of oldIds) {
        if (!nextById.has(recordId)) await tx.htmlFlowFollowup.updateMany({ where: { recordId, deletedAt: null }, data: { deletedAt: new Date() } });
      }
      const nextFiles = referencedFileIds(next);
      const removedIds = [...referencedFileIds(previous)].filter((id) => !nextFiles.has(id));
      if (removedIds.length) {
        removedFiles = await tx.htmlFlowFile.findMany({ where: { id: { in: removedIds } }, select: { storageKey: true } });
        await tx.htmlFlowFile.deleteMany({ where: { id: { in: removedIds } } });
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
