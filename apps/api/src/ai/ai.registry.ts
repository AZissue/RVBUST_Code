import { Injectable } from '@nestjs/common';
import { OpenAICompatibleAdapter } from './openai-compatible.adapter.js';
import { AIError, PROVIDERS, type AIProviderAdapter } from './ai.types.js';

@Injectable()
export class AIAdapterRegistry {
  private readonly adapters: Map<string, AIProviderAdapter>;
  constructor(compatible: OpenAICompatibleAdapter) {
    this.adapters = new Map(PROVIDERS.map((provider) => [provider, compatible]));
  }
  get(provider: string) {
    const adapter = this.adapters.get(provider);
    if (!adapter) throw new AIError('INVALID_CONFIG');
    return adapter;
  }
}
