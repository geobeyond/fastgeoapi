import { WidenControl } from "./widen";

const labels = { widen: "Widen the map", narrow: "Narrow the map" };

function added(): {
  element: HTMLElement;
  control: WidenControl;
  container: HTMLElement;
  button: HTMLButtonElement;
} {
  const element = document.createElement("fga-map");
  const control = new WidenControl(element, labels);
  const container = control.onAdd();
  const button = container.querySelector("button") as HTMLButtonElement;
  return { element, control, container, button };
}

describe("WidenControl", () => {
  it("is a button of MapLibre's control group, named to widen the map", () => {
    const { container, button } = added();

    expect(container.classList.contains("maplibregl-ctrl-group")).toBe(true);
    expect(button.type).toBe("button");
    expect(button.getAttribute("aria-label")).toBe("Widen the map");
    expect(button.title).toBe("Widen the map");
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });

  it("widens the map on a click, and narrows it on the next", () => {
    const { element, button } = added();

    button.click();
    expect(element.hasAttribute("wide")).toBe(true);
    expect(button.getAttribute("aria-label")).toBe("Narrow the map");
    expect(button.getAttribute("aria-pressed")).toBe("true");

    button.click();
    expect(element.hasAttribute("wide")).toBe(false);
    expect(button.getAttribute("aria-label")).toBe("Widen the map");
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });

  it("takes its button away when MapLibre removes it", () => {
    const { control, container } = added();
    const holder = document.createElement("div");
    holder.append(container);

    control.onRemove();

    expect(holder.children).toHaveLength(0);
  });
});
