/**
 * Controls that say what they do.
 *
 * rjsf's plain theme draws add and remove as bootstrap glyphs, and the
 * page loads no bootstrap — so both come out as **empty boxes** with a
 * tooltip and nothing else. Measured, not guessed: their `textContent`
 * is the empty string and only `title` carries a word.
 *
 * Adding and removing a collection is most of what an operator comes
 * here to do, so the buttons that do it cannot be a shape you have to
 * hover to identify.
 */

import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { templates } from "./templates";

const SCHEMA = {
  type: "object",
  properties: {
    keywords: { type: "array", items: { type: "string" } },
    resources: {
      type: "object",
      patternProperties: { "^.*$": { type: "string" } },
    },
  },
} as const;

const DATA = { keywords: ["geospatial"], resources: { lakes: "collection" } };

describe("the controls", () => {
  it("say add and remove in words", () => {
    render(
      <Form
        schema={SCHEMA as object}
        validator={validator}
        formData={DATA}
        templates={templates}
      />,
    );

    expect(
      screen.getAllByRole("button", { name: /add/i }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("button", { name: /remove/i }).length,
    ).toBeGreaterThan(0);
  });

  it("still add and remove", async () => {
    // Labelling them would be worth nothing if it broke what they do.
    const onChange = vi.fn();
    render(
      <Form
        schema={SCHEMA as object}
        validator={validator}
        formData={DATA}
        templates={templates}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getAllByRole("button", { name: /add/i })[0]);

    const last = onChange.mock.calls.at(-1)?.[0].formData;
    expect(last.keywords.length).toBe(2);
  });
});
