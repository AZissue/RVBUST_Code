import { Injectable } from '@nestjs/common';
import { AITransport } from './ai.transport.js';
import { AIError, type AdapterConfig, type AIProviderAdapter, type ChatInput, type AdapterResponse } from './ai.types.js';

@Injectable()
export class OpenAICompatibleAdapter implements AIProviderAdapter {
  constructor(private readonly transport: AITransport) {}
  validateConfig(config: AdapterConfig) {
    this.transport.validateUrl(config.baseUrl);
    if (!config.apiKey) throw new AIError('KEY_MISSING');
    if (!config.defaultModel || !['max_tokens', 'max_completion_tokens'].includes(config.tokenParameter)) throw new AIError('INVALID_CONFIG');
  }
  async chat(config: AdapterConfig, input: ChatInput, signal: AbortSignal): Promise<AdapterResponse> {
    this.validateConfig(config);
    const response = await this.transport.request(config.baseUrl, 'chat/completions', config.apiKey, {
      model: config.defaultModel, messages: input.messages, stream: false,
      [config.tokenParameter]: config.maxTokens,
      ...(config.omitTemperature ? {} : { temperature: config.temperature }),
      ...(input.json && config.jsonMode ? { response_format: { type: 'json_object' } } : {}),
    }, signal) as { choices?: Array<{ message?: { content?: unknown }; finish_reason?: string }>; usage?: Record<string, unknown> } | null;
    const choice = response?.choices?.[0];
    if (JSON.stringify(response).includes(config.apiKey)) throw new AIError('INVALID_OUTPUT');
    if (typeof choice?.message?.content !== 'string' || !choice.message.content.trim() || choice.finish_reason !== 'stop') throw new AIError('INVALID_OUTPUT');
    const token = (key: string) => { const n = response?.usage?.[key]; return typeof n === 'number' && Number.isInteger(n) && n >= 0 && n <= 2147483647 ? n : null; };
    return { content: choice.message.content, usage: { promptTokens: token('prompt_tokens'), completionTokens: token('completion_tokens'), totalTokens: token('total_tokens') } };
  }
  testConnection(config: AdapterConfig, signal: AbortSignal) {
    return this.chat({ ...config, maxTokens: Math.min(config.maxTokens, 1024) }, { messages: [{ role: 'user', content: 'Return exactly this JSON object: {"ok":true}' }], json: true }, signal);
  }
  async listModels(config: AdapterConfig, signal: AbortSignal) {
    this.transport.validateUrl(config.baseUrl);
    if (!config.apiKey) throw new AIError('KEY_MISSING');
    const response = await this.transport.request(config.baseUrl, 'models', config.apiKey, undefined, signal) as { data?: Array<{ id?: unknown }> } | null;
    if (!Array.isArray(response?.data)) throw new AIError('INVALID_OUTPUT');
    return [...new Set(response.data.map((m) => m?.id).filter((id): id is string => typeof id === 'string' && !id.includes(config.apiKey) && /^[a-zA-Z0-9][a-zA-Z0-9_./:@+-]{0,159}$/.test(id)))].slice(0, 300);
  }
}
