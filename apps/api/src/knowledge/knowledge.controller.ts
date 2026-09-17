import { BadRequestException, Body, Controller, Get, Put, Post, Query, Res } from '@nestjs/common';
import type { Response } from 'express';
import { Roles } from '../auth/roles.decorator.js';
import { DeleteEntryDto, MkdirDto, RenameDto, SaveContentDto } from './dto/knowledge.dto.js';
import { KnowledgeService } from './knowledge.service.js';

/**
 * 知识库：文件系统直通（根目录由 KB_ROOT 指定，目录结构即数据源，不建表）。
 * 权限：全员（admin/support/employee）可读；编辑/删除/新建/重命名仅管理员。
 */
@Roles('admin', 'support', 'employee')
@Controller('kb')
export class KnowledgeController {
  constructor(private readonly kb: KnowledgeService) {}

  @Get('list') list(@Query('path') path?: string) { return this.kb.list(path ?? ''); }

  @Get('download') async download(@Query('path') path: string, @Res() response: Response) {
    const file = this.kb.fileInfo(path);
    await this.kb.assertFile(path);
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Cache-Control', 'private, no-store');
    response.setHeader('Content-Type', file.mime);
    response.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(file.name)}`);
    return response.sendFile(file.abs);
  }

  @Get('preview') async preview(@Query('path') path: string, @Res() response: Response) {
    const file = this.kb.fileInfo(path);
    if (file.previewKind === 'none') throw new BadRequestException('该类型不支持预览，请下载后查看');
    await this.kb.assertFile(path);
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Cache-Control', 'private, no-store');
    response.setHeader('Content-Type', file.mime);
    response.setHeader('Content-Disposition', `inline; filename*=UTF-8''${encodeURIComponent(file.name)}`);
    return response.sendFile(file.abs);
  }

  @Get('content') content(@Query('path') path: string) { return this.kb.readText(path); }

  @Roles('admin') @Put('content') save(@Body() dto: SaveContentDto) { return this.kb.saveText(dto.path, dto.content); }
  @Roles('admin') @Post('delete') remove(@Body() dto: DeleteEntryDto) { return this.kb.remove(dto.path); }
  @Roles('admin') @Post('mkdir') makeDir(@Body() dto: MkdirDto) { return this.kb.makeDir(dto.path, dto.name); }
  @Roles('admin') @Post('rename') rename(@Body() dto: RenameDto) { return this.kb.renameEntry(dto.path, dto.newName); }
}
