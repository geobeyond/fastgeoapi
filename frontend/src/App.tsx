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

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

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
    then: (value: T) => void,
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

  if (failure) return <p className="p-8 text-destructive">{failure}</p>;
  if (!schema || !opened)
    return <p className="p-8 text-muted-foreground">Opening…</p>;

  return (
    <main className="mx-auto max-w-7xl p-6">
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="font-mono text-sm text-muted-foreground">{source}</h1>
        <p className="text-sm text-muted-foreground">
          {opened.written === 0
            ? "No changes yet — saving now would send the document untouched."
            : `${opened.written} ${
                opened.written === 1 ? "change" : "changes"
              } not yet saved.`}
        </p>
      </header>

      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as "form" | "yaml")}
      >
        <TabsList>
          <TabsTrigger value="form">Form</TabsTrigger>
          <TabsTrigger value="yaml">YAML</TabsTrigger>
        </TabsList>

        {/* Radix unmounts the panel you are not looking at, which this
            page needs rather than merely likes: a form left mounted
            behind the text view goes on reacting to the document being
            typed into, and writes its idea of the half-written state
            back over it. */}
        <TabsContent value="form">
          <Form
            schema={schema as object}
            validator={validator}
            formData={opened.data}
            onChange={onChange}
            templates={templates}
            liveValidate={false}
            noValidate
          >
            <></>
          </Form>
        </TabsContent>

        <TabsContent value="yaml">
          {broken && (
            <p className="mb-2 text-sm text-destructive" role="alert">
              {broken} — the form still holds the last document that parsed.
            </p>
          )}
          <YamlEditor value={draft ?? textToSend()} onChange={onTyped} />
        </TabsContent>
      </Tabs>

      <div className="sticky bottom-0 mt-4 flex items-center gap-2 border-t border-border bg-background py-3">
        <Button
          variant="outline"
          disabled={busy !== null}
          onClick={() =>
            void run(
              "validate",
              () => api.validate(textToSend()),
              setValidation,
            )
          }
        >
          Validate
        </Button>
        <Button
          variant="outline"
          disabled={busy !== null}
          onClick={() =>
            void run("dry-run", () => api.dryRun(textToSend()), setPreview)
          }
        >
          Dry run
        </Button>
        <Button
          disabled={busy !== null}
          onClick={() =>
            void run("save", () => api.save(textToSend()), setSaved)
          }
        >
          Save
        </Button>
        {busy && <span className="text-sm text-muted-foreground">{busy}…</span>}
      </div>

      {validation && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Well formed?</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Answer title="As written" outcome={validation.source} />
            <Answer title="As it would run" outcome={validation.effective} />
          </CardContent>
        </Card>
      )}

      {preview && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Dry run</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Answer title="Built here" outcome={preview} />
            {/* Only when asked for, and only when there is something to
                say: `--augmented` is off by default because the editor
                has to stay useful with nothing but pygeoapi installed. */}
            {preview.specs.length > 0 && (
              <p className="text-sm">
                <span className="font-medium">Specifications mounted:</span>{" "}
                {preview.specs.join(", ")}
              </p>
            )}
            {preview.tools.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer font-medium">
                  MCP tools an agent would see ({preview.tools.length})
                </summary>
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {preview.tools.join(", ")}
                </p>
              </details>
            )}
            {preview.not_reported.length > 0 && (
              <ul className="list-inside list-disc text-xs text-muted-foreground">
                {preview.not_reported.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            <p className="text-xs text-muted-foreground">
              This says whether it builds <em>here</em>, with the variables and
              credentials of whoever is running the editor. It says nothing
              about the deployment.
            </p>
          </CardContent>
        </Card>
      )}

      {saved && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Saved</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>Checked: {saved.checked.join(", ")}</p>
            <ul className="list-inside list-disc text-muted-foreground">
              {saved.not_checked.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Written, not activated. Putting it into service is a separate
              gesture, against the deployment.
            </p>
          </CardContent>
        </Card>
      )}
    </main>
  );
}

function Answer({ title, outcome }: { title: string; outcome: Outcome }) {
  return (
    <div>
      <h3 className="text-sm font-semibold">
        {title}:{" "}
        <span className={outcome.ok ? "text-emerald-600" : "text-destructive"}>
          {outcome.ok ? "yes" : "no"}
        </span>
      </h3>
      {outcome.problems.length > 0 && (
        <ul className="mt-1 list-inside list-disc text-sm text-destructive">
          {outcome.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      {outcome.collections.length > 0 && (
        <p className="mt-1 text-sm">
          Collections: {outcome.collections.join(", ")}
        </p>
      )}
      {Object.keys(outcome.variables).length > 0 && (
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          Resolved with{" "}
          {Object.entries(outcome.variables)
            .map(([name, value]) => `${name}=${value}`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}
