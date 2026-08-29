/**
 * Making room in the schema for the values a configuration is meant to
 * carry.
 *
 * The document being edited is not the document that runs: it carries
 * `${VAR}` placeholders that the deployment resolves at load time. So
 * `port: ${PORT}` is a string where the schema says integer, and it is
 * correct.
 *
 * Handed the schema as it stands, the form does two harmful things —
 * both measured, not supposed. It renders an **empty number box**, so
 * the placeholder is not even visible and the first keystroke destroys
 * it. And it reports a type error on a perfectly good configuration,
 * which is the mistake ADR-0008 names: telling someone to "fix"
 * something by nailing down a value that was parameterised on purpose.
 *
 * So every scalar type is widened to accept a string as well. The form
 * then shows the placeholder and leaves it alone. This is looser than
 * the server, deliberately: the authority on whether a document is well
 * formed is `/editor/validate`, which answers for the source *and* the
 * effective form, and whose answers this page displays. The schema here
 * only decides what can be typed.
 */

/** JSON Schema, as far as this file needs to care. */
type Schema = Record<string, unknown>;

const WIDENED = new Set(["integer", "number", "boolean"]);

/**
 * The schema, with room for placeholders wherever one could appear.
 *
 * Structural keywords are walked; scalar types are widened in place. A
 * type already allowing a string is left as it is, and so is anything
 * this does not recognise — an unknown keyword is not ours to rewrite.
 */
export function relax(schema: unknown): unknown {
  if (Array.isArray(schema)) return schema.map(relax);
  if (typeof schema !== "object" || schema === null) return schema;

  const out: Schema = {};
  for (const [keyword, value] of Object.entries(schema as Schema)) {
    out[keyword] = keyword === "type" ? value : relax(value);
  }

  const type = out.type;
  if (typeof type === "string" && WIDENED.has(type)) {
    out.type = [type, "string"];
  } else if (
    Array.isArray(type) &&
    type.some((t) => WIDENED.has(t as string))
  ) {
    if (!type.includes("string")) out.type = [...type, "string"];
  }
  return out;
}

const PLACEHOLDER = /\$\{[A-Za-z_][A-Za-z0-9_]*\}/;

/** Whether a value is a parameter standing in for something else. */
export function isPlaceholder(value: unknown): boolean {
  return typeof value === "string" && PLACEHOLDER.test(value);
}
