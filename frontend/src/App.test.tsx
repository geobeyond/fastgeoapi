/**
 * The whole design, checked where it actually lands.
 *
 * `document.ts` proves the bridge in isolation and `placeholders.ts`
 * proves the schema is habitable. Neither proves that the page wires
 * them up — and the failure mode of wiring them up wrongly is the one
 * this feature exists to avoid: a save that quietly drops what the form
 * could not see.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

// CodeMirror measures layout, which jsdom does not do. These tests are
// about the wiring between the two views, so the editor is stood in for
// by a plain textarea and CodeMirror is left to its own smoke test.
vi.mock("./YamlEditor", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (text: string) => void;
  }) => (
    <textarea
      aria-label="YAML document"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

const DOCUMENT = `# Kept by hand.
server:
    bind:
        host: \${HOST}
        port: \${PORT}
metadata:
    identification:
        title:
            en: pygeoapi default instance
resources:
    overture-places:
        type: collection
        providers:
            - name: app.provider.geoparquet.GeoParquetProvider
              data: s3://overturemaps-us-west-2/release/
              store_options:
                  region: us-west-2
                  skip_signature: true
`;

const SCHEMA = {
  type: "object",
  properties: {
    server: {
      type: "object",
      properties: {
        bind: {
          type: "object",
          properties: { host: { type: "string" }, port: { type: "integer" } },
        },
      },
    },
    metadata: {
      type: "object",
      properties: {
        identification: {
          type: "object",
          properties: {
            title: { type: "object", properties: { en: { type: "string" } } },
          },
        },
      },
    },
  },
};

vi.mock("./api", () => ({
  fetchSchema: vi.fn(),
  fetchConfig: vi.fn(),
  validate: vi.fn(),
  dryRun: vi.fn(),
  save: vi.fn(),
  openSession: vi.fn(),
}));

import * as api from "./api";

beforeEach(() => {
  vi.mocked(api.fetchSchema).mockResolvedValue(SCHEMA);
  vi.mocked(api.fetchConfig).mockResolvedValue({
    source: "s3://fastgeoapi-demo/pygeoapi-config.yml",
    document: DOCUMENT,
  });
  vi.mocked(api.dryRun).mockResolvedValue({
    ok: true,
    problems: [],
    variables: {},
    collections: ["lakes"],
    specs: ["core", "features"],
    tools: ["getCollections", "getLakesFeatures"],
    not_reported: [],
  });
  vi.mocked(api.save).mockResolvedValue({
    saved: true,
    activated: false,
    checked: ["source", "effective"],
    not_checked: ["dry-run: ask /editor/dry-run before relying on this"],
    source: "s3://fastgeoapi-demo/pygeoapi-config.yml",
  });
});

describe("the page", () => {
  it("sends back exactly what it opened when nothing was changed", async () => {
    render(<App onLocked={() => {}} />);
    await screen.findByText(/No changes yet/);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.save).toHaveBeenCalledWith(DOCUMENT));
  });

  it("keeps what the schema never described", async () => {
    render(<App onLocked={() => {}} />);
    const title = await screen.findByLabelText("en");

    await userEvent.clear(title);
    await userEvent.type(title, "fastgeoapi demo");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.save).toHaveBeenCalled());
    const sent = vi.mocked(api.save).mock.calls.at(-1)![0];
    expect(sent).toContain("fastgeoapi demo");
    expect(sent).toContain("skip_signature: true");
    expect(sent).toContain("# Kept by hand.");
  });

  it("shows the placeholder instead of an empty box", async () => {
    render(<App onLocked={() => {}} />);

    const port = (await screen.findByLabelText("port")) as HTMLInputElement;

    expect(port.value).toBe("${PORT}");
  });

  it("says a save is not an activation", async () => {
    render(<App onLocked={() => {}} />);
    await screen.findByText(/No changes yet/);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/not activated/i)).toBeTruthy();
  });
});

describe("the two views", () => {
  it("offers the form and the text as tabs", async () => {
    render(<App onLocked={() => {}} />);
    await screen.findByText(/No changes yet/);

    expect(screen.getByRole("tab", { name: /form/i })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /yaml/i })).toBeTruthy();
  });

  it("shows the document as text, kept up to date with the form", async () => {
    render(<App onLocked={() => {}} />);
    const title = await screen.findByLabelText("en");

    await userEvent.clear(title);
    await userEvent.type(title, "changed here");
    await userEvent.click(screen.getByRole("tab", { name: /yaml/i }));

    const shown = (
      (await screen.findByRole("textbox", {
        name: "YAML document",
      })) as HTMLTextAreaElement
    ).value;
    expect(shown).toContain("changed here");
    expect(shown).toContain("skip_signature: true");
  });

  it("takes text the form could never have written", async () => {
    // The reason this view is editable at all: pygeoapi's schema does
    // not describe store_options, so no widget can create one.
    render(<App onLocked={() => {}} />);
    await screen.findByText(/No changes yet/);
    await userEvent.click(screen.getByRole("tab", { name: /yaml/i }));

    const area = (await screen.findByRole("textbox", {
      name: "YAML document",
    })) as HTMLTextAreaElement;
    await userEvent.clear(area);
    await userEvent.type(
      area,
      "resources:\n  brand-new:\n    type: collection\n",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.save).toHaveBeenCalled());
    expect(vi.mocked(api.save).mock.calls.at(-1)![0]).toContain("brand-new");
  });

  it("says what is wrong with half-written text instead of emptying the form", async () => {
    render(<App onLocked={() => {}} />);
    await screen.findByText(/No changes yet/);
    await userEvent.click(screen.getByRole("tab", { name: /yaml/i }));

    const area = (await screen.findByRole("textbox", {
      name: "YAML document",
    })) as HTMLTextAreaElement;
    await userEvent.clear(area);
    await userEvent.type(area, "resources:\n  a: 1\n b: 2\n");

    expect(await screen.findByRole("alert")).toBeTruthy();
    await userEvent.click(screen.getByRole("tab", { name: /form/i }));
    expect(screen.getByLabelText("en")).toBeTruthy();
  });
});

describe("what only fastgeoapi can say", () => {
  it("shows the specifications and the tools when the dry run reports them", async () => {
    render(<App onLocked={() => {}} />);
    await screen.findByText(/No changes yet/);

    await userEvent.click(screen.getByRole("button", { name: "Dry run" }));

    expect(await screen.findByText(/core, features/)).toBeTruthy();
    expect(screen.getByText(/MCP tools an agent would see \(2\)/)).toBeTruthy();
  });

  it("says nothing about either when they are not reported", async () => {
    // The default. A pygeoapi user must not be shown an empty promise.
    vi.mocked(api.dryRun).mockResolvedValue({
      ok: true,
      problems: [],
      variables: {},
      collections: ["lakes"],
      specs: [],
      tools: [],
      not_reported: [],
    });
    render(<App onLocked={() => {}} />);
    await screen.findByText(/No changes yet/);

    await userEvent.click(screen.getByRole("button", { name: "Dry run" }));

    await screen.findByText(/Built here/);
    expect(screen.queryByText(/MCP tools/)).toBeNull();
    expect(screen.queryByText(/Specifications mounted/)).toBeNull();
  });
});
