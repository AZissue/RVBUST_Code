import { Injectable } from '@nestjs/common';
import { TicketPriority } from '@prisma/client';
import { AIService } from '../ai/ai.service.js';
import { PROMPT_TEMPLATES } from '../ai/prompt-templates.js';
import { matchCustomers, matchPeople, choose, RuleBasedParser, type ParserContext, type QuickInputParser } from './quick-input.parser.js';

export interface ExtractedTicket { customerText: string; issue: string; assigneeText: string; priority: 'low' | 'medium' | 'high' | 'urgent'; deviceText: string }
export function validateExtraction(value: unknown, rawText: string): ExtractedTicket {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid object');
  const data = value as Record<string, unknown>;
  const keys = ['customerText', 'issue', 'assigneeText', 'priority', 'deviceText'];
  if (Object.keys(data).length !== keys.length || keys.some((key) => typeof data[key] !== 'string')) throw new Error('Invalid schema');
  if (!['low', 'medium', 'high', 'urgent'].includes(data.priority as string) || (data.issue as string).trim().length < 3 || (data.issue as string).length > 4000) throw new Error('Invalid content');
  if (!rawText.includes(data.issue as string)) throw new Error('Ungrounded issue');
  for (const key of ['customerText', 'assigneeText', 'deviceText']) {
    const text = data[key] as string;
    if (text.length > (key === 'deviceText' ? 100 : 200) || (text && !rawText.includes(text))) throw new Error('Ungrounded entity');
  }
  return data as unknown as ExtractedTicket;
}

@Injectable()
export class AIParser implements QuickInputParser {
  private readonly rules = new RuleBasedParser();
  constructor(private readonly ai: AIService) {}
  async parse(rawText: string, context: ParserContext) {
    const fallback = this.rules.parse(rawText, context);
    // Send only a small, relevant names-only shortlist, never IDs, contacts, serial numbers or entire customer tables.
    const customers = [...new Set([...context.customers.filter((c) => rawText.includes(c.name)).map((c) => c.name), ...fallback.customerCandidates.map((c) => c.name)])].slice(0, 20);
    const users = [...new Set([...context.users.filter((u) => rawText.includes(u.name) || (u.username && rawText.includes(u.username)) || rawText.includes(`小${u.name[0]}`) || rawText.includes(`${u.name[0]}工`)).map((u) => u.name), ...fallback.assigneeCandidates.map((u) => u.name)])].slice(0, 20);
    try {
      const response = await this.ai.chat({ userId: context.currentUserId, feature: 'quick_ticket_parser',
        messages: [{ role: 'system', content: PROMPT_TEMPLATES.quick_ticket_parser }, { role: 'user', content: JSON.stringify({ rawText, candidates: { customers, users, devices: context.deviceModels ?? [] }, priorities: ['low', 'medium', 'high', 'urgent'] }) }],
        validate: (value) => validateExtraction(value, rawText),
      });
      if (!response.success) return { ...fallback, parser: 'rule' as const, fallbackReason: response.error, requestId: response.requestId };
      const data = response.data;
      const customerCandidates = matchCustomers(data.customerText, context.customers);
      const assigneeCandidates = data.assigneeText ? matchPeople(data.assigneeText, context.users) : context.users.filter((u) => u.id === context.currentUserId).map((u) => ({ id: u.id, name: u.name, score: 1 }));
      const matchedCustomer = choose(customerCandidates, .85); const matchedAssignee = choose(assigneeCandidates, .8);
      return { ...data, rawText, title: data.issue.replace(/\s+/g, ' ').slice(0, 64), priority: data.priority.toUpperCase() as TicketPriority, customerCandidates, assigneeCandidates, matchedCustomer, matchedAssignee, assigneeDefaulted: !data.assigneeText,
        confidence: { customer: matchedCustomer?.score ?? 0, assignee: matchedAssignee?.score ?? 0 }, parser: 'ai' as const, provider: response.provider, model: response.model, requestId: response.requestId };
    } catch { return { ...fallback, parser: 'rule' as const, fallbackReason: 'AI 暂不可用' }; }
  }
}
