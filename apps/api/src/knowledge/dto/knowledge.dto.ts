import { IsString, Length, Matches } from 'class-validator';

export class KbPathQuery {
  @IsString() @Length(0, 1000)
  path!: string;
}

const NAME_PATTERN = /^[^\\/:*?"<>|]+$/;

export class SaveContentDto {
  @IsString() @Length(1, 1000)
  path!: string;

  @IsString() @Length(0, 512 * 1024)
  content!: string;
}

export class DeleteEntryDto {
  @IsString() @Length(1, 1000)
  path!: string;
}

export class MkdirDto {
  @IsString() @Length(0, 1000)
  path!: string;

  @IsString() @Length(1, 120) @Matches(NAME_PATTERN, { message: '名称包含非法字符' })
  name!: string;
}

export class RenameDto {
  @IsString() @Length(1, 1000)
  path!: string;

  @IsString() @Length(1, 120) @Matches(NAME_PATTERN, { message: '名称包含非法字符' })
  newName!: string;
}
