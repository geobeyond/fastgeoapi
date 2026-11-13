import { readConfig } from "./config";

export interface InputSchema {
  type?: string;
  enum?: unknown[];
  default?: unknown;
}

export interface InputSpec {
  title?: string;
  description?: string;
  schema?: InputSchema;
  minOccurs?: number;
}

export interface ProcessRunConfig {
  executeUrl: string;
  inputs: Record<string, InputSpec>;
  modes: string[];
  messages: Record<string, string>;
}

export type FieldKind = "text" | "number" | "boolean" | "choice" | "json";

export type Outcome =
  | { kind: "result"; text: string }
  | { kind: "job"; href: string }
  | { kind: "error"; message: string };

interface Answer {
  status: number;
  ok: boolean;
  headers: { get(name: string): string | null };
  text(): Promise<string>;
}

export type Fetch = (url: string, init: RequestInit) => Promise<Answer>;

/** An input whose text is not valid JSON; the message is the input's name. */
export class InvalidJsonError extends Error {}

/** The control an input gets from its schema; any other schema is written as JSON. */
export function fieldKind(spec: InputSpec): FieldKind {
  const schema = spec.schema ?? {};
  if (Array.isArray(schema.enum)) {
    return "choice";
  }
  switch (schema.type) {
    case "string":
      return "text";
    case "number":
    case "integer":
      return "number";
    case "boolean":
      return "boolean";
    default:
      return "json";
  }
}

function isRequired(spec: InputSpec): boolean {
  return (spec.minOccurs ?? 1) > 0;
}

function option(label: string, value: string): HTMLOptionElement {
  const element = document.createElement("option");
  element.value = value;
  element.textContent = label;
  return element;
}

function control(name: string, spec: InputSpec): HTMLElement {
  const kind = fieldKind(spec);
  const schema = spec.schema ?? {};
  let element: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
  if (kind === "choice") {
    const select = document.createElement("select");
    if (!isRequired(spec)) {
      select.append(option("", ""));
    }
    (schema.enum ?? []).forEach((value, index) => {
      select.append(option(String(value), String(index)));
    });
    element = select;
  } else if (kind === "json") {
    const area = document.createElement("textarea");
    area.rows = 3;
    if (schema.default !== undefined) {
      area.value = JSON.stringify(schema.default);
    }
    element = area;
  } else {
    const input = document.createElement("input");
    input.type =
      kind === "boolean" ? "checkbox" : kind === "number" ? "number" : "text";
    if (kind === "boolean") {
      input.checked = schema.default === true;
    } else if (schema.default !== undefined) {
      input.value = String(schema.default);
    }
    if (kind === "number") {
      input.step = "any";
    }
    element = input;
  }
  element.name = name;
  element.id = `fga-input-${name}`;
  element.required = isRequired(spec) && kind !== "boolean";
  return element;
}

function button(
  value: string,
  label: string,
  primary: boolean,
): HTMLButtonElement {
  const element = document.createElement("button");
  element.type = "submit";
  element.value = value;
  element.textContent = label;
  if (primary) {
    element.className = "primary";
  }
  return element;
}

/** A form with one field per input, and a button per way the process runs. */
export function buildForm(config: ProcessRunConfig): HTMLFormElement {
  const form = document.createElement("form");
  form.className = "run";
  for (const [name, spec] of Object.entries(config.inputs)) {
    const field = document.createElement("div");
    const label = document.createElement("label");
    label.htmlFor = `fga-input-${name}`;
    label.textContent = spec.title ?? name;
    if (isRequired(spec)) {
      label.append(` (${config.messages.required})`);
    }
    field.append(label, control(name, spec));
    if (spec.description) {
      const help = document.createElement("small");
      help.textContent = spec.description;
      field.append(help);
    }
    form.append(field);
  }
  const actions = document.createElement("div");
  actions.className = "actions";
  const sync =
    config.modes.length === 0 || config.modes.includes("sync-execute");
  if (sync) {
    actions.append(button("sync", config.messages.run, true));
  }
  if (config.modes.includes("async-execute")) {
    actions.append(button("job", config.messages.asJob, !sync));
  }
  form.append(actions);
  return form;
}

