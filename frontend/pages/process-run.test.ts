import {
  InvalidJsonError,
  buildForm,
  collectInputs,
  execute,
  fieldKind,
  type InputSchema,
  type ProcessRunConfig,
} from "./process-run";

const config: ProcessRunConfig = {
  executeUrl:
    "https://example.org/geoapi/processes/hello-world/execution?f=json",
  inputs: {
    name: { title: "Name", schema: { type: "string" }, minOccurs: 1 },
    times: { title: "Times", schema: { type: "integer" }, minOccurs: 0 },
    loud: { title: "Loud", schema: { type: "boolean" }, minOccurs: 0 },
    tone: { title: "Tone", schema: { enum: ["calm", 2] }, minOccurs: 0 },
    extra: { title: "Extra", minOccurs: 0 },
  },
  modes: ["sync-execute", "async-execute"],
  messages: {
    run: "Run",
    asJob: "Run as a job",
    running: "Running…",
    result: "Result",
    jobStarted: "The job has started:",
    followJob: "follow it",
    failed: "The process could not run:",
    invalidJson: "Not valid JSON:",
    required: "required",
  },
};

function answer(status: number, body: string, location: string | null = null) {
  return {
    status,
    ok: status < 400,
    headers: { get: (name: string) => (name === "Location" ? location : null) },
    text: async () => body,
  };
}

function setValue(form: HTMLFormElement, name: string, value: string): void {
  (form.elements.namedItem(name) as HTMLInputElement).value = value;
}

function buttons(form: HTMLFormElement): string[] {
  return Array.from(form.querySelectorAll("button")).map(
    (button) => button.value,
  );
}

describe("fieldKind", () => {
  it.each([
    [{ schema: { type: "string" } }, "text"],
    [{ schema: { type: "integer" } }, "number"],
    [{ schema: { type: "number" } }, "number"],
    [{ schema: { type: "boolean" } }, "boolean"],
    [{ schema: { type: "string", enum: ["a", "b"] } }, "choice"],
    [{ schema: { type: "object" } }, "json"],
    [{ schema: { type: "array" } }, "json"],
    [
      { schema: JSON.parse('{"oneOf": [{"type": "string"}]}') as InputSchema },
      "json",
    ],
    [{}, "json"],
  ])("gives %o a %s control", (spec, kind) => {
    expect(fieldKind(spec)).toBe(kind);
  });
});

describe("buildForm", () => {
  it("marks the inputs a run cannot do without", () => {
    const form = buildForm(config);

    expect((form.elements.namedItem("name") as HTMLInputElement).required).toBe(
      true,
    );
    expect(
      (form.elements.namedItem("times") as HTMLInputElement).required,
    ).toBe(false);
  });

  it("offers a job only to a process that can run as one", () => {
    expect(buttons(buildForm({ ...config, modes: ["sync-execute"] }))).toEqual([
      "sync",
    ]);
    expect(buttons(buildForm(config))).toEqual(["sync", "job"]);
  });
});

describe("collectInputs", () => {
  it("reads each value as its schema types it", () => {
    const form = buildForm(config);
    setValue(form, "name", "Ada");
    setValue(form, "times", "3");
    (form.elements.namedItem("loud") as HTMLInputElement).checked = true;
    setValue(form, "tone", "1");
    setValue(form, "extra", '{"a": [1]}');

    expect(collectInputs(form, config.inputs)).toEqual({
      name: "Ada",
      times: 3,
      loud: true,
      tone: 2,
      extra: { a: [1] },
    });
  });

  it("leaves out the optional fields left empty", () => {
    const form = buildForm(config);
    setValue(form, "name", "Ada");

    expect(collectInputs(form, config.inputs)).toEqual({
      name: "Ada",
      loud: false,
    });
  });

  it("names the input whose JSON does not parse", () => {
    const form = buildForm(config);
    setValue(form, "extra", "{oops");

    expect(() => collectInputs(form, config.inputs)).toThrow(InvalidJsonError);
    expect(() => collectInputs(form, config.inputs)).toThrow("extra");
  });
});

describe("execute", () => {
  it("shows the result of a run", async () => {
    const fetcher = vi.fn(async (_url: string, _init: RequestInit) =>
      answer(200, '{"id":"echo","value":"Hello Ada!"}'),
    );

    expect(await execute(config, { name: "Ada" }, false, fetcher)).toEqual({
      kind: "result",
      text: '{\n  "id": "echo",\n  "value": "Hello Ada!"\n}',
    });
    expect(fetcher).toHaveBeenCalledWith(config.executeUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: '{"inputs":{"name":"Ada"}}',
    });
  });

  it("asks for a job, and links its page", async () => {
    const fetcher = vi.fn(async (_url: string, _init: RequestInit) =>
      answer(201, "", "https://example.org/geoapi/jobs/42"),
    );

    expect(await execute(config, {}, true, fetcher)).toEqual({
      kind: "job",
      href: "https://example.org/geoapi/jobs/42?f=html",
    });
    expect(fetcher.mock.calls[0][1].headers).toMatchObject({
      Prefer: "respond-async",
    });
  });

  it("reports the description of a refusal", async () => {
    const fetcher = vi.fn(async (_url: string, _init: RequestInit) =>
      answer(
        400,
        '{"code":"InvalidParameterValue","description":"name is missing"}',
      ),
    );

    expect(await execute(config, {}, false, fetcher)).toEqual({
      kind: "error",
      message: "name is missing",
    });
  });

  it("reports a network failure", async () => {
    const fetcher = vi.fn(async (_url: string, _init: RequestInit) => {
      throw new TypeError("offline");
    });

    expect(await execute(config, {}, false, fetcher)).toEqual({
      kind: "error",
      message: "TypeError: offline",
    });
  });
});
