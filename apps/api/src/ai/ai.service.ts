import { BadRequestException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import type { AIProviderConfig } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service.js';
import { AIKeyStore } from './ai.crypto.js';
import { AIAdapterRegistry } from './ai.registry.js';
import { AITransport } from './ai.transport.js';
import { FeatureDto, ProviderDto } from './ai.dto.js';
import { AIError, FEATURES, safeError, type AdapterConfig, type Feature, type Message, type Usage } from './ai.types.js';

@Injectable()
export class AIService {
  private readonly logger = new Logger(AIService.name);
  private active = new Set<string>();
  constructor(private readonly prisma: PrismaService, private readonly keys: AIKeyStore, private readonly registry: AIAdapterRegistry, private readonly transport: AITransport) {}
  private publicProvider(p: AIProviderConfig) {
    const { apiKeyEncrypted, ...rest } = p;
    return { ...rest, hasApiKey: Boolean(apiKeyEncrypted), apiKeyMasked: apiKeyEncrypted ? '********' : '' };
  }
  async providers() {
    return { encryptionReady: this.keys.ready(), providers: (await this.prisma.aIProviderConfig.findMany({ orderBy: { createdAt: 'asc' } })).map((p) => this.publicProvider(p)) };
  }
  keyExchange() { return { publicKey: this.keys.publicKey() }; }
  async saveProvider(dto: ProviderDto, id: string = randomUUID()) {
    try { this.transport.validateUrl(dto.baseUrl); } catch (e) { throw new BadRequestException(safeError(e).message); }
    return this.prisma.$transaction(async (tx) => {
      await tx.$executeRaw`SELECT pg_advisory_xact_lock(80813)`;
      const previous = await tx.aIProviderConfig.findUnique({ where: { id } });
      const { sealedApiKey, ...values } = dto;
      let encrypted = previous?.apiKeyEncrypted ?? null;
      if (previous?.apiKeyEncrypted && previous.baseUrl !== dto.baseUrl.replace(/\/$/, '') && !sealedApiKey) throw new BadRequestException('更换服务地址时请重新输入 API Key');
      if (sealedApiKey) {
        try { encrypted = this.keys.encrypt(this.keys.unseal(sealedApiKey), id); } catch (e) { throw new BadRequestException(safeError(e).message); }
      }
      if (dto.enabled && !encrypted) throw new BadRequestException('启用前请先配置 API Key');
      if (dto.isDefault && !dto.enabled) throw new BadRequestException('默认 Provider 必须启用');
      if (dto.enabled) { try { this.keys.decrypt(encrypted, id); } catch (e) { throw new BadRequestException(safeError(e).message); } }
      if (dto.isDefault) await tx.aIProviderConfig.updateMany({ where: { isDefault: true }, data: { isDefault: false } });
      const data = { ...values, name: dto.name.trim(), baseUrl: dto.baseUrl.replace(/\/$/, ''), apiKeyEncrypted: encrypted };
      const saved = await tx.aIProviderConfig.upsert({ where: { id }, create: { id, ...data }, update: data });
      return this.publicProvider(saved);
    });
  }
  async updateProvider(id: string, dto: ProviderDto) { await this.findProvider(id); return this.saveProvider(dto, id); }
  private async findProvider(id: string) {
    const p = await this.prisma.aIProviderConfig.findUnique({ where: { id } });
    if (!p) throw new NotFoundException('Provider 不存在');
    return p;
  }
  async deleteProvider(id: string) {
    await this.findProvider(id);
    await this.prisma.$transaction(async (tx) => { await tx.$executeRaw`SELECT pg_advisory_xact_lock(80813)`; await tx.aIProviderConfig.deleteMany({ where: { id } }); });
    return { success: true };
  }
  async features() {
    const rows = await this.prisma.aIFeatureConfig.findMany();
    return Object.entries(FEATURES).map(([featureKey, label]) => ({ featureKey, label, active: featureKey === 'quick_ticket_parser', useSystemDefault: true, providerId: null, model: null, temperature: null, maxTokens: null, ...rows.find((f) => f.featureKey === featureKey) }));
  }
  async saveFeature(featureKey: string, dto: FeatureDto) {
    if (!Object.hasOwn(FEATURES, featureKey)) throw new BadRequestException('未知 AI 功能');
    return this.prisma.$transaction(async (tx) => {
      await tx.$executeRaw`SELECT pg_advisory_xact_lock(80813)`;
      if (!dto.useSystemDefault) {
        if (!dto.providerId || !await tx.aIProviderConfig.findFirst({ where: { id: dto.providerId, enabled: true } })) throw new BadRequestException('请选择已启用的 Provider');
      }
      const data = { useSystemDefault: dto.useSystemDefault, providerId: dto.useSystemDefault ? null : dto.providerId, model: dto.useSystemDefault ? null : dto.model ?? null, temperature: dto.temperature ?? null, maxTokens: dto.maxTokens ?? null };
      return tx.aIFeatureConfig.upsert({ where: { featureKey }, create: { featureKey, ...data }, update: data });
    });
  }
  async usage() {
    const rows = await this.prisma.aIUsageLog.findMany({ orderBy: { createdAt: 'desc' }, take: 100 });
    const users = await this.prisma.user.findMany({ where: { id: { in: [...new Set(rows.map((r) => r.userId))] } }, select: { id: true, name: true, username: true } });
    return rows.map((r) => ({ ...r, user: users.find((u) => u.id === r.userId) ?? null }));
  }
  async chat<T>(input: { userId: string; feature: Feature; messages: Message[]; validate: (value: unknown) => T; temperature?: number; maxTokens?: number }) {
    return this.run(input.userId, input.feature, undefined, async (config, adapter, signal) => {
      const response = await adapter.chat({ ...config, temperature: input.temperature ?? config.temperature, maxTokens: input.maxTokens ?? config.maxTokens }, { messages: input.messages, json: true }, signal);
      let data: T;
      try { data = input.validate(JSON.parse(response.content)); } catch { throw new AIError('INVALID_OUTPUT', response.usage); }
      return { data, usage: response.usage };
    });
  }
  testProvider(id: string, userId: string) {
    return this.run(userId, 'connection_test', id, async (config, adapter, signal) => {
      const response = await adapter.testConnection(config, signal);
      try { if (JSON.parse(response.content)?.ok !== true) throw new Error(); } catch { throw new AIError('INVALID_OUTPUT', response.usage); }
      return { data: { connected: true }, usage: response.usage };
    });
  }
  models(id: string, userId: string) {
    return this.run(userId, 'list_models', id, async (config, adapter, signal) => ({ data: await adapter.listModels(config, signal), usage: { promptTokens: null, completionTokens: null, totalTokens: null } }));
  }
  private async run<T>(userId: string, feature: string, providerId: string | undefined, operation: (config: AdapterConfig, adapter: ReturnType<AIAdapterRegistry['get']>, signal: AbortSignal) => Promise<{ data: T; usage: Usage }>) {
    const started = Date.now(); const requestId = randomUUID();
    let provider: AIProviderConfig | null = null; let model: string | null = null;
    let usage: Usage = { promptTokens: null, completionTokens: null, totalTokens: null }; let attempts = 0;
    let errorType: string | null = null; let success = false; let acquired = false;
    try {
      if (this.active.has(userId) || this.active.size >= 8) throw new AIError('BUSY');
      this.active.add(userId); acquired = true;
      const override = providerId ? null : await this.prisma.aIFeatureConfig.findUnique({ where: { featureKey: feature } });
      provider = providerId ? await this.prisma.aIProviderConfig.findUnique({ where: { id: providerId } }) : override && !override.useSystemDefault ? (override.providerId ? await this.prisma.aIProviderConfig.findUnique({ where: { id: override.providerId } }) : null) : await this.prisma.aIProviderConfig.findFirst({ where: { isDefault: true } });
      if (!provider) throw new AIError('NOT_CONFIGURED');
      model = (!override?.useSystemDefault && override?.model) || provider.defaultModel;
      if (!providerId && !provider.enabled) throw new AIError('DISABLED');
      const config: AdapterConfig = { ...provider, apiKey: this.keys.decrypt(provider.apiKeyEncrypted, provider.id), defaultModel: model, temperature: override?.temperature ?? provider.temperature, maxTokens: override?.maxTokens ?? provider.maxTokens };
      const adapter = this.registry.get(provider.provider);
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), provider.timeout);
      try {
        for (let retry = 0; retry < 2; retry++) {
          attempts++;
          try {
            const response = await operation(config, adapter, controller.signal);
            usage = response.usage; success = true;
            return { success: true as const, data: response.data, requestId, provider: provider.provider, model, usage, latencyMs: Date.now() - started };
          } catch (e) {
            const error = controller.signal.aborted ? new AIError('TIMEOUT') : safeError(e);
            if (error.usage) usage = error.usage;
            if (retry === 1 || !['NETWORK', 'PROVIDER_ERROR'].includes(error.code)) throw error;
          }
        }
      } finally { clearTimeout(timer); }
      throw new AIError('PROVIDER_ERROR');
    } catch (e) {
      const error = safeError(e); errorType = error.code;
      return { success: false as const, requestId, error: error.message, errorType: error.code, fallback: true, latencyMs: Date.now() - started };
    } finally {
      if (acquired) this.active.delete(userId);
      try { await this.prisma.aIUsageLog.create({ data: { requestId, userId, feature, providerId: provider?.id, provider: provider?.provider, model, success, errorType, attempts, latencyMs: Date.now() - started, ...usage } }); }
      catch { this.logger.warn(`AI usage metadata could not be persisted: ${requestId}`); }
    }
  }
}
