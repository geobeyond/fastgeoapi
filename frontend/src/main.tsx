/**
 * Getting in, then getting out of the way.
 *
 * The token is asked for in a form and posted in a body. It is never put
 * in the address: a secret there outlives the session in browser
 * history and rides along in the `Referer` sent to anything the page
 * loads. What comes back is an `HttpOnly` cookie, which no script here
 * can read — including this one.
 */

import { StrictMode, useCallback, useState } from "react";
import { createRoot } from "react-dom/client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { openSession } from "./api";
import App from "./App";
import "./style.css";

function Unlock({ onOpen }: { onOpen: () => void }) {
  const [token, setToken] = useState("");
  const [refused, setRefused] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setRefused(false);
    const accepted = await openSession(token.trim());
    setBusy(false);
    // Cleared either way: on success the cookie holds it and this copy
    // is only something left lying in the page.
    setToken("");
    if (accepted) onOpen();
    else setRefused(true);
  }

  return (
    <main className="mx-auto max-w-md p-6">
      <Card>
        <CardHeader>
          <CardTitle>fastgeoapi configuration editor</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-sm text-muted-foreground">
            Paste the token the command printed.
          </p>
          <form className="space-y-3" onSubmit={(event) => void submit(event)}>
            <label className="block text-sm font-medium" htmlFor="token">
              Token
            </label>
            <input
              id="token"
              type="password"
              autoComplete="off"
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
            <Button type="submit" disabled={busy || token.trim() === ""}>
              {busy ? "Checking…" : "Open"}
            </Button>
          </form>
          {refused && (
            <p className="mt-3 text-sm text-destructive" role="alert">
              That token was not accepted.
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

function Editor() {
  const [open, setOpen] = useState(false);
  const lock = useCallback(() => setOpen(false), []);

  return open ? (
    <App onLocked={lock} />
  ) : (
    <Unlock onOpen={() => setOpen(true)} />
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Editor />
  </StrictMode>,
);
