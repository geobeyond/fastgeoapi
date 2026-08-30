/**
 * What the form gives back must not be less than what it was given.
 *
 * The bridge treats a key missing from the form's output as a key the
 * operator removed — it has to, or the form could never delete anything.
 * That makes one library behaviour load-bearing: a form driven by a
 * schema that does not describe `store_options` must still carry it
 * through untouched. If it stripped it, saving would delete it, and the
 * bridge would be faithfully writing down a deletion nobody asked for.
 *
 * pygeoapi's schema declares no `additionalProperties` on providers, so
 * this is not a corner case: it is every dataset we serve.
 */

import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

/** As much of a provider as pygeoapi's schema actually describes. */
const SCHEMA = {
  type: "object",
  properties: {
    title: { type: "string" },
    providers: {
      type: "array",
      items: {
        type: "object",
        properties: {
          name: { type: "string" },
          data: { type: "string" },
        },
      },
    },
  },
} as const;

const DATA = {
  title: "Overture places",
  providers: [
    {
      name: "app.provider.geoparquet.GeoParquetProvider",
      data: "s3://overturemaps-us-west-2/release/",
      store_options: { region: "us-west-2", skip_signature: true },
      engine_options: { memory_limit: "384MB" },
    },
  ],
};

describe("the form", () => {
  it("carries through what the schema does not describe", async () => {
    const onChange = vi.fn();
    render(
      <Form
        schema={SCHEMA as object}
        validator={validator}
        formData={DATA}
        onChange={onChange}
      />,
    );

    const title = screen.getByLabelText("title");
    await userEvent.type(title, "!");

    const last = onChange.mock.calls.at(-1)?.[0].formData;
    expect(last.title).toBe("Overture places!");
    expect(last.providers[0].store_options).toEqual({
      region: "us-west-2",
      skip_signature: true,
    });
    expect(last.providers[0].engine_options).toEqual({ memory_limit: "384MB" });
  });
});
