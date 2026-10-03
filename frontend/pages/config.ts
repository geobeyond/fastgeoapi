/**
 * The configuration the server writes inside an island: a JSON script
 * that is the element's own child.
 */
export function readConfig<T>(element: HTMLElement): T {
  const script = Array.from(element.children).find(
    (child): child is HTMLScriptElement =>
      child instanceof HTMLScriptElement && child.type === "application/json",
  );
  if (script === undefined) {
    throw new Error(`${element.localName} has no configuration`);
  }
  return JSON.parse(script.textContent ?? "") as T;
}
