import { mkdtemp, mkdir, readFile, readdir, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ForbiddenException, NotFoundException } from '@nestjs/common';
import { KnowledgeService, kindOf } from './knowledge.service.js';

describe('KnowledgeService', () => {
  let root: string;
  let outside: string;
  let service: KnowledgeService;

  beforeEach(async () => {
    root = await mkdtemp(join(tmpdir(), 'kb-root-'));
    outside = await mkdtemp(join(tmpdir(), 'kb-out-'));
    process.env.KB_ROOT = root;
    process.env.KB_EDIT_MAX_KB = '4';
    service = new KnowledgeService();
    await service.ensureRoot();
  });

  afterEach(() => {
    delete process.env.KB_ROOT;
    delete process.env.KB_EDIT_MAX_KB;
  });

  const seed = async () => {
    await mkdir(join(root, '01_手册'), { recursive: true });
    await writeFile(join(root, '01_手册', '参数.txt'), 'hello kb');
    await writeFile(join(root, 'note.md'), '# 标题');
    await writeFile(join(root, 'big.txt'), 'x'.repeat(8192));
    await writeFile(join(root, 'page.html'), '<script>alert(1)</script>');
    await writeFile(join(root, 'movie.mp4'), 'fake');
    await writeFile(join(root, '.hidden'), 'secret');
  };

  it('kindOf 白名单分类', () => {
    expect(kindOf('a.JPG')).toBe('image');
    expect(kindOf('a.pdf')).toBe('pdf');
    expect(kindOf('a.md')).toBe('text');
    expect(kindOf('a.MP4')).toBe('video');
    expect(kindOf('a.mp3')).toBe('audio');
    expect(kindOf('a.html')).toBe('none');
    expect(kindOf('a.svg')).toBe('none');
    expect(kindOf('a.zip')).toBe('none');
  });

  it('list 列目录：目录在前、隐藏文件不显示、面包屑正确', async () => {
    await seed();
    const top = await service.list('');
    const names = top.entries.map((e) => e.name);
    expect(names).toContain('01_手册');
    expect(names).toContain('note.md');
    expect(names).not.toContain('.hidden');
    expect(top.entries[0].kind).toBe('dir');
    expect(top.breadcrumbs).toEqual([]);
    const sub = await service.list('01_手册');
    expect(sub.parent).toBe('');
    expect(sub.breadcrumbs).toEqual([{ name: '01_手册', path: '01_手册' }]);
    expect(sub.entries[0]).toMatchObject({ name: '参数.txt', previewKind: 'text', editable: true });
    expect(top.entries.find((e) => e.name === 'big.txt')!.editable).toBe(false); // 超过 4KB
  });

  it('路径穿越被拒绝', async () => {
    await seed();
    await expect(service.list('../../etc')).rejects.toThrow(ForbiddenException);
    await expect(service.list('01_手册/../../outside')).rejects.toThrow(ForbiddenException);
    await expect(service.list('.trash/x')).rejects.toThrow(ForbiddenException);
    await expect(service.list('.history/x')).rejects.toThrow(ForbiddenException);
    expect(() => service.fileInfo('../outside.txt')).toThrow(ForbiddenException);
  });

  it('不存在路径返回 404', async () => {
    await expect(service.list('nope')).rejects.toBeInstanceOf(NotFoundException);
    expect(() => service.fileInfo('nope.txt')).toThrow(NotFoundException);
  });

  it('readText 仅白名单文本且限大小', async () => {
    await seed();
    expect((await service.readText('01_手册/参数.txt')).content).toBe('hello kb');
    await expect(service.readText('movie.mp4')).rejects.toThrow('不支持文本读取');
    await expect(service.readText('big.txt')).rejects.toThrow('超过可编辑大小上限');
  });

  it('saveText：备份到 .history、内容原子覆盖、拒绝 html', async () => {
    await seed();
    const result = await service.saveText('01_手册/参数.txt', 'updated');
    expect(result.size).toBe(7);
    expect(await readFile(join(root, '01_手册', '参数.txt'), 'utf8')).toBe('updated');
    const historyDir = join(root, '.history', '01_手册');
    const backups = await readdir(historyDir);
    expect(backups).toHaveLength(1);
    expect(await readFile(join(historyDir, backups[0]), 'utf8')).toBe('hello kb');
    await expect(service.saveText('page.html', 'x')).rejects.toThrow('仅白名单内的文本类型可编辑');
    await expect(service.saveText('01_手册/参数.txt', 'y'.repeat(8192))).rejects.toThrow('超过可编辑大小上限');
  });

  it('remove 移入 .trash 且可恢复命名', async () => {
    await seed();
    const moved = await service.remove('note.md');
    expect(moved.movedTo).toBe('.trash/note.md');
    await expect(stat(join(root, 'note.md'))).rejects.toThrow();
    expect(await readFile(join(root, '.trash', 'note.md'), 'utf8')).toBe('# 标题');
    await expect(service.remove('')).rejects.toThrow('不能删除知识库根目录');
  });

  it('mkdir 校验名称，rename 拒绝覆盖', async () => {
    await seed();
    await service.makeDir('', '新目录');
    expect((await stat(join(root, '新目录'))).isDirectory()).toBe(true);
    await expect(service.makeDir('', '新目录')).rejects.toThrow('同名条目已存在');
    await expect(service.makeDir('', '..')).rejects.toThrow('名称不合法');
    await expect(service.makeDir('', 'a/b')).rejects.toThrow();
    await service.renameEntry('新目录', ' renamed ');
    expect((await stat(join(root, ' renamed '))).isDirectory()).toBe(true);
    await expect(service.renameEntry(' renamed ', '01_手册')).rejects.toThrow('同名条目已存在');
  });

  it('符号链接逃逸被拒绝', async () => {
    await mkdir(join(outside, 'secret'), { recursive: true });
    await writeFile(join(outside, 'secret', 'leak.txt'), 'leak');
    try { await symlink(join(outside, 'secret'), join(root, 'link')); } catch { return; } // 无权限创建软链时跳过
    expect(() => service.list('link')).toThrow(ForbiddenException);
    expect(() => service.fileInfo('link/leak.txt')).toThrow(ForbiddenException);
  });

  it('KB_ROOT 通过环境变量切换', () => {
    expect(resolve(process.env.KB_ROOT!)).toBe(root);
  });
});
