import { PartialType } from '@nestjs/mapped-types';
import { WorkItemPriority, WorkItemStatus } from '@prisma/client';
import { IsArray, IsDateString, IsEnum, IsInt, IsOptional, IsString, IsUUID, Length, Max, Min } from 'class-validator';

export class CreateWorkItemDto {
  @IsString() @Length(2, 240) title!: string;
  @IsOptional() @IsString() @Length(0, 20000) description?: string;
  @IsUUID() workTypeId!: string;
  @IsOptional() @IsUUID() organizationId?: string;
  @IsOptional() @IsUUID() projectId?: string;
  @IsOptional() @IsEnum(WorkItemPriority) priority?: WorkItemPriority;
  @IsOptional() @IsEnum(WorkItemStatus) status?: WorkItemStatus;
  @IsOptional() @IsUUID() ownerId?: string;
  @IsOptional() @IsArray() @IsUUID('4', { each: true }) collaboratorIds?: string[];
  @IsOptional() @IsDateString() startDate?: string;
  @IsOptional() @IsDateString() dueDate?: string;
  @IsOptional() @IsInt() @Min(0) @Max(100) progress?: number;
  @IsOptional() @IsArray() @IsString({ each: true }) tags?: string[];
}

export class UpdateWorkItemDto extends PartialType(CreateWorkItemDto) {}
