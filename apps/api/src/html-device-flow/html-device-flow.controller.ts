import { BadRequestException, Controller, Get, Param, ParseUUIDPipe, Post, Query, Res, UploadedFile, UseInterceptors } from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { memoryStorage } from 'multer';
import type { Response } from 'express';
import { Roles } from '../auth/roles.decorator.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthUser } from '../auth/auth.types.js';
import { HtmlDeviceFlowService } from './html-device-flow.service.js';

@Controller('html-device-flow')
@Roles('admin', 'support', 'employee')
export class HtmlDeviceFlowController {
  constructor(private readonly flow: HtmlDeviceFlowService) {}

  @Get('snapshot') snapshot() { return this.flow.snapshot(); }

  @Post('sync')
  @UseInterceptors(FileInterceptor('payload', { storage: memoryStorage(), limits: { fileSize: 20 * 1024 * 1024, files: 1 } }))
  sync(@UploadedFile() file?: Express.Multer.File) {
    if (!file) throw new BadRequestException('缺少同步数据');
    let payload: unknown;
    try { payload = JSON.parse(file.buffer.toString('utf8')); }
    catch { throw new BadRequestException('同步数据格式无效'); }
    return this.flow.sync(payload);
  }

  @Post('files')
  @UseInterceptors(FileInterceptor('file', { storage: memoryStorage(), limits: { fileSize: 10 * 1024 * 1024, files: 1 } }))
  upload(@CurrentUser() user: AuthUser, @UploadedFile() file: Express.Multer.File) { return this.flow.upload(file, user.id); }

  @Get('files/:id')
  async file(@Param('id', ParseUUIDPipe) id: string, @Query('download') download: string | undefined, @Res() response: Response) {
    const { metadata, bytes } = await this.flow.file(id);
    response.setHeader('Content-Type', metadata.mimeType);
    response.setHeader('Content-Disposition', `${download === '1' ? 'attachment' : 'inline'}; filename*=UTF-8''${encodeURIComponent(metadata.originalName)}`);
    response.setHeader('Cache-Control', 'private, no-store');
    return response.send(bytes);
  }
}