function parseJson(name: string, raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    throw new InvalidJsonError(name);
  }
}

/** The inputs of a run, typed as their schemas say; empty optional fields are left out. */
export function collectInputs(
  form: HTMLFormElement,
  inputs: Record<string, InputSpec>,
): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const [name, spec] of Object.entries(inputs)) {
    const element = form.elements.namedItem(name);
    if (!(
      element instanceof HTMLInputElement ||
      element instanceof HTMLSelectElement ||
      element instanceof HTMLTextAreaElement
    )) {
      continue;
    }
    const kind = fieldKind(spec);
    if (kind === "boolean") {
      values[name] = (element as HTMLInputElement).checked;
      continue;
    }
    const raw = element.value.trim();
    if (raw === "") {
      continue;
    }
    if (kind === "number") {
      values[name] = Number(raw);
    } else if (kind === "choice") {
      values[name] = (spec.schema?.enum ?? [])[Number(raw)];
    } else if (kind === "json") {
      values[name] = parseJson(name, raw);
    } else {
      values[name] = raw;
    }
  }
  return values;
}

function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function describeRefusal(text: string): string {
  try {
    const parsed = JSON.parse(text) as { description?: unknown };
    return typeof parsed.description === "string" ? parsed.description : text;
  } catch {
    return text;
  }
}

/** Runs the process: its result, the page of the job it started, or why it failed. */
export async function execute(
  config: ProcessRunConfig,
  inputs: Record<string, unknown>,
  asJob: boolean,
  fetcher: Fetch = fetch,
): Promise<Outcome> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (asJob) {
    headers.Prefer = "respond-async";
  }
  let answer: Answer;
  try {
    answer = await fetcher(config.executeUrl, {
      method: "POST",
      headers,
      body: JSON.stringify({ inputs }),
    });
  } catch (error) {
    return { kind: "error", message: String(error) };
  }
  const location = answer.headers.get("Location");
  if (answer.status === 201 && location !== null) {
    const href = new URL(location, config.executeUrl);
    href.searchParams.set("f", "html");
    return { kind: "job", href: href.toString() };
  }
  const text = await answer.text();
  return answer.ok
    ? { kind: "result", text: pretty(text) }
    : { kind: "error", message: describeRefusal(text) };
}

/** Writes what came of a run under the form. */
export function showOutcome(
  output: HTMLElement,
  outcome: Outcome,
  messages: Record<string, string>,
): void {
  output.replaceChildren();
  if (outcome.kind === "result") {
    const heading = document.createElement("h3");
    heading.textContent = messages.result;
    const result = document.createElement("pre");
    result.textContent = outcome.text;
    output.append(heading, result);
  } else if (outcome.kind === "job") {
    const line = document.createElement("p");
    const link = document.createElement("a");
    link.href = outcome.href;
    link.textContent = messages.followJob;
    line.append(`${messages.jobStarted} `, link);
    output.append(line);
  } else {
    const line = document.createElement("p");
    line.className = "error";
    line.textContent = `${messages.failed} ${outcome.message}`;
    output.append(line);
  }
}

async function run(
  config: ProcessRunConfig,
  form: HTMLFormElement,
  output: HTMLElement,
  asJob: boolean,
): Promise<void> {
  let inputs: Record<string, unknown>;
  try {
    inputs = collectInputs(form, config.inputs);
  } catch (error) {
    showOutcome(
      output,
      {
        kind: "error",
        message: `${config.messages.invalidJson} ${(error as Error).message}`,
      },
      config.messages,
    );
    return;
  }
  output.textContent = config.messages.running;
  showOutcome(output, await execute(config, inputs, asJob), config.messages);
}

class ProcessRun extends HTMLElement {
  connectedCallback(): void {
    const config = readConfig<ProcessRunConfig>(this);
    const form = buildForm(config);
    const output = document.createElement("div");
    output.className = "outcome";
    output.setAttribute("aria-live", "polite");
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const asJob = event.submitter?.getAttribute("value") === "job";
      void run(config, form, output, asJob);
    });
    this.append(form, output);
  }
}

if (!customElements.get("fga-process-run")) {
  customElements.define("fga-process-run", ProcessRun);
}
