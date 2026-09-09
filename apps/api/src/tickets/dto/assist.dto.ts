import { IsArray, IsOptional, IsString, IsUUID, Length } from 'class-validator';

/** 在已有工单上创建协助（邀请）请求 */
export class CreateAssistRequestDto {
  @IsArray() @IsUUID('4', { each: true }) targetUserIds!: string[];
  @IsOptional() @IsString() @Length(0, 2000) message?: string;
}

/** 被邀请人驳回协助请求时填写的意见 */
export class RejectAssistRequestDto {
  @IsString() @Length(1, 1000) reason!: string;
}
