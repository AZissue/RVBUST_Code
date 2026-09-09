import { PartialType } from '@nestjs/mapped-types';
import { TicketCategory, TicketPriority, TicketStatus } from '@prisma/client';
import { IsArray, IsDateString, IsEnum, IsOptional, IsString, IsUUID, Length } from 'class-validator';

export class CreateTicketDto {
  @IsOptional() @IsString() @Length(1, 20000) rawText?: string;
  @IsOptional() @IsUUID() requestKey?: string;
  @IsUUID() organizationId!: string;
  @IsOptional() @IsUUID() contactId?: string;
  @IsOptional() @IsUUID() deviceId?: string;
  @IsOptional() @IsUUID() projectId?: string;
  @IsOptional() @IsString() @Length(0, 100) cameraModel?: string;
  @IsOptional() @IsString() @Length(0, 120) serialNumber?: string;
  @IsOptional() @IsString() @Length(0, 80) sdkVersion?: string;
  @IsOptional() @IsString() @Length(0, 4000) systemEnvironment?: string;
  @IsEnum(TicketCategory, { message: '问题分类无效' }) category!: TicketCategory;
  @IsString() @Length(3, 240) title!: string;
  @IsString() @Length(3, 20000) description!: string;
  @IsOptional() @IsEnum(TicketPriority) priority?: TicketPriority;
  @IsOptional() @IsUUID() assigneeId?: string;
  @IsOptional() @IsArray() @IsUUID('4', { each: true }) collaboratorIds?: string[];
  @IsOptional() @IsDateString() plannedAt?: string;
  /** 工单发生/记录时间（本地日期），决定 createdAt 与编号日期；缺省为当前时间 */
  @IsOptional() @IsDateString() occurredAt?: string;
  /** 创建时直接指定状态（补录场景），如 RESOLVED/IN_PROGRESS；客户账号忽略此字段 */
  @IsOptional() @IsEnum(TicketStatus) status?: TicketStatus;
}

export class UpdateTicketDto extends PartialType(CreateTicketDto) {}

export class ChangeCreatorDto {
  @IsUUID() createdById!: string;
}
