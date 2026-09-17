import { PartialType } from '@nestjs/mapped-types';
import { TicketCategory, TicketPriority, TicketStatus } from '@prisma/client';
import { Type } from 'class-transformer';
import { IsArray, IsBoolean, IsDateString, IsEnum, IsOptional, IsString, IsUUID, Length, ValidateNested } from 'class-validator';

/** 接续的前置工单：note 必填（2-500 字），写入前置单时间线，自动关单时同步填入其 solution */
export class ContinuationItemDto {
  @IsUUID() fromTicketId!: string;
  @IsString() @Length(2, 500) note!: string;
}

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
  /** 创建工单时邀请协助的对象（系统已有账号的内部成员），被邀请人需接受后生效 */
  @IsOptional() @IsArray() @IsUUID('4', { each: true }) assistTargetIds?: string[];
  /** 邀请协助时填写的说明 */
  @IsOptional() @IsString() @Length(0, 2000) assistMessage?: string;
  @IsOptional() @IsDateString() plannedAt?: string;
  /** 工单发生/记录时间（本地日期），决定 createdAt 与编号日期；缺省为当前时间 */
  @IsOptional() @IsDateString() occurredAt?: string;
  /** 创建时直接指定状态（补录场景），如 RESOLVED/IN_PROGRESS；客户账号忽略此字段 */
  @IsOptional() @IsEnum(TicketStatus) status?: TicketStatus;
  /** 创建工单的同时联动创建借测单（幂等，失败不阻断工单创建） */
  @IsOptional() @IsBoolean() createLinkedLoan?: boolean;
  /** 创建工单的同时联动创建维修单（幂等，失败不阻断工单创建） */
  @IsOptional() @IsBoolean() createLinkedRepair?: boolean;
  /** 接续同客户未解决工单：建立工单链，旧单时间线留痕并按 autoClose 关闭 */
  @IsOptional() @IsArray() @ValidateNested({ each: true }) @Type(() => ContinuationItemDto) continuations?: ContinuationItemDto[];
  /** 接续后同时关闭前置单（默认 true；false 时仅建立关联与时间线留痕） */
  @IsOptional() @IsBoolean() autoClose?: boolean;
  /** 前置单存在进行中借测/维修单时，将其迁移到新工单（默认 false；不迁移且未处理时关单被拦截） */
  @IsOptional() @IsBoolean() carryLinks?: boolean;
}

export class UpdateTicketDto extends PartialType(CreateTicketDto) {}

export class ChangeCreatorDto {
  @IsUUID() createdById!: string;
}

export class DeleteTicketDto {
  @IsOptional() @IsString() @Length(0, 1000) reason?: string;
}
