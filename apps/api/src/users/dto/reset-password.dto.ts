import { IsString, Length } from 'class-validator';

export class ResetPasswordDto {
  @IsString() @Length(10, 128) password!: string;
}
