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
    <main className="unlock">
      <h1>fastgeoapi configuration editor</h1>
      <p>Paste the token the command printed.</p>
      <form onSubmit={(event) => void submit(event)}>
        <label htmlFor="token">Token</label>
        <input
          id="token"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <button type="submit" disabled={busy || token.trim() === ""}>
          {busy ? "Checking…" : "Open"}
        </button>
      </form>
      {refused && <p className="failure">That token was not accepted.</p>}
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
  </StrictMode>
);
