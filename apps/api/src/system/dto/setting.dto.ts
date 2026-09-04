import { IsBoolean, IsObject, IsOptional, IsString, Length } from 'class-validator';

export class UpsertSettingDto {
  @IsString() @Length(2, 100) key!: string;
  @IsObject() value!: Record<string, unknown>;
  @IsOptional() @IsBoolean() isPublic?: boolean;
}

