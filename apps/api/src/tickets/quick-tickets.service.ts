import { BadRequestException, ConflictException, ForbiddenException, Inject, Injectable } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { QUICK_INPUT_PARSER, extractDateExpression, extractStatusExpression, type QuickInputParser, ticketSimilarity } from './quick-input.parser.js';
import { SimilarTicketsDto, UpdateQuickTicketDto } from './dto/quick-ticket.dto.js';

@Injectable()
export class QuickTicketsService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService, @Inject(QUICK_INPUT_PARSER) private readonly parser: QuickInputParser) {}

  async parse(user: AuthUser, rawText: string) {
    this.access.requireInternal(user);
    // 日期表达式（本周一/0907/9月7日等）与状态关键词（已解决/处理中等）先确定性剥离，AI/规则解析器只处理剩余文本
    const extracted = extractDateExpression(rawText);
    const withStatus = extractStatusExpression(extracted.text);
    const customers = await this.prisma.customerOrganization.findMany({ where: this.access.customerWhere(user), select: { id: true, name: true } });
    const users = await this.prisma.user.findMany({ where: { status: "ACTIVE", role: { name: { in: ['admin', 'support', 'employee'] } } }, select: { id: true, name: true, username: true } });
    const modelHint = rawText.match(/\b[A-Za-z]+[- ]?\d{3,}[A-Za-z0-9-]*\b/)?.[0]?.replace(/ /g, '');
    const modelCandidates = modelHint ? await this.prisma.device.findMany({ where: { organizationId: { in: customers.map((c) => c.id) }, cameraModel: { equals: modelHint, mode: 'insensitive' } }, select: { cameraModel: true }, take: 20 }) : [];
    const result = await this.parser.parse(withStatus.text, { customers, users, currentUserId: user.id, deviceModels: [...new Set(modelCandidates.map((d) => d.cameraModel).filter((m): m is string => Boolean(m)))] });
    const devices = result.matchedCustomer && result.deviceText ? await this.prisma.device.findMany({ where: { organizationId: result.matchedCustomer.id, OR: [{ cameraModel: { equals: result.deviceText, mode: 'insensitive' } }, { name: { equals: result.deviceText, mode: 'insensitive' } }] }, select: { id: true, name: true, serialNumber: true, cameraModel: true } }) : [];
    const similarTickets = result.matchedCustomer && result.issue ? await this.similar(user, { organizationId: result.matchedCustomer.id, issue: result.issue, cameraModel: result.deviceText }) : [];
    // occurredAt/status 由确定性提取给出；rawText 保留原文（含日期/状态短语）供追溯
    return { ...result, rawText, occurredAt: extracted.occurredAt, status: withStatus.status, deviceCandidates: devices, matchedDevice: devices.length === 1 ? devices[0] : null, similarTickets };
  }

  async similar(user: AuthUser, dto: SimilarTicketsDto) {
    this.access.requireInternal(user);
    await this.access.requireCustomer(user, dto.organizationId);
    const tickets = await this.prisma.ticket.findMany({ where: { AND: [this.access.ticketWhere(user), { organizationId: dto.organizationId }] }, include: { organization: { select: { id: true, name: true } }, device: true, assignee: { select: { id: true, name: true } } } });
    return tickets.map((t) => ({ ...t, similarity: Math.max(ticketSimilarity(dto.issue, t.title, dto.cameraModel ?? '', t.cameraModel ?? t.device?.cameraModel ?? '', !['CLOSED', 'RESOLVED'].includes(t.status)), ticketSimilarity(dto.issue, t.description, dto.cameraModel ?? '', t.cameraModel ?? t.device?.cameraModel ?? '', !['CLOSED', 'RESOLVED'].includes(t.status))) }))
      .filter((t) => t.similarity >= 40).sort((a, b) => b.similarity - a.similarity).slice(0, 6);
  }

  async update(user: AuthUser, id: string, dto: UpdateQuickTicketDto) {
    this.access.requireInternal(user);
    const current = await this.access.requireTicket(user, id);
    if (!this.access.canEditTicket(user, current)) throw new ForbiddenException('仅创建人、负责人或管理员可以更新该工单');
    if (!dto.issue.trim()) throw new BadRequestException('问题描述不能为空');
    if (!await this.prisma.user.findFirst({ where: { id: dto.assigneeId, status: "ACTIVE", role: { name: { in: ['admin', 'support', 'employee'] } } } })) throw new BadRequestException('负责人不可分配');
    return this.prisma.$transaction(async (tx) => {
      const result = await tx.ticket.updateMany({ where: { id, organizationId: dto.organizationId, updatedAt: new Date(dto.expectedUpdatedAt) }, data: { assigneeId: dto.assigneeId, priority: dto.priority, updatedAt: new Date() } });
      if (!result.count) throw new ConflictException('工单已变化或客户不一致，请重新检查相似工单');
      await tx.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type: 'INTERNAL_NOTE', visibility: 'INTERNAL', content: dto.issue, metadata: { source: 'QUICK_INPUT', rawText: dto.rawText, assigneeId: dto.assigneeId, priority: dto.priority } } });
      return tx.ticket.findUniqueOrThrow({ where: { id } });
    });
  }
}
