import { BadRequestException, Body, Controller, Get, Param, Post, Query, Res, UploadedFile, UseInterceptors } from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { diskStorage } from 'multer';
import { randomUUID } from 'node:crypto';
import { extname, resolve } from 'node:path';
import type { Response } from 'express';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { UploadFileDto } from './dto/upload-file.dto.js';
import { FilesService } from './files.service.js';
import { LoanPhotoDto } from './dto/loan-photo.dto.js';
import { plainToInstance } from 'class-transformer';
import { validate } from 'class-validator';
import { unlink } from 'node:fs/promises';

const allowedTypes = new Set(['image/jpeg', 'image/png', 'image/webp', 'text/plain', 'application/pdf', 'application/zip', 'application/x-zip-compressed']);

const uploadOptions = {
  storage: diskStorage({
    destination: resolve(process.env.UPLOAD_DIR ?? './uploads'),
    filename: (_request: unknown, file: Express.Multer.File, callback: (error: Error | null, filename: string) => void) => callback(null, `${randomUUID()}${extname(file.originalname).toLowerCase()}`),
  }),
  limits: { fileSize: Math.max(1, Number(process.env.MAX_UPLOAD_MB ?? 10)) * 1024 * 1024, files: 1 },
  fileFilter: (_request: unknown, file: Express.Multer.File, callback: (error: Error | null, accept: boolean) => void) => callback(allowedTypes.has(file.mimetype) ? null : new BadRequestException('不支持的文件类型'), allowedTypes.has(file.mimetype)),
};

@Controller('files')
export class FilesController {
  constructor(private readonly files: FilesService) {}

  @Post('loan-items/:itemId')
  @UseInterceptors(FileInterceptor('file', uploadOptions))
  async uploadLoan(@CurrentUser() user: AuthUser, @Param('itemId') itemId: string, @UploadedFile() file: Express.Multer.File, @Body() body: Record<string, unknown>) {
    if (!file) throw new BadRequestException('请选择图片');
    const dto = plainToInstance(LoanPhotoDto, body);
    if ((await validate(dto, { whitelist: true, forbidNonWhitelisted: true })).length || !/^[0-9a-f-]{36}$/i.test(itemId)) {
      await unlink(file.path).catch(() => {});
      throw new BadRequestException('图片类别或上传标识无效');
    }
    return this.files.registerLoanPhoto(user, itemId, file, dto);
  }

  @Post('tickets/:ticketId')
  @UseInterceptors(FileInterceptor('file', uploadOptions))
  upload(@CurrentUser() user: AuthUser, @Param('ticketId') ticketId: string, @UploadedFile() file: Express.Multer.File, @Body() dto: UploadFileDto) {
    if (!file) throw new BadRequestException('请选择文件');
    return this.files.register(user, ticketId, file, dto.visibility);
  }

  @Post('repairs/:repairOrderId')
  @UseInterceptors(FileInterceptor('file', uploadOptions))
  uploadRepair(@CurrentUser() user: AuthUser, @Param('repairOrderId') repairOrderId: string, @UploadedFile() file: Express.Multer.File) {
    if (!file) throw new BadRequestException('请选择文件');
    return this.files.registerRepair(user, repairOrderId, file);
  }

  @Post('bugs/:bugReportId')
  @UseInterceptors(FileInterceptor('file', uploadOptions))
  uploadBug(@Param('bugReportId') bugReportId: string, @UploadedFile() file: Express.Multer.File) {
    if (!file) throw new BadRequestException('请选择文件');
    return this.files.registerBug(bugReportId, file);
  }

  @Get(':id')
  async download(@CurrentUser() user: AuthUser, @Param('id') id: string, @Query('preview') preview: string | undefined, @Res() response: Response) {
    const attachment = await this.files.getForDownload(user, id);
    response.setHeader('Content-Type', attachment.mimeType);
    const inline = preview === '1' && ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'].includes(attachment.mimeType);
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Cache-Control', 'private, no-store');
    response.setHeader('Content-Disposition', `${inline ? 'inline' : 'attachment'}; filename*=UTF-8''${encodeURIComponent(attachment.originalName)}`);
    return response.sendFile(attachment.storageKey, { root: resolve(process.env.UPLOAD_DIR ?? './uploads') });
  }
}
