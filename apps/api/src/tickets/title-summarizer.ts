/**
 * 本地规则标题总结（不依赖 AI）：
 * 按标点分句 → 按「设备型号 / 故障关键词 / 长度适中 / 位置靠前」打分 → 取核心问题句 → 拼设备型号。
 * 适合工单这类模式化文本（型号 + 故障现象），作为 AI 不可用时的兜底。
 */
const FAULT_KEYWORDS = [
  '无点云', '点云缺失', '点云异常', '连接超时', '超时', '报错', '错误', '失败', '异常',
  '无法', '不能', '缺失', '损坏', '断开', '掉线', '连不上', '不识别', '识别失败',
  '误差', '漂移', '延迟', '卡顿', '闪退', '重启', '黑屏', '过热', '进水',
  '激光', '散射', '水汽', '凝结', '精度', '模糊', '裂纹', '噪音', '不稳定',
] as const;

const FILLER_PATTERN = /^(具体情况是|大概意思是|简单来说|就是说|总之|客户|用户|现场|反馈|表示|称|说|描述)[:：,，\s]*/;

const stripFiller = (clause: string): string => {
  let text = clause.trim();
  for (let i = 0; i < 3; i++) {
    const next = text.replace(FILLER_PATTERN, '').trim();
    if (next === text) break;
    text = next;
  }
  return text;
};

/** 否定/正常语境：关键词命中点前后 6 字窗口内出现这些词，说明是「精度正常/已恢复」类描述而非故障 */
const NEGATION_PATTERN = /正常|无异常|恢复|已排除|OK/;
const hasNegationContext = (clause: string): boolean =>
  FAULT_KEYWORDS.some((keyword) => {
    let from = 0;
    for (;;) {
      const i = clause.indexOf(keyword, from);
      if (i < 0) return false;
      if (NEGATION_PATTERN.test(clause.slice(Math.max(0, i - 6), i + keyword.length + 6))) return true;
      from = i + keyword.length;
    }
  });

/** 提取描述中的设备型号（如 M2600、RVC-X1），无则空串 */
export const extractModel = (text: string): string =>
  text.match(/[A-Za-z]{1,12}[- ]?\d{3,}[A-Za-z0-9-]*/)?.[0].replace(/[- ]/g, '') ?? '';

export function summarizeTitleLocally(description: string): string {
  const clean = description.replace(/\s+/g, ' ').trim();
  if (!clean) return '新工单';
  const model = extractModel(clean);
  const clauses = clean
    .split(/[。！？!?.；;，,、\n\r]/)
    .map((clause) => stripFiller(clause))
    .filter((clause) => clause.length >= 4 || FAULT_KEYWORDS.some((keyword) => clause.includes(keyword)));

  const scored = clauses.map((clause, index) => {
    const hits = FAULT_KEYWORDS.filter((keyword) => clause.includes(keyword)).length;
    const hasModel = Boolean(model && clause.includes(model));
    let score = Math.min(hits, 3) * 4;
    if (hasModel) score += 2;
    if (clause.length >= 8 && clause.length <= 40) score += 1;
    score += Math.max(0, 2 - index); // 位置靠前优先
    if (hasNegationContext(clause)) score -= 4; // 「M2600 精度正常」类否定语境减分
    return { clause, score, hits, hasModel, index };
  }).sort((a, b) => b.score - a.score
    || Number(b.hasModel) - Number(a.hasModel) // 平局：含型号的真实故障句优先于猜测性短句
    || b.hits - a.hits
    || a.index - b.index // 位置靠前优先
    || a.clause.length - b.clause.length); // 最后短句优先

  let core = scored[0]?.clause ?? '';
  if (core.length > 30) core = core.slice(0, 30);
  // 核心句已含其他型号时不再拼全局型号，避免出现 M2600M3120 这类拼接
  let title = model && core && !core.includes(model) && !extractModel(core) ? `${model}${core}` : core;
  title = title.trim();
  // 兜底：规则提取过短（纯客套/人名等）且不含故障关键词时截取描述开头
  if (title.replace(model, '').length < 4 && !FAULT_KEYWORDS.some((keyword) => title.includes(keyword))) title = clean.slice(0, 30).trim();
  return title.slice(0, 60) || '新工单';
}
