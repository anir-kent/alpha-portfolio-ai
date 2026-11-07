/** Locating an Insight's cited passage on its Report page, for highlighting.
 *
 * Matching mirrors the server's `normalise` in app/reports.py, which decided the passage was on the page when the
 * Insight was kept: curly quotes fold to straight ones, a hyphenated word wrapped across lines joins up, and every run
 * of whitespace counts as one space. It is case-sensitive. Anything else that differs means "not found verbatim". */

const WORD = /[\p{L}\p{N}_]/u;
const WHITE = /\s/u;
/** Python's \s, which the server uses: JavaScript's \s plus the information separators U+001C–U+001F and NEL. */
const isSpace = (c: string) => WHITE.test(c) || (c >= "\u001c" && c <= "\u001f") || c === "\u0085";
const FOLD: Record<string, string> = { "’": "'", "‘": "'", "“": '"', "”": '"' };

/** The normalised text, and for each of its characters the index in the original it came from. */
function normalise(text: string): { norm: string; from: number[] } {
  let norm = "";
  const from: number[] = [];
  let i = 0;
  while (i < text.length) {
    if (!isSpace(text[i])) {
      norm += FOLD[text[i]] ?? text[i];
      from.push(i);
      i += 1;
      continue;
    }
    const start = i;
    while (i < text.length && isSpace(text[i])) i += 1;
    const wrappedHyphen =
      norm.endsWith("-") &&
      norm.length > 1 &&
      WORD.test(norm[norm.length - 2]) &&
      i < text.length &&
      WORD.test(text[i]);
    if (norm.length > 0 && i < text.length && !wrappedHyphen) {
      norm += " ";
      from.push(start);
    }
  }
  return { norm, from };
}

/** The [start, end) range of `passage` in `text`, or null when it does not appear there. */
export function findPassage(text: string, passage: string): { start: number; end: number } | null {
  const needle = normalise(passage).norm;
  if (!needle) return null;
  const hay = normalise(text);
  const at = hay.norm.indexOf(needle);
  if (at < 0) return null;
  return { start: hay.from[at], end: hay.from[at + needle.length - 1] + 1 };
}
