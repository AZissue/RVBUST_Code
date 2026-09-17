import { BadRequestException, ConflictException, ForbiddenException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { existsSync, realpathSync } from 'node:fs';
import { copyFile, mkdir, readdir, readFile, rename, stat, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve as resolvePath, sep } from 'node:path';
import { randomUUID } from 'node:crypto';

export type KbKind = 'image' | 'pdf' | 'text' | 'video' | 'audio' | 'none';

const IMAGE_EXTS = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp']);
const PDF_EXTS = new Set(['pdf']);
const TEXT_EXTS = new Set(['txt', 'md', 'log', 'json', 'yaml', 'yml', 'csv', 'ini', 'conf', 'py', 'ts', 'js', 'sh', 'c', 'cpp', 'java']);
const VIDEO_EXTS = new Set(['mp4', 'webm', 'mov']);
const AUDIO_EXTS = new Set(['mp3', 'wav', 'm4a']);

const MIME_BY_EXT: Record<string, string> = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif', bmp: 'image/bmp',
  pdf: 'application/pdf',
  mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime',
  mp3: 'audio/mpeg', wav: 'audio/wav', m4a: 'audio/mp4',
  txt: 'text/plain; charset=utf-8', md: 'text/plain; charset=utf-8', log: 'text/plain; charset=utf-8',
  json: 'application/json; charset=utf-8', yaml: 'text/plain; charset=utf-8', yml: 'text/plain; charset=utf-8',
  csv: 'text/plain; charset=utf-8', ini: 'text/plain; charset=utf-8', conf: 'text/plain; charset=utf-8',
  py: 'text/plain; charset=utf-8', ts: 'text/plain; charset=utf-8', js: 'text/plain; charset=utf-8',
  sh: 'text/plain; charset=utf-8', c: 'text/plain; charset=utf-8', cpp: 'text/plain; charset=utf-8', java: 'text/plain; charset=utf-8',
};

const extOf = (name: string) => {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
};

export const kindOf = (name: string): KbKind => {
  const ext = extOf(name);
  if (IMAGE_EXTS.has(ext)) return 'image';
  if (PDF_EXTS.has(ext)) return 'pdf';
  if (TEXT_EXTS.has(ext)) return 'text';
  if (VIDEO_EXTS.has(ext)) return 'video';
  if (AUDIO_EXTS.has(ext)) return 'audio';
  return 'none';
};

export interface KbEntry {
  name: string;
  kind: 'dir' | 'file';
  size: number;
  modifiedAt: string;
  previewKind: KbKind;
  editable: boolean;
}

export interface KbListResult {
  path: string;
  parent: string | null;
  breadcrumbs: { name: string; path: string }[];
  entries: KbEntry[];
}

@Injectable()
export class KnowledgeService {
  private readonly logger = new Logger(KnowledgeService.name);

  private get root() { return resolvePath(process.env.KB_ROOT ?? './kb-data'); }
  private get editMaxBytes() { return Math.max(1, Number(process.env.KB_EDIT_MAX_KB ?? 512)) * 1024; }
  private get historyDir() { return process.env.KB_HISTORY_DIR ?? '.history'; }
  private get trashDir() { return process.env.KB_TRASH_DIR ?? '.trash'; }

  /** 确保根目录存在（本地默认 ./kb-data，服务器由 KB_ROOT 指向共享目录） */
  async ensureRoot() {
    await mkdir(this.root, { recursive: true }).catch((error) => this.logger.error(`知识库根目录创建失败：${(error as Error).message}`));
  }

  /**
   * 路径穿越防护：解析后校验 + realpath 校验（防符号链接逃逸）。
   * 同时禁止进入 .trash / .history 元目录。
   */
  private resolveExisting(userPath: string): { abs: string; rel: string } {
    const cleaned = (userPath || '').replace(/\\/g, '/');
    if (cleaned.includes('\0')) throw new BadRequestException('非法路径');
    const abs = resolvePath(this.root, cleaned || '.');
    const rel = relative(this.root, abs);
    if (rel.startsWith('..') || isAbsolute(rel)) throw new ForbiddenException('非法路径');
    const segments = rel.split(sep).filter(Boolean);
    if (segments.some((seg) => seg === this.trashDir || seg === this.historyDir)) throw new ForbiddenException('非法路径');
    let real: string;
    try { real = realpathSync(abs); } catch { throw new NotFoundException('路径不存在'); }
    const relReal = relative(realpathSync(this.root), real);
    if (relReal.startsWith('..') || isAbsolute(relReal)) throw new ForbiddenException('非法路径');
    return { abs: real, rel: relative(realpathSync(this.root), real).split(sep).join('/') };
  }

  /** 写操作的新叶子节点：父目录必须存在且在根内，叶子可不存在 */
  private resolveLeaf(parentPath: string, name: string) {
    this.assertName(name);
    const { abs: parentAbs } = this.resolveExisting(parentPath || '');
    const abs = join(parentAbs, name);
    if (existsSync(abs)) {
      const real = realpathSync(abs);
      const relReal = relative(realpathSync(this.root), real);
      if (relReal.startsWith('..') || isAbsolute(relReal)) throw new ForbiddenException('非法路径');
    }
    return abs;
  }

