/** The names of the control, in the language of the page. */
export interface WidenLabels {
  widen: string;
  narrow: string;
}

/**
 * A MapLibre control that widens the map across the page, above the block it
 * sits beside, and narrows it back. It only marks the map's element: the
 * stylesheet lays the page out, and MapLibre follows its container's size.
 */
export class WidenControl {
  private readonly element: HTMLElement;
  private readonly labels: WidenLabels;
  private container: HTMLElement | null = null;
  private button: HTMLButtonElement | null = null;

  constructor(element: HTMLElement, labels: WidenLabels) {
    this.element = element;
    this.labels = labels;
  }

  onAdd(): HTMLElement {
    const container = document.createElement("div");
    container.className = "maplibregl-ctrl maplibregl-ctrl-group fga-widen";
    const button = document.createElement("button");
    button.type = "button";
    button.addEventListener("click", () => this.toggle());
    container.append(button);
    this.container = container;
    this.button = button;
    this.show(this.element.hasAttribute("wide"));
    return container;
  }

  onRemove(): void {
    this.container?.remove();
    this.container = null;
    this.button = null;
  }

  /** Widens the map, or narrows it when it is wide. */
  toggle(): void {
    this.show(this.element.toggleAttribute("wide"));
  }

  private show(wide: boolean): void {
    if (this.button === null) {
      return;
    }
    const label = wide ? this.labels.narrow : this.labels.widen;
    this.button.textContent = wide ? "⤡" : "⤢";
    this.button.title = label;
    this.button.setAttribute("aria-label", label);
    this.button.setAttribute("aria-pressed", String(wide));
  }
}
