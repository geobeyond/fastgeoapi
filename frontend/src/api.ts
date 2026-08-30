/**
 * The four endpoints, plus the exchange that gets the page in.
 *
 * Nothing here holds the token. It is posted once to `/editor/session`
 * and comes back as an `HttpOnly` cookie the browser attaches on its
 * own — which is why `credentials: "same-origin"` is on every call and
 * why no code in this file could read the secret even if it wanted to.
 */

export interface Outcome {
  ok: boolean;
  problems: string[];
  variables: Record<string, string>;
  collections: string[];
}

export interface Validation {
  source: Outcome;
  effective: Outcome;
}

export interface Saved {
  saved: boolean;
  activated: boolean;
  checked: string[];
  not_checked: string[];
  source: string;
}

async function call(path: string, init?: RequestInit): Promise<Response> {
  return fetch(path, { ...init, credentials: "same-origin" });
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await call(path, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(
      `${path} answered ${response.status}: ${detail.slice(0, 300)}`,
    );
  }
  return (await response.json()) as T;
}

function withDocument(document: string): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document }),
  };
}

/**
 * Exchange the token for a cookie.
 *
 * Returns whether it was accepted rather than throwing: a mistyped token
 * is the ordinary case on this screen, not an exceptional one.
 */
export async function openSession(token: string): Promise<boolean> {
  const response = await call("/editor/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return response.ok;
}

/** The schema the form is generated from, as the running server has it. */
export async function fetchSchema(): Promise<unknown> {
  return json<unknown>("/editor/schema");
}

/** The document as written — placeholders intact. */
export async function fetchConfig(): Promise<{
  source: string;
  document: string;
}> {
  return json("/editor/config");
}

/** Well formed as source, and as it would run: two questions, two answers. */
export async function validate(document: string): Promise<Validation> {
  return json("/editor/validate", withDocument(document));
}

/** Build it for real. Seconds against a remote dataset. */
export async function dryRun(document: string): Promise<Outcome> {
  return json("/editor/dry-run", withDocument(document));
}

/** Save, if it validates. Says what it checked and what it did not. */
export async function save(document: string): Promise<Saved> {
  return json("/editor/config", { ...withDocument(document), method: "PUT" });
}