  private assertName(name: string) {
    if (!name || name === '.' || name === '..' || name.startsWith('.')) throw new BadRequestException('名称不合法（不允许隐藏文件/目录）');
    if (/[\\/:*?"<>|]/.test(name)) throw new BadRequestException('名称包含非法字符');
  }

  async list(userPath: string): Promise<KbListResult> {
    const { abs, rel } = this.resolveExisting(userPath);
    const info = await stat(abs).catch(() => { throw new NotFoundException('路径不存在'); });
    if (!info.isDirectory()) throw new BadRequestException('该路径不是目录');
    const dirents = await readdir(abs, { withFileTypes: true });
    const entries: KbEntry[] = [];
    for (const dirent of dirents) {
      if (dirent.name.startsWith('.')) continue;
      const full = join(abs, dirent.name);
      const st = await stat(full).catch(() => null);
      if (!st) continue;
      const previewKind = dirent.isDirectory() ? 'none' : kindOf(dirent.name);
      entries.push({
        name: dirent.name,
        kind: dirent.isDirectory() ? 'dir' : 'file',
        size: st.size,
        modifiedAt: st.mtime.toISOString(),
        previewKind,
        editable: previewKind === 'text' && st.size <= this.editMaxBytes,
      });
    }
    entries.sort((a, b) => (a.kind === b.kind ? a.name.localeCompare(b.name, 'zh-CN') : a.kind === 'dir' ? -1 : 1));
    const breadcrumbs = rel ? rel.split('/').map((seg, index, arr) => ({ name: seg, path: arr.slice(0, index + 1).join('/') })) : [];
    return { path: rel, parent: rel ? breadcrumbs[breadcrumbs.length - 2]?.path ?? '' : null, entries, breadcrumbs } as KbListResult;
  }

  /** 下载/预览前置：解析路径并确认是文件，返回文件名与绝对路径 */
  private resolveFile(userPath: string) {
    if (!userPath) throw new BadRequestException('缺少文件路径');
    const { abs } = this.resolveExisting(userPath);
    return abs;
  }

  fileInfo(userPath: string) {
    const abs = this.resolveFile(userPath);
    const name = abs.split(sep).pop()!;
    const ext = extOf(name);
    return { abs, name, ext, mime: MIME_BY_EXT[ext] ?? 'application/octet-stream', previewKind: kindOf(name) };
  }

  async assertFile(userPath: string) {
    const abs = this.resolveFile(userPath);
    const info = await stat(abs).catch(() => { throw new NotFoundException('文件不存在'); });
    if (!info.isFile()) throw new BadRequestException('该路径不是文件');
    return abs;
  }

  async readText(userPath: string) {
    const { abs, name } = (() => { const f = this.fileInfo(userPath); return { abs: f.abs, name: f.name }; })();
    if (kindOf(name) !== 'text') throw new BadRequestException('该文件类型不支持文本读取');
    const info = await stat(abs).catch(() => { throw new NotFoundException('文件不存在'); });
    if (!info.isFile()) throw new BadRequestException('该路径不是文件');
    if (info.size > this.editMaxBytes) throw new BadRequestException(`文件超过可编辑大小上限（${Math.round(this.editMaxBytes / 1024)} KB）`);
    const content = await readFile(abs, 'utf8');
    return { content, size: info.size, editable: true };
  }

  async saveText(userPath: string, content: string) {
    const file = this.fileInfo(userPath);
    if (file.previewKind !== 'text') throw new BadRequestException('仅白名单内的文本类型可编辑，禁止保存为 html/svg 等可渲染文件');
    if (!TEXT_EXTS.has(file.ext)) throw new BadRequestException('该扩展名不允许网页编辑');
    const bytes = Buffer.byteLength(content, 'utf8');
    if (bytes > this.editMaxBytes) throw new BadRequestException(`内容超过可编辑大小上限（${Math.round(this.editMaxBytes / 1024)} KB）`);
    await this.assertFile(userPath);
    // 写前备份到 .history/<相对路径>.<时间戳>
    const { rel } = this.resolveExisting(userPath);
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const backup = join(this.root, this.historyDir, `${rel}.${stamp}`);
    await mkdir(join(this.root, this.historyDir, rel.split('/').slice(0, -1).join(sep) || '.'), { recursive: true });
    await copyFile(file.abs, backup).catch((error) => this.logger.warn(`知识库备份失败（${rel}）：${(error as Error).message}`));
    // 原子写入：临时文件 + rename 覆盖
    const tmp = join(file.abs + `.tmp-${randomUUID()}`);
    try {
      await writeFile(tmp, content, { encoding: 'utf8', flag: 'wx' });
      await rename(tmp, file.abs);
    } catch (error) {
      await rename(tmp, file.abs).catch(() => {});
      throw error;
    }
    return { success: true, size: bytes };
  }

  async remove(userPath: string) {
    const { abs, rel } = this.resolveExisting(userPath);
    if (!rel) throw new BadRequestException('不能删除知识库根目录');
    const info = await stat(abs).catch(() => { throw new NotFoundException('路径不存在'); });
    let target = join(this.root, this.trashDir, rel);
    if (existsSync(target)) target = `${target}.${Date.now()}`;
    await mkdir(join(this.root, this.trashDir, rel.split('/').slice(0, -1).join(sep) || '.'), { recursive: true });
    await rename(abs, target);
    this.logger.log(`知识库删除：${rel} → ${this.trashDir}（${info.isDirectory() ? '目录' : '文件'}）`);
    return { success: true, movedTo: `${this.trashDir}/${rel}` };
  }

  async makeDir(parentPath: string, name: string) {
    const abs = this.resolveLeaf(parentPath || '', name);
    if (existsSync(abs)) throw new ConflictException('同名条目已存在');
    await mkdir(abs);
    return { success: true };
  }

  async renameEntry(userPath: string, newName: string) {
    const { abs, rel } = this.resolveExisting(userPath);
    if (!rel) throw new BadRequestException('不能重命名知识库根目录');
    this.assertName(newName);
    const dest = join(abs, '..', newName);
    if (existsSync(dest)) throw new ConflictException('同名条目已存在');
    await rename(abs, dest);
    return { success: true };
  }
}
