import { Module } from '@nestjs/common';
import { AIController } from './ai.controller.js';
import { AIService } from './ai.service.js';
import { AIKeyStore } from './ai.crypto.js';
import { AITransport } from './ai.transport.js';
import { AIAdapterRegistry } from './ai.registry.js';
import { OpenAICompatibleAdapter } from './openai-compatible.adapter.js';

@Module({ controllers: [AIController], providers: [AIService, AIKeyStore, AITransport, AIAdapterRegistry, OpenAICompatibleAdapter], exports: [AIService] })
export class AIModule {}
