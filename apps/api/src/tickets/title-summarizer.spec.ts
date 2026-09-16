import { describe, expect, it } from 'vitest';
import { extractModel, summarizeTitleLocally } from './title-summarizer.js';

describe('title-summarizer', () => {
  it('提取设备型号', () => {
    expect(extractModel('M2600拍摄无点云')).toBe('M2600');
    expect(extractModel('RVC 2.8 SDK 报错')).toBe('');
    expect(extractModel('')).toBe('');
  });

  it('型号 + 故障句优先，型号不在核心句时自动拼接', () => {
    const title = summarizeTitleLocally('拍摄时无点云，M2600 设备，客户已寄回检修');
    expect(title).toContain('M2600');
    expect(title).toContain('无点云');
  });

  it('多句描述选中含故障关键词的句子', () => {
    const title = summarizeTitleLocally('客户反馈现场使用中相机经常连接超时，已经持续一周了，需要尽快帮忙处理');
    expect(title).toContain('连接超时');
    expect(title.length).toBeLessThanOrEqual(40);
  });

  it('剥离开头客套词', () => {
    const title = summarizeTitleLocally('客户反馈说相机防护失效，镜头内水汽凝结');
    expect(title.startsWith('客户')).toBe(false);
    expect(title).toContain('水汽凝结');
  });

  it('无关键词时截取描述主体兜底', () => {
    const title = summarizeTitleLocally('咨询相机报价和购买流程');
    expect(title.length).toBeGreaterThanOrEqual(4);
    expect(title).toContain('咨询');
  });

  it('长句截断到 30 字以内', () => {
    const long = '相机在现场运行过程中频繁出现连接超时导致产线无法正常运转已经影响交付进度'.repeat(2);
    const title = summarizeTitleLocally(long);
    expect(title.length).toBeLessThanOrEqual(60);
  });

  it('空输入兜底', () => {
    expect(summarizeTitleLocally('')).toBe('新工单');
  });

  it('多句平分时选中含型号的真实故障句而非猜测句（S1）', () => {
    const title = summarizeTitleLocally('客户反馈：现场使用 M2600 相机拍摄3D工件时无点云输出。客户表示已重启软件并更换网线，问题依旧。现场环境为高温高湿车间，怀疑激光器散射严重。请尽快协助排查。');
    expect(title).toContain('M2600');
    expect(title).toContain('无点云');
    expect(title).not.toContain('散射');
  });

  it('否定/正常语境的关键词句减分，让位真实故障句（用例12）', () => {
    const title = summarizeTitleLocally('M2600 精度正常，M3120 点云漂移');
    expect(title).toBe('M3120 点云漂移');
  });

  it('极短故障句不被长度过滤丢弃（用例13）', () => {
    expect(summarizeTitleLocally('无点云。就三个字')).toContain('无点云');
  });

  it('剥离口语填充词（用例14）', () => {
    expect(summarizeTitleLocally('具体情况是 M2600 连接超时')).toBe('M2600 连接超时');
  });
});
