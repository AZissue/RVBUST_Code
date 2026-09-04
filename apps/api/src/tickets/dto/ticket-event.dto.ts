import { TicketEventType, Visibility } from '@prisma/client';
import { IsEnum, IsOptional, IsString, Length } from 'class-validator';

export class CreateTicketEventDto {
  @IsEnum(TicketEventType) type!: TicketEventType;
  @IsOptional() @IsEnum(Visibility) visibility?: Visibility;
  @IsString() @Length(1, 20000) content!: string;
}

