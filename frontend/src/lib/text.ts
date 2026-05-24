export function decodeEscapedUnicode(input: string): string {
  if (!input || !/\\u[0-9a-fA-F]{4}/.test(input)) {
    return input;
  }

  try {
    return JSON.parse(`"${input.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`);
  } catch {
    return input.replace(/\\u([0-9a-fA-F]{4})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)));
  }
}

export function repairMojibake(input: string): string {
  if (!input || !/[ÃÂÆÐÑØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ]/.test(input)) {
    return input;
  }

  try {
    const bytes = Uint8Array.from(input, (char) => char.charCodeAt(0) & 0xff);
    const repaired = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return repaired;
  } catch {
    return input;
  }
}

export function normalizeText(input: string): string {
  return repairMojibake(decodeEscapedUnicode(input));
}

export function normalizeDeep<T>(value: T): T {
  if (typeof value === "string") {
    return normalizeText(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeDeep(item)) as T;
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, normalizeDeep(item)]),
    ) as T;
  }
  return value;
}
