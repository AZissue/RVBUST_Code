import { NotificationSeverity } from '@prisma/client';
import { IsEnum, IsOptional, IsString, IsUUID, Length } from 'class-validator';

export class CreateNotificationDto {
  @IsUUID() recipientId!: string;
  @IsOptional() @IsUUID() ticketId?: string;
  @IsString() @Length(1, 80) type!: string;
  @IsOptional() @IsEnum(NotificationSeverity) severity?: NotificationSeverity;
  @IsString() @Length(1, 200) title!: string;
  @IsString() @Length(1, 4000) body!: string;
  @IsOptional() @IsString() @Length(1, 180) dedupeKey?: string;
}

