import { readFile } from 'node:fs/promises';
import { PDFDocument, rgb, type PDFFont } from 'pdf-lib';
import fontkit from '@pdf-lib/fontkit';
import type { ReturnFormDto } from './dto/return-form.dto.js';

function linesFor(text: string, font: PDFFont, size: number, width: number) {
  const lines: string[] = [];
  for (const paragraph of text.replace(/\r/g, '').split('\n')) {
    let line = '';
    for (const char of paragraph) {
      if (line && font.widthOfTextAtSize(line + char, size) > width) { lines.push(line); line = ''; }
      line += char;
    }
    lines.push(line);
  }
  return lines;
}

export async function createReturnPdf(form: ReturnFormDto, symptom: string, repairNo: string) {
  const pdf = await PDFDocument.load(await readFile(new URL('../../assets/repair-return-template.pdf', import.meta.url)));
  pdf.registerFontkit(fontkit);
  const font = await pdf.embedFont(await readFile(new URL('../../assets/NotoSansSC-Regular.ttf', import.meta.url)), { subset: false });
  const page = pdf.getPages()[0];
  const overflow: { label: string; text: string }[] = [];
  const field = (label: string, text: string, x: number, top: number, width: number, height: number) => {
    const size = 10;
    let lines = linesFor(text, font, size, width - 12);
    if (lines.length * 14 > height - 8) { overflow.push({ label, text }); lines = ['内容较长，详见附页']; }
    page.drawRectangle({ x: x + 1, y: page.getHeight() - top - height + 1, width: width - 2, height: height - 2, color: rgb(1, 1, 1) });
    lines.forEach((line, i) => page.drawText(line, { x: x + 6, y: page.getHeight() - top - 8 - size - i * 14, size, font }));
  };
  field('报修日期', form.reportedAt.slice(0, 10), 687, 103, 85, 27);
  field('报修单位名称', form.companyName, 172, 137, 600, 67);
  field('报修人', form.reporterName, 172, 205, 228, 33);
  field('报修人电话', form.reporterPhone, 500, 205, 272, 33);
  field('报修设备 SN', form.serialNumber, 172, 238, 228, 34);
  field('外观情况', form.appearance, 500, 238, 272, 34);
  field('报修原因', symptom, 172, 272, 600, 68);
  field('回寄地址及联系人', form.returnAddress, 172, 340, 600, 34);
  field('设备方销售', form.salesContact, 172, 374, 228, 42);
  field('设备方售后', form.afterSalesContact, 500, 374, 272, 42);
  page.drawText(repairNo, { x: 72, y: 42, font, size: 9 });
  for (const item of overflow) {
    const lines = linesFor(item.text, font, 11, 700);
    for (let offset = 0; offset < lines.length; offset += 27) {
      const extra = pdf.addPage([841.8, 595.4]);
      extra.drawText(`返厂维修单附页 / ${repairNo} / ${item.label}`, { x: 60, y: 545, font, size: 14 });
      lines.slice(offset, offset + 27).forEach((line, i) => extra.drawText(line, { x: 60, y: 512 - i * 16, font, size: 11 }));
    }
  }
  pdf.setTitle(`返厂维修单 ${repairNo}`);
  return pdf.save();
}
