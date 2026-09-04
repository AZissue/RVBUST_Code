import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { FilesController } from './files.controller.js';
import { FilesService } from './files.service.js';

@Module({ imports: [AuthModule], controllers: [FilesController], providers: [FilesService] })
export class FilesModule {}

