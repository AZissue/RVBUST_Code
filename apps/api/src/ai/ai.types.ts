export const FEATURES = {
  quick_ticket_parser: '快速工单语义解析', work_record_summary: '工作记录整理',
  daily_report: '日报生成', weekly_report: '周报生成', monthly_report: '月报生成',
  ai_assistant: 'AI 助手', knowledge_qa: '知识库问答',
} as const;
export type Feature = keyof typeof FEATURES;
export const PROVIDERS = ['deepseek', 'kimi', 'openai', 'openai-compatible'] as const;
export interface Message { role: 'system' | 'user' | 'assistant'; content: string }
export interface Usage { promptTokens: number | null; completionTokens: number | null; totalTokens: number | null }
export interface AdapterConfig {
  baseUrl: string; apiKey: string; defaultModel: string; temperature: number; maxTokens: number;
  timeout: number; omitTemperature: boolean; jsonMode: boolean; tokenParameter: string;
}
export interface ChatInput { messages: Message[]; json: boolean }
export interface AdapterResponse { content: string; usage: Usage }
export interface AIProviderAdapter {
  validateConfig(config: AdapterConfig): void;
  chat(config: AdapterConfig, input: ChatInput, signal: AbortSignal): Promise<AdapterResponse>;
  testConnection(config: AdapterConfig, signal: AbortSignal): Promise<AdapterResponse>;
  listModels(config: AdapterConfig, signal: AbortSignal): Promise<string[]>;
}
export const ERRORS = {
  NOT_CONFIGURED: '未配置默认 AI，请在系统设置中选择', DISABLED: 'AI Provider 已停用',
  KEY_MISSING: '未配置 API Key', KEY_UNAVAILABLE: '后端加密密钥缺失或不匹配，请联系管理员',
  KEY_EXCHANGE: '密钥安全提交失败，请重新输入并保存（服务可能已重启）',
  AUTH: '401 API Key 无效', FORBIDDEN: '403 权限不足', NOT_FOUND: '404 模型或 Base URL 错误',
  RATE_LIMIT: '429 请求限流或额度不足', TIMEOUT: '请求超时', NETWORK: '网络连接失败',
  PROVIDER_ERROR: '模型服务暂时不可用', INVALID_CONFIG: '配置无效，请检查地址和模型参数',
  UNSAFE_URL: '地址不安全；内网接口须由管理员在后端加入允许列表',
  INVALID_OUTPUT: '模型返回格式不符合要求', BUSY: 'AI 请求繁忙，请稍后重试',
} as const;
export type ErrorCode = keyof typeof ERRORS;
export class AIError extends Error {
  constructor(public readonly code: ErrorCode, public readonly usage?: Usage) { super(ERRORS[code]); }
}
export const safeError = (e: unknown) => e instanceof AIError ? e : new AIError('PROVIDER_ERROR');
