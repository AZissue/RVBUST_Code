export function splitWorklogDrafts(rawText: string) {
  return rawText.split(/[。；;\n]+/).map((value) => value.trim()).filter(Boolean)
}
