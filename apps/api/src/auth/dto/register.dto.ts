import { IsOptional, IsString, Length, Matches } from 'class-validator';

export class RegisterDto {
  @IsString()
  @Length(4, 30)
  @Matches(/^[a-zA-Z0-9_]+$/)
  username!: string;

  @IsString()
  @Length(10, 128)
  password!: string;

  @IsString()
  @Length(2, 100)
  name!: string;

  @IsOptional()
  @IsString()
  @Length(0, 100)
  department?: string;

  @IsOptional()
  @IsString()
  @Length(0, 40)
  phone?: string;
}
