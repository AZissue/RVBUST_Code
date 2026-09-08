import { BugStatus } from '@prisma/client';
import { IsEnum, IsString, Length } from 'class-validator';

export class CreateBugDto {
  @IsString() @Length(3, 240) title!: string;
  @IsString() @Length(3, 20000) description!: string;
}

export class UpdateBugStatusDto {
  @IsEnum(BugStatus, { message: 'BUG 状态无效' }) status!: BugStatus;
}
