import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { LoansModule } from '../loans/loans.module.js';
import { RepairsModule } from '../repairs/repairs.module.js';
import { LinkageService } from './linkage.service.js';

/** 工单 ↔ 借测/维修联动编排：复用 loans/repairs 的建单逻辑，loans/repairs 模块互相不感知 */
@Module({ imports: [AuthModule, LoansModule, RepairsModule], providers: [LinkageService], exports: [LinkageService] })
export class LinkageModule {}
