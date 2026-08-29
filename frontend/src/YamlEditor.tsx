/**
 * The text view: CodeMirror, kept deliberately thin.
 *
 * Everything that decides anything lives in `sync.ts`, which is plain
 * functions and is tested as such. This file only carries keystrokes in
 * and text out — because an editor component is awkward to drive in a
 * headless DOM, and logic that hides in one is logic that does not get
 * tested.
 */

import { yaml } from "@codemirror/lang-yaml";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { useEffect, useRef } from "react";

export default function YamlEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (text: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  // Held in a ref so that changing the handler does not tear the editor
  // down and put the cursor back at the top.
  const notify = useRef(onChange);
  notify.current = onChange;

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          yaml(),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) notify.current(update.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // Built once: `value` is applied below instead, so that typing here
    // does not fight with the state it is updating.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    const shown = editor.state.doc.toString();
    // Only when it changed elsewhere — the form. Writing back text the
    // editor already holds would move the cursor on every keystroke.
    if (shown === value) return;
    editor.dispatch({ changes: { from: 0, to: shown.length, insert: value } });
  }, [value]);

  return <div className="yaml" ref={host} aria-label="YAML" />;
}
