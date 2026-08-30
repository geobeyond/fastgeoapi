/**
 * The bridge between a form that speaks JSON and a document that is YAML.
 *
 * A form library takes a JSON value and gives one back. Handing its
 * output to the server would mean re-serialising the whole document from
 * a shape the form understands — and the form understands less than the
 * document contains. pygeoapi's schema does not describe `store_options`
 * or `engine_options`, declares no `additionalProperties` on providers,
 * and knows nothing of comments or key order. Saving would silently drop
 * all of it, in the one gesture that looks harmless: open, change one
 * title, save.
 *
 * So the document stays the truth. The form is given a plain value to
 * render, and what comes back is compared against what went out: only
 * the paths that actually changed are written. What the form never saw
 * is never written — by construction, not by care.
 */

import { diff3Merge } from "node-diff3";
// Split rather than an inline `type` modifier: the repository's prettier
// hook is v2.4.1 and does not parse that syntax.
import type { Document } from "yaml";
import { parseDocument } from "yaml";

/** A location inside the document: object keys and array indices. */
type Path = (string | number)[];

/**
 * The document as a plain value, for the form to render.
 *
 * `toJS` resolves aliases and drops comments, which is right here: this
 * is the throwaway view, not the thing that gets saved.
 */
export function toJSON(doc: Document): unknown {
  return doc.toJS();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Write to the document every path where `after` differs from `before`.
 *
 * Nothing else is touched. Two values that are equal are not rewritten
 * even when they are deeply equal by chance: an untouched subtree keeps
 * its comments, its anchors and its key order because nobody writes to
 * it, not because writing preserves them.
 *
 * Returns how many paths were written, which the caller needs:
 * re-emitting a document normalises indentation and escapes, so saving
 * an untouched document would produce a diff that changes nothing —
 * 122 of 227 lines on the deployment's own configuration. At zero, send
 * the text that was opened instead of serialising.
 */
export function applyDiff(
  doc: Document,
  before: unknown,
  after: unknown,
): number {
  let written = 0;
  for (const [path, value] of changes(before, after)) {
    if (value === REMOVED) {
      doc.deleteIn(path);
    } else {
      doc.setIn(path, value);
    }
    written++;
  }
  return written;
}

/** Distinguishes "set to undefined" from "no longer there". */
const REMOVED = Symbol("removed");

/**
 * Yield one entry per path that differs, deepest changes first.
 *
 * Removals come out of the walk in reverse index order for arrays, so
 * that deleting several entries does not shift the ones still to go.
 */
function* changes(
  before: unknown,
  after: unknown,
  at: Path = [],
): Generator<[Path, unknown]> {
  if (Object.is(before, after)) return;

  if (isRecord(before) && isRecord(after)) {
    for (const key of Object.keys(after)) {
      if (!(key in before)) {
        yield [[...at, key], after[key]];
      } else {
        yield* changes(before[key], after[key], [...at, key]);
      }
    }
    for (const key of Object.keys(before)) {
      if (!(key in after)) yield [[...at, key], REMOVED];
    }
    return;
  }

  if (Array.isArray(before) && Array.isArray(after)) {
    // Entry by entry, so an untouched provider keeps the keys the form
    // cannot see. Replacing the whole list would be simpler and would
    // throw those away.
    for (let i = 0; i < Math.min(before.length, after.length); i++) {
      yield* changes(before[i], after[i], [...at, i]);
    }
    for (let i = before.length; i < after.length; i++) {
      yield [[...at, i], after[i]];
    }
    for (let i = before.length - 1; i >= after.length; i--) {
      yield [[...at, i], REMOVED];
    }
    return;
  }

  if (!same(before, after)) yield [at, after];
}

/** Scalar equality, with NaN treated the way a document would treat it. */
function same(a: unknown, b: unknown): boolean {
  if (a instanceof Date && b instanceof Date)
    return a.getTime() === b.getTime();
  return Object.is(a, b) || a === b;
}

/**
 * How the document is re-emitted.
 *
 * `indentSeq: false` because pygeoapi's own configurations do not indent
 * a sequence under its key and the library does — left at the default it
 * accounts for most of the difference between a document and its own
 * re-emission. `lineWidth` is deliberately *not* changed: turning
 * wrapping off unwraps lines the author had already wrapped, which is
 * worse than the wrapping itself.
 */
const EMIT = { indentSeq: false };

/**
 * The text to save: the document that was opened, carrying the changes.
 *
 * Re-emitting a whole document normalises it — around thirteen lines of
 * churn on the deployment's own configuration, none of it meaningful.
 * Two things keep that out of the saved file.
 *
 * At zero writes the text that was opened is returned untouched, so
 * opening and saving cannot produce a diff at all.
 *
 * Otherwise the changes are *transplanted*: the same serialiser renders
 * the document before and after the edit, so the difference between
 * those two is the edit and nothing else, and a three-way merge carries
 * it into the original. Everything the operator did not touch keeps the
 * shape they gave it.
 *
 * The merge is then checked rather than trusted: a merge that came out
 * meaning something else would be far worse than a reformatted file, so
 * the plain re-emission is used whenever the two do not agree.
 */
export function serialise(
  original: string,
  doc: Document,
  written: number,
): string {
  if (written === 0) return original;

  const modified = doc.toString(EMIT);
  const base = parseDocument(original).toString(EMIT);

  const regions = diff3Merge(
    original.split("\n"),
    base.split("\n"),
    modified.split("\n"),
  );
  // On a conflict the edited side wins: the region is one the operator
  // changed, and the alternative would be to silently drop their edit.
  const merged = regions.flatMap((r) => r.ok ?? r.conflict!.b).join("\n");

  return means(merged, modified) ? merged : modified;
}

/** Whether two documents say the same thing, whatever they look like. */
function means(a: string, b: string): boolean {
  try {
    return (
      JSON.stringify(parseDocument(a).toJS()) ===
      JSON.stringify(parseDocument(b).toJS())
    );
  } catch {
    return false;
  }
}
