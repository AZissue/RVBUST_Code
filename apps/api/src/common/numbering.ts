/** 统一单号生成：{业务前缀}-YYMMDD-NNN，按本地日期当日顺序递增。
 *  并发安全依赖单号唯一索引 + 调用方捕获 P2002 重试（见 tickets/loans/repairs 创建流程）。 */
export function dateSerialPrefix(code: string): string {
  const now = new Date()
  const ymd = `${String(now.getFullYear()).slice(2)}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
  return `${code}-${ymd}-`
}

/** 由同日最大单号推导下一个顺序号；last 为 null 时从 001 开始 */
export function nextSerial(last: string | null, prefix: string): string {
  const seq = last ? Number(last.slice(prefix.length)) + 1 : 1
  return `${prefix}${String(seq).padStart(3, '0')}`
}
