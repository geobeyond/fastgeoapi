/**
 * Keeping the form and the text as two views of one document.
 *
 * The form cannot create what pygeoapi's schema does not describe. Our
 * own `store_options` and `engine_options` are not in it, and providers
 * may invent anything, so there is no widget that could bring them into
 * being — which would leave no way to add a GeoParquet collection from
 * this page at all. `document.ts` keeps such keys alive through a save;
 * only the text view can *write* them.
 *
 * So both views can be edited, and the state below is what they share.
 */

import type { Document } from "yaml";
import { parseDocument } from "yaml";

import { applyDiff, serialise, toJSON } from "./document";

export interface Opened {
  /** The text this state was last agreed to be. */
  original: string;
  /** The document being edited, comments and unknown keys and all. */
  doc: Document;
  /** What the form renders. */
  data: unknown;
  /** How many paths the form has written since `original`. */
  written: number;
}

export interface Parsed {
  state: Opened | null;
  error: string | null;
}

/**
 * Take text as the document, or say why it cannot be.
 *
 * Returning the problem instead of raising it: half-written YAML is the
 * normal state of someone typing, not an exceptional one, and the state
 * being replaced has to survive it. A stray keystroke must not empty the
 * form.
 *
 * Text that parses becomes the new agreed original with nothing written
 * against it — it *is* the document now, so saving it must send it back
 * unchanged rather than putting it through a transplant that would
 * reformat what someone just chose to write.
 */
export function fromYaml(text: string): Parsed {
  const doc = parseDocument(text);
  const failure = doc.errors[0];
  if (failure) {
    const where = failure.linePos?.[0];
    const at = where ? ` (line ${where.line})` : "";
    return { state: null, error: `${failure.message}${at}` };
  }
  const contents = doc.toJS();
  if (
    contents !== null &&
    (typeof contents !== "object" || Array.isArray(contents))
  ) {
    return {
      state: null,
      error: "a configuration has to be a mapping at the top level",
    };
  }
  return {
    state: { original: text, doc, data: toJSON(doc), written: 0 },
    error: null,
  };
}

/** The text this state would save: see `serialise` for why not always the document. */
export function toYaml(state: Opened): string {
  return serialise(state.original, state.doc, state.written);
}

/** Fold a change made in the form into the shared state. */
export function fromForm(state: Opened, data: unknown): Opened {
  const written = applyDiff(state.doc, state.data, data);
  return { ...state, data, written: state.written + written };
}
