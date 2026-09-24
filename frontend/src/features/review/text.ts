/** Code-point helpers: the contract's offsets are Python str indices, not UTF-16 units. */
export const chars = (text: string): string[] => Array.from(text);

export const slice = (text: string, start: number, end: number): string => chars(text).slice(start, end).join("");

export const codePointLength = (text: string): number => chars(text).length;
