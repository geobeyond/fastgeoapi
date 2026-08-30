/**
 * A parameterised value must survive the form.
 *
 * `port: ${PORT}` is a string where the schema wants an integer, and it
 * is correct — the deployment resolves it at load time. ADR-0008 calls
 * this out as the mistake a naive editor makes: report a false error on
 * a perfect configuration and, in "fixing" it, nail down a value that
 * was parameterised on purpose.
 *
 * The form must therefore neither reject it nor quietly drop it. What it
 * does by default is measured here rather than assumed.
 */

import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { relax } from "./placeholders";

const SCHEMA = {
  type: "object",
  properties: {
    bind: {
      type: "object",
      properties: {
        host: { type: "string" },
        port: { type: "integer" },
      },
    },
  },
} as const;

const DATA = { bind: { host: "${HOST}", port: "${PORT}" } };

describe("a parameterised value", () => {
  it("is still there after the form has been touched", async () => {
    const onChange = vi.fn();
    render(
      <Form
        schema={SCHEMA as object}
        validator={validator}
        formData={DATA}
        onChange={onChange}
      />,
    );

    await userEvent.type(screen.getByLabelText("host"), "!");

    const last = onChange.mock.calls.at(-1)?.[0].formData;
    expect(last.bind.port).toBe("${PORT}");
  });
});

describe("the widget the placeholder lands in", () => {
  it("shows it rather than an empty box", () => {
    render(
      <Form
        schema={relax(SCHEMA) as object}
        validator={validator}
        formData={DATA}
      />,
    );

    const port = screen.getByLabelText("port") as HTMLInputElement;

    expect({ type: port.type, value: port.value }).toEqual({
      type: "text",
      value: "${PORT}",
    });
  });

  it("does not report a perfectly good configuration as broken", () => {
    const errors = validator.validateFormData(
      DATA,
      relax(SCHEMA) as object,
    ).errors;

    expect(errors).toEqual([]);
  });
});

describe("what widening must not do", () => {
  it("still refuses a value of the wrong shape", () => {
    // Widening is for scalars standing in for scalars. If it turned the
    // schema into a rubber stamp the form would stop helping at all, so
    // the structural constraints have to survive it.
    const errors = validator.validateFormData(
      { bind: "not an object" },
      relax(SCHEMA) as object,
    ).errors;

    expect(errors.map((e) => e.name)).toContain("type");
  });

  it("leaves a string alone and keeps every other keyword", () => {
    const relaxed = relax({
      type: "object",
      properties: {
        name: { type: "string", maxLength: 4, description: "why" },
      },
      required: ["name"],
    }) as any;

    expect(relaxed.properties.name).toEqual({
      type: "string",
      maxLength: 4,
      description: "why",
    });
    expect(relaxed.required).toEqual(["name"]);
  });
});
