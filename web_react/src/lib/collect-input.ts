/** 接受中文输入习惯，始终向采集器传英文逗号分隔的非空词。 */
export function normalizeKeywords(value: string): string {
  return [...new Set(value.split(/[,，、;；\n\r]+/).map(word => word.trim()).filter(Boolean))].join(',')
}
