import { TicketPriority } from '@prisma/client';

export interface Candidate { id: string; name: string; score: number }
export interface Person { id: string; name: string; username?: string }
export interface ParserContext { customers: Person[]; users: Person[]; currentUserId: string; deviceModels?: string[] }
export type ParsedTicket = Omit<ReturnType<typeof parseQuickTicketInput>, 'priority'> & { priority: TicketPriority };
export interface QuickInputParser { parse(rawText: string, context: ParserContext): ParsedTicket | Promise<ParsedTicket> }
const clean = (s: string) => s.replace(/^[\s,，。:：;；]+|[\s,，。:：;；]+$/g, '');
const normalize = (s: string) => s.toLowerCase().replace(/有限责任公司|股份有限公司|有限公司|机器人|科技|公司|客户/g, '').replace(/\s/g, '');

export function similarity(a: string, b: string) {
  if (!a || !b) return 0;
  if (a === b) return 1;
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let diagonal = row[0]; row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const above = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, diagonal + Number(a[i - 1] !== b[j - 1]));
      diagonal = above;
    }
  }
  return 1 - row[b.length] / Math.max(a.length, b.length);
}

export function matchCustomers(text: string, customers: Person[]): Candidate[] {
  const query = normalize(text);
  if (query.length < 2) return [];
  return customers.map((c) => {
    const name = normalize(c.name);
    const score = c.name === text ? 1 : name === query ? .98 : name.includes(query) || query.includes(name) ? .9 : similarity(query, name) * .85;
    return { id: c.id, name: c.name, score };
  }).filter((c) => c.score >= .58).sort((a, b) => b.score - a.score);
}

export function matchPeople(text: string, users: Person[]): Candidate[] {
  if (!text) return [];
  const surname = text.match(/^(?:小([\u4e00-\u9fff])|([\u4e00-\u9fff])工)$/);
  return users.map((u) => ({ id: u.id, name: u.name, score: u.name === text || u.username === text ? 1 : surname && u.name.startsWith(surname[1] || surname[2]) ? .8 : similarity(text, u.name) * .8 }))
    .filter((u) => u.score >= .6).sort((a, b) => b.score - a.score);
}
export const choose = (c: Candidate[], threshold: number) => c[0] && c[0].score >= threshold && (!c[1] || c[0].score - c[1].score >= .12) ? c[0] : null;

