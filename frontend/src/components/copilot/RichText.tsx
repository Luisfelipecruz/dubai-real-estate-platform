import { Fragment } from "react";

/**
 * The smallest possible renderer for the inline markdown the model actually emits.
 *
 * ── Why this exists ───────────────────────────────────────────────────────
 *
 * Every answer came out of the model with its emphasis intact and reached the screen as
 * literal punctuation: `There are **35,577** villa transactions`. On the one line the
 * whole product is built around. The model is not being asked to stop — bolding the
 * figure is the correct instinct and the system prompt encourages it — so the fix belongs
 * on the rendering side.
 *
 * ── Why not a markdown library ────────────────────────────────────────────
 *
 * Because the input is untrusted. It is model output, and the model has just read tool
 * results built from user-supplied area names. A general markdown renderer brings link
 * and image syntax with it, and the usual way to render its output is
 * `dangerouslySetInnerHTML`, which is how `[x](javascript:…)` becomes a live link. This
 * returns React nodes and never HTML, so there is no injection surface at all: the worst
 * a malformed answer can do is render its own asterisks, which is exactly what happens
 * today.
 *
 * ── What it deliberately does NOT do ──────────────────────────────────────
 *
 * No headings, lists, tables, links or block elements. The answers are one to four
 * sentences of prose with a bolded figure. Supporting block markdown would mean deciding
 * how a model-generated table renders next to a verified number, and that is a question
 * worth answering on purpose rather than by importing a dependency.
 */

/** Inline `**bold**` and `` `code` ``, in order, without a regex over the whole string. */
export function RichText({ text }: { text: string }) {
  return <>{parse(text).map((n, i) => <Fragment key={i}>{n}</Fragment>)}</>;
}

type Node = string | React.ReactElement;

export function parse(text: string): Node[] {
  const out: Node[] = [];
  let buffer = "";
  let i = 0;

  const flush = () => {
    if (buffer) { out.push(buffer); buffer = ""; }
  };

  while (i < text.length) {
    const bold = text.startsWith("**", i);
    const code = text[i] === "`";

    if (bold || code) {
      const marker = bold ? "**" : "`";
      const close = text.indexOf(marker, i + marker.length);
      // An unmatched marker is NOT an error and must not eat the rest of the answer.
      // It is punctuation the model meant literally, so it renders as itself.
      if (close === -1) {
        buffer += marker;
        i += marker.length;
        continue;
      }
      const inner = text.slice(i + marker.length, close);
      // `****` and `` `` `` — an empty span is the model stuttering, not emphasis.
      if (inner.length === 0) {
        buffer += marker + marker;
        i = close + marker.length;
        continue;
      }
      flush();
      out.push(
        bold ? (
          <strong className="font-semibold">{inner}</strong>
        ) : (
          <code className="rounded bg-[--muted] px-1 py-0.5 font-mono text-[0.9em]">
            {inner}
          </code>
        ),
      );
      i = close + marker.length;
      continue;
    }

    buffer += text[i];
    i += 1;
  }

  flush();
  return out;
}
