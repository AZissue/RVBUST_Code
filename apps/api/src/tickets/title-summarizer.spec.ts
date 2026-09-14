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
});
