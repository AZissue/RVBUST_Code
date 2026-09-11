import { IsArray, IsOptional, IsString, IsUUID, Length } from 'class-validator';

/** 在已有工单上直接添加协作人（无接受/驳回环节） */
export class CreateAssistRequestDto {
  @IsArray() @IsUUID('4', { each: true }) targetUserIds!: string[];
  @IsOptional() @IsString() @Length(0, 2000) message?: string;
}