export function parseQuickTicketInput(rawText: string, context: ParserContext) {
  let issue = clean(rawText);
  let priority: TicketPriority = TicketPriority.MEDIUM;
  // Strip explicit urgency labels, but retain factual symptoms such as 2D正常 and 产线停机.
  if (/非常紧急|紧急|客户现场停线|产线停机|马上处理/.test(issue)) priority = TicketPriority.URGENT;
  else if (/高优先级|优先处理|比较急/.test(issue)) priority = TicketPriority.HIGH;
  else if (/(?:^|[\s，,])急(?:$|[\s，,])/.test(issue)) priority = TicketPriority.URGENT;
  issue = issue.replace(/非常紧急|紧急|高优先级|优先处理|比较急|马上处理|有空处理/g, ' ')
    .replace(/(?:^|[\s，,])(普通|一般|正常|急)(?=$|[\s，,])/g, ' ');
  issue = clean(issue);
  const explicit = issue.match(/(?:指定负责人|负责人|指派给|交给)\s*[:：]?\s*([^\s，,。；;]+)/);
  let assigneeText = explicit?.[1] ?? '';
  if (explicit) issue = issue.replace(explicit[0], ' ');
  if (!assigneeText) {
    const assigned = issue.match(/(?:^|[\s，,])([^\s，,。；;]{1,20})负责(?=$|[\s，,。；;])/);
    if (assigned) { assigneeText = assigned[1]; issue = issue.replace(assigned[0], ' '); }
  }
  if (!assigneeText) {
    const known = context.users.flatMap((u) => [u.name, u.username ?? '', `小${u.name[0]}`, `${u.name[0]}工`]).filter(Boolean).sort((a, b) => b.length - a.length);
    const found = known.find((name) => issue.endsWith(name) || issue.includes(` ${name} `) || issue.includes(`，${name}`));
    if (found) { assigneeText = found; issue = issue.replace(found, ' '); }
    else {
      const tail = issue.match(/[\s，,]([\u4e00-\u9fff]{2,3})$/)?.[1];
      if (tail && /^[张王李赵刘陈杨黄吴周徐孙马朱胡郭何林高郑罗梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严赖覃洪武莫孔]/.test(tail)) { assigneeText = tail; issue = issue.slice(0, -tail.length); }
    }
  }
  issue = clean(issue);
  const deviceText = issue.match(/\b[A-Za-z]+[- ]?\d{3,}[A-Za-z0-9-]*\b/)?.[0]?.replace(/ /g, '') ?? '';
  let customerText = '';
  const fullName = context.customers.map((c) => c.name).sort((a, b) => b.length - a.length).find((name) => issue.startsWith(name));
  if (fullName) customerText = fullName;
  else {
    const head = clean(issue.split(/[A-Za-z]+[- ]?\d{3,}|[\s，,。；;]/)[0]);
    if (head && head !== issue) customerText = head;
    else {
      const prefix = context.customers.flatMap((c) => [c.name, normalize(c.name)]).filter((n) => n.length >= 2 && issue.startsWith(n)).sort((a, b) => b.length - a.length)[0];
      if (prefix) customerText = prefix;
    }
  }
  const customerCandidates = matchCustomers(customerText, context.customers);
  if (customerText) issue = clean(issue.slice(customerText.length));
  const assigneeCandidates = assigneeText ? matchPeople(assigneeText, context.users) : context.users.filter((u) => u.id === context.currentUserId).map((u) => ({ id: u.id, name: u.name, score: 1 }));
  issue = clean(issue.replace(/[\s，,]+$/g, ''));
  const matchedCustomer = choose(customerCandidates, .85);
  const matchedAssignee = choose(assigneeCandidates, .8);
  return { rawText, customerText, customerCandidates, matchedCustomer, assigneeText, assigneeCandidates, matchedAssignee, assigneeDefaulted: !assigneeText, priority, deviceText, issue,
    title: issue.replace(/拍摄(?=\s*3D)/gi, '').replace(/([A-Za-z]\d+)\s*(?=3D|2D)/g, '$1 ').replace(/\s+/g, ' ').slice(0, 64),
    confidence: { customer: matchedCustomer?.score ?? 0, assignee: matchedAssignee?.score ?? 0 } };
}

export class RuleBasedParser implements QuickInputParser { parse(rawText: string, context: ParserContext) { return parseQuickTicketInput(rawText, context); } }
export const QUICK_INPUT_PARSER = Symbol('QuickInputParser');

export function ticketSimilarity(issue: string, candidate: string, model: string, candidateModel: string, active: boolean) {
  const normalizeIssue = (s: string) => s.toLowerCase().replace(/连接不上|连接超时|无法连接|连接失败|连接不了/g, '连接异常').replace(/没有点云|无点云|点云为空/g, '无点云').replace(/\s|[，,。；;]/g, '');
  const a = normalizeIssue(issue).slice(0, 500); const b = normalizeIssue(candidate).slice(0, 500);
  const grams = (s: string) => new Set(Array.from({ length: Math.max(0, s.length - 1) }, (_, i) => s.slice(i, i + 2)));
  const x = grams(a); const y = grams(b);
  const dice = x.size + y.size ? 2 * [...x].filter((g) => y.has(g)).length / (x.size + y.size) : 0;
  const textScore = Math.max(similarity(a, b), dice);
  return Math.round(Math.min(1, .78 * textScore + (model && candidateModel.toLowerCase().includes(model.toLowerCase()) ? .17 : 0) + (active ? .05 : 0)) * 100);
}
