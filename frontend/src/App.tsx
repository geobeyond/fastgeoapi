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

import type { Outcome, Saved, Validation } from "./api";
import * as api from "./api";
import { relax } from "./placeholders";
import type { Opened } from "./sync";
import { fromForm, fromYaml, toYaml } from "./sync";
import { templates } from "./templates";
import YamlEditor from "./YamlEditor";

export default function App({ onLocked }: { onLocked: () => void }) {
  const [schema, setSchema] = useState<unknown>(null);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [preview, setPreview] = useState<Outcome | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [tab, setTab] = useState<"form" | "yaml">("form");
  const [source, setSource] = useState("");
  // Text being typed that does not parse yet. Held apart from `opened`
  // so a half-written line cannot empty the form behind the other tab.
  const [draft, setDraft] = useState<string | null>(null);
  const [broken, setBroken] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [rawSchema, config] = await Promise.all([
          api.fetchSchema(),
          api.fetchConfig(),
        ]);
        setSchema(relax(rawSchema));
        setSource(config.source);
        setOpened(fromYaml(config.document).state);
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
  const textToSend = () => (opened ? toYaml(opened) : "");

  /** Every answer belongs to the text that produced it, and that is gone. */
  function forget() {
    setValidation(null);
    setPreview(null);
    setSaved(null);
  }

  function onChange(event: IChangeEvent) {
    if (!opened) return;
    setOpened(fromForm(opened, event.formData));
    setDraft(null);
    setBroken(null);
    forget();
  }

  function onTyped(text: string) {
    // Typed text *is* the document, so it replaces the state outright
    // rather than being folded into it: saving has to send back what was
    // written, not a reformatting of it.
    const { state, error } = fromYaml(text);
    setBroken(error);
    setDraft(state ? null : text);
    if (state) setOpened(state);
    forget();
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
        <h1>{source}</h1>
        <p>
          {opened.written === 0
            ? "No changes yet — saving now would send the document untouched."
            : `${opened.written} ${
                opened.written === 1 ? "change" : "changes"
              } not yet saved.`}
        </p>
      </header>

      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "form"}
          onClick={() => setTab("form")}
        >
          Form
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "yaml"}
          onClick={() => setTab("yaml")}
        >
          YAML
        </button>
      </div>

      {tab === "yaml" && (
        <section className="pane">
          {broken && (
            <p className="failure" role="alert">
              {broken} — the form still holds the last document that parsed.
            </p>
          )}
          <YamlEditor value={draft ?? textToSend()} onChange={onTyped} />
        </section>
      )}

      {/* Rendered only when it is the view in front of you. Kept mounted
          behind the other tab, the form goes on reacting to a document
          being typed into — and folds its idea of the half-written state
          back in, overwriting what is being written. */}
      {tab === "form" && (
        <div className="pane">
          <Form
            schema={schema as object}
            validator={validator}
            formData={opened.data}
            onChange={onChange}
            templates={templates}
            liveValidate={false}
            // The server is the authority on whether a document is well
            // formed, and it answers for the source and the effective form
            // separately. A second opinion from the browser, which knows
            // neither the environment nor the variables, would only
            // contradict it.
            noValidate
          >
            <></>
          </Form>
        </div>
      )}

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
