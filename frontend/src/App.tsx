/**
 * The page: the four endpoints, with a form in front of them.
 *
 * It owns no truth. The document it opened is held as text and as a
 * `Document`; the form is handed a plain value derived from that, and
 * what comes back is diffed and written path by path. Saving sends the
 * text that was opened when nothing changed, and a transplant otherwise
 * — see `document.ts` for why both matter.
 *
 * What it deliberately cannot do is put anything into service. There is
 * no reload webhook here, because there is none in the authoring role at
 * all (ADR-0008): writing a configuration and activating it are two
 * powers, and one surface holding both would mean whoever reaches it
 * decides what the server serves.
 */

import Form from "@rjsf/core";
import type { IChangeEvent } from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import { useEffect, useState } from "react";
import type { Document } from "yaml";
import { parseDocument } from "yaml";

import type { Outcome, Saved, Validation } from "./api";
import * as api from "./api";
import { applyDiff, serialise, toJSON } from "./document";
import { relax } from "./placeholders";

interface Opened {
  source: string;
  original: string;
  doc: Document;
  data: unknown;
  written: number;
}

export default function App({ onLocked }: { onLocked: () => void }) {
  const [schema, setSchema] = useState<unknown>(null);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [preview, setPreview] = useState<Outcome | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [rawSchema, config] = await Promise.all([
          api.fetchSchema(),
          api.fetchConfig(),
        ]);
        setSchema(relax(rawSchema));
        const doc = parseDocument(config.document);
        setOpened({
          source: config.source,
          original: config.document,
          doc,
          data: toJSON(doc),
          written: 0,
        });
      } catch (error) {
        // A session that has lapsed looks like any other failure from
        // here, so the token screen is offered again rather than leaving
        // a page that silently does nothing.
        if (String(error).includes("401")) onLocked();
        else setFailure(String(error));
      }
    })();
  }, [onLocked]);

  /** The text to send: what was opened, carrying whatever changed. */
  const textToSend = () =>
    opened ? serialise(opened.original, opened.doc, opened.written) : "";

  function onChange(event: IChangeEvent) {
    if (!opened) return;
    const written = applyDiff(opened.doc, opened.data, event.formData);
    setOpened({
      ...opened,
      data: event.formData,
      written: opened.written + written,
    });
    // Any answer about the previous text is now about a document that no
    // longer exists. Showing it next to changed fields would be worse
    // than showing nothing.
    setValidation(null);
    setPreview(null);
    setSaved(null);
  }

  async function run<T>(
    label: string,
    work: () => Promise<T>,
    then: (value: T) => void
  ) {
    setBusy(label);
    setFailure(null);
    try {
      then(await work());
    } catch (error) {
      if (String(error).includes("401")) onLocked();
      else setFailure(String(error));
    } finally {
      setBusy(null);
    }
  }

  if (failure) return <p className="failure">{failure}</p>;
  if (!schema || !opened) return <p>Opening…</p>;

  return (
    <main>
      <header>
        <h1>{opened.source}</h1>
        <p>
          {opened.written === 0
            ? "No changes yet — saving now would send the document untouched."
            : `${opened.written} ${
                opened.written === 1 ? "change" : "changes"
              } not yet saved.`}
        </p>
      </header>

      <Form
        schema={schema as object}
        validator={validator}
        formData={opened.data}
        onChange={onChange}
        liveValidate={false}
        // The server is the authority on whether a document is well
        // formed, and it answers for the source and the effective form
        // separately. A second opinion from the browser, which knows
        // neither the environment nor the variables, would only
        // contradict it.
        noValidate
      >
        <div className="actions">
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              void run(
                "validate",
                () => api.validate(textToSend()),
                setValidation
              )
            }
          >
            Validate
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              void run("dry-run", () => api.dryRun(textToSend()), setPreview)
            }
          >
            Dry run
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              void run("save", () => api.save(textToSend()), setSaved)
            }
          >
            Save
          </button>
          {busy && <span className="busy">{busy}…</span>}
        </div>
      </Form>

      {validation && (
        <section>
          <h2>Well formed?</h2>
          <Answer title="As written" outcome={validation.source} />
          <Answer title="As it would run" outcome={validation.effective} />
        </section>
      )}

      {preview && (
        <section>
          <h2>Dry run</h2>
          <Answer title="Built here" outcome={preview} />
          <p className="caveat">
            This says whether it builds <em>here</em>, with the variables and
            credentials of whoever is running the editor. It says nothing about
            the deployment.
          </p>
        </section>
      )}

      {saved && (
        <section>
          <h2>Saved</h2>
          <p>Checked: {saved.checked.join(", ")}</p>
          <ul>
            {saved.not_checked.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="caveat">
            Written, not activated. Putting it into service is a separate
            gesture, against the deployment.
          </p>
        </section>
      )}
    </main>
  );
}

function Answer({ title, outcome }: { title: string; outcome: Outcome }) {
  return (
    <div className={outcome.ok ? "ok" : "not-ok"}>
      <h3>
        {title}: {outcome.ok ? "yes" : "no"}
      </h3>
      {outcome.problems.length > 0 && (
        <ul>
          {outcome.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      {outcome.collections.length > 0 && (
        <p>Collections: {outcome.collections.join(", ")}</p>
      )}
      {Object.keys(outcome.variables).length > 0 && (
        <p className="variables">
          Resolved with{" "}
          {Object.entries(outcome.variables)
            .map(([name, value]) => `${name}=${value}`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}
