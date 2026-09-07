import { BadRequestException, Body, Controller, Get, Param, Post, Res, UploadedFile, UseInterceptors } from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { diskStorage } from 'multer';
import { randomUUID } from 'node:crypto';
import { extname, resolve } from 'node:path';
import type { Response } from 'express';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { UploadFileDto } from './dto/upload-file.dto.js';
import { FilesService } from './files.service.js';

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

  @Get(':id')
  async download(@CurrentUser() user: AuthUser, @Param('id') id: string, @Res() response: Response) {
    const attachment = await this.files.getForDownload(user, id);
    response.setHeader('Content-Type', attachment.mimeType);
    response.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(attachment.originalName)}`);
    return response.sendFile(attachment.storageKey, { root: resolve(process.env.UPLOAD_DIR ?? './uploads') });
  }
}

