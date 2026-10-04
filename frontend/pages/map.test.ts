import {
  baseStyle,
  dataBounds,
  extentFeature,
  mapImageUrl,
  startMap,
  type FeatureCollection,
  type MapConfig,
} from "./map";

const maplibre = vi.hoisted(() => ({
  setWorkerUrl: vi.fn(),
  NavigationControl: class {
    options: unknown;
    constructor(options?: unknown) {
      this.options = options;
    }
  },
  ScaleControl: class {
    options: unknown;
    constructor(options?: unknown) {
      this.options = options;
    }
  },
}));

vi.mock("maplibre-gl", () => ({
  Map: class {},
  NavigationControl: maplibre.NavigationControl,
  ScaleControl: maplibre.ScaleControl,
  setWorkerUrl: maplibre.setWorkerUrl,
}));

type Handler = () => void;

class FakeMap {
  static last: FakeMap;
  options: Record<string, unknown>;
  handlers: Record<string, Handler[]> = {};
  sources: Record<string, Record<string, unknown>> = {};
  layers: string[] = [];
  styles: unknown[] = [];
  fitted: unknown[] = [];
  fitOptions: unknown[] = [];
  updates: unknown[] = [];
  controls: unknown[] = [];
  images: unknown[] = [];
  bounds: [number, number, number, number] = [12, 41, 13, 42];
  bearing = 0;

  constructor(options: Record<string, unknown>) {
    this.options = options;
    FakeMap.last = this;
  }
  on(event: string, handler: Handler) {
    (this.handlers[event] ??= []).push(handler);
  }
  getBearing() {
    return this.bearing;
  }
  setBearing(bearing: number) {
    this.bearing = bearing;
  }
  fire(event: string) {
    (this.handlers[event] ?? []).forEach((handler) => handler());
  }
  addSource(id: string, source: Record<string, unknown>) {
    this.sources[id] = source;
  }
  getSource(id: string) {
    return id in this.sources
      ? {
          updateImage: (image: unknown) => this.images.push(image),
          setData: (data: unknown) => this.updates.push([id, data]),
        }
      : undefined;
  }
  addControl(control: unknown, position?: string) {
    this.controls.push([control, position]);
  }
  addLayer(layer: { id: string }) {
    this.layers.push(layer.id);
  }
  setStyle(style: unknown) {
    this.styles.push(style);
  }
  fitBounds(bounds: unknown, options?: unknown) {
    this.fitted.push(bounds);
    this.fitOptions.push(options);
  }
  getBounds() {
    const [w, s, e, n] = this.bounds;
    return {
      getWest: () => w,
      getSouth: () => s,
      getEast: () => e,
      getNorth: () => n,
    };
  }
  getCanvas() {
    return { clientWidth: 800, clientHeight: 600 };
  }
}

const camera = {
  bounds: [12, 41, 13, 42] as [number, number, number, number],
  minZoom: 0,
};
const collection: FeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "a" },
      geometry: { type: "Point", coordinates: [12.5, 41.9] },
    },
    {
      type: "Feature",
      properties: null,
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [12, 41],
            [14, 41],
            [14, 43],
            [12, 41],
          ],
        ],
      },
    },
  ],
};

function start(config: MapConfig): FakeMap {
  document.body.innerHTML = "";
  const element = document.createElement("div");
  document.body.append(element);
  startMap(element, config, FakeMap as never);
  return FakeMap.last;
}

describe("mapImageUrl", () => {
  it("asks for the view in corners, scaled down to the largest size", () => {
    const url = new URL(
      mapImageUrl(
        "https://e.org/geoapi/collections/b/map",
        [12, 41, 13, 42],
        3000,
        1500,
        2048,
      ),
    );

    expect(url.searchParams.get("bbox")).toBe(
      "12.000000,41.000000,13.000000,42.000000",
    );
    expect([
      url.searchParams.get("width"),
      url.searchParams.get("height"),
    ]).toEqual(["2048", "1024"]);
    expect(url.searchParams.get("f")).toBe("png");
  });
});

describe("helpers", () => {
  it("draws an extent as a closed ring", () => {
    expect(extentFeature([12, 41, 13, 42]).geometry).toEqual({
      type: "Polygon",
      coordinates: [
        [
          [12, 41],
          [13, 41],
          [13, 42],
          [12, 42],
          [12, 41],
        ],
      ],
    });
  });

  it("finds the bounds of every coordinate", () => {
    expect(dataBounds(collection)).toEqual([12, 41, 14, 43]);
    expect(dataBounds({ type: "FeatureCollection", features: [] })).toBeNull();
  });

  it("puts the basemap under the data, or a plain background without one", () => {
    expect(
      baseStyle({ url: "https://t/{z}/{x}/{y}.png", attribution: "OSM" })
        .layers,
    ).toEqual([{ id: "basemap", type: "raster", source: "basemap" }]);
    expect(baseStyle(null).layers[0].type).toBe("background");
  });

  it("asks the basemap no deeper than its tiles go", () => {
    const sources = baseStyle({
      url: "https://t/{z}/{x}/{y}.png",
      attribution: "OSM",
    }).sources as Record<string, { maxzoom?: number }>;

    expect(sources.basemap.maxzoom).toBe(19);
  });
});

describe("startMap", () => {
  it("draws tiles with their first style and switches style from the picker", () => {
    const styles = [
      { name: "Default", style: { version: 8, sources: {}, layers: [] } },
      {
        name: "night",
        style: { version: 8, sources: {}, layers: [], name: "night" },
      },
    ];
    const map = start({
      kind: "tiles",
      camera,
      styles,
      labels: { style: "Style" },
    } as MapConfig);
    const picker = document.querySelector("select") as HTMLSelectElement;

    picker.value = "1";
    picker.dispatchEvent(new Event("change"));

    expect(map.options.style).toBe(styles[0].style);
    expect(map.styles).toEqual([styles[1].style]);
  });

  it("keeps a map of images flat, and lets the other maps tilt", () => {
    const image = start({
      kind: "image",
      camera,
      basemap: null,
      maps: [{ name: "Default", url: "https://e.org/map" }],
      maxSize: 2048,
      labels: { style: "Style" },
    });
    const extent = start({
      kind: "extent",
      camera,
      basemap: null,
      bbox: [12, 41, 13, 42],
    });

    expect(image.options.maxPitch).toBe(0);
    expect("maxPitch" in extent.options).toBe(false);
  });

  it("turns with two fingers on a trackpad, where the browser tells the angle", () => {
    const map = start({
      kind: "extent",
      camera,
      basemap: null,
      bbox: [12, 41, 13, 42],
    });
    const canvas = map.options.container as HTMLElement;
    map.bearing = 10;
    const gesture = (type: string, rotation: number) =>
      Object.assign(new Event(type, { cancelable: true }), { rotation });

    const started = gesture("gesturestart", 0);
    canvas.dispatchEvent(started);
    const turned = gesture("gesturechange", 30);
    canvas.dispatchEvent(turned);

    expect(map.bearing).toBe(-20);
    expect(started.defaultPrevented && turned.defaultPrevented).toBe(true);
  });

  it("draws the basemap under the tiles, above the style's own background", () => {
    const hillshade = {
      version: 8,
      sources: { archive: { type: "raster-dem" } },
      layers: [
        { id: "background", type: "background" },
        { id: "hillshade", type: "hillshade", source: "archive" },
      ],
    };
    const night = {
      version: 8,
      sources: { lines: { type: "vector" } },
      layers: [{ id: "night", type: "line", source: "lines" }],
    };
    const map = start({
      kind: "tiles",
      camera,
      basemap: { url: "https://t/{z}/{x}/{y}.png", attribution: "OSM" },
      styles: [
        { name: "Default", style: hillshade },
        { name: "night", style: night },
      ],
      labels: { style: "Style" },
    } as MapConfig);
    const picker = document.querySelector("select") as HTMLSelectElement;
    picker.value = "1";
    picker.dispatchEvent(new Event("change"));
    const ids = (style: unknown) =>
      (style as { layers: { id: string }[] }).layers.map((layer) => layer.id);

    expect(ids(map.options.style)).toEqual([
      "background",
      "basemap",
      "hillshade",
    ]);
    expect(ids(map.styles[0])).toEqual(["basemap", "night"]);
    expect(
      (map.options.style as { sources: Record<string, unknown> }).sources
        .basemap,
    ).toMatchObject({ type: "raster", maxzoom: 19, attribution: "OSM" });
    expect(hillshade.layers).toHaveLength(2);
  });

  it("asks one map image per view, again when the map stops moving", () => {
    const map = start({
      kind: "image",
      camera,
      basemap: null,
      maps: [{ name: "Default", url: "https://e.org/map" }],
      maxSize: 2048,
      labels: { style: "Style" },
    });

    map.fire("load");
    map.bounds = [12.2, 41.2, 12.8, 41.8];
    map.fire("moveend");

    expect(map.sources["fga-image"].url).toContain(
      "bbox=12.000000%2C41.000000",
    );
    expect((map.images[0] as { url: string }).url).toContain(
      "bbox=12.200000%2C41.200000",
    );
    expect(map.options.minZoom).toBe(0);
  });

  it("draws the item under the pointer above the others, where points overlap too", () => {
    document.body.innerHTML = "";
    const item = document.createElement("li");
    item.dataset.fgaFeature = "1";
    const element = document.createElement("div");
    document.body.append(item, element);
    startMap(
      element,
      {
        kind: "features",
        camera: { ...camera, fitData: true },
        basemap: null,
        data: collection,
      },
      FakeMap as never,
    );
    const map = FakeMap.last;

    map.fire("load");
    item.dispatchEvent(new Event("mouseenter"));
    const shown = map.updates[map.updates.length - 1];
    item.dispatchEvent(new Event("mouseleave"));

    expect(map.fitted).toEqual([[12, 41, 14, 43]]);
    expect(map.layers.indexOf("fga-active-point")).toBeGreaterThan(
      map.layers.indexOf("fga-data-point"),
    );
    expect(shown).toEqual([
      "fga-active",
      { type: "FeatureCollection", features: [collection.features[1]] },
    ]);
    expect(map.updates[map.updates.length - 1]).toEqual([
      "fga-active",
      { type: "FeatureCollection", features: [] },
    ]);
  });

  it("gives every map its zoom buttons, a compass that shows the tilt, and a scale", () => {
    const map = start({
      kind: "extent",
      camera,
      basemap: null,
      bbox: [12, 41, 13, 42],
    });
    const controls = map.controls as [{ options: unknown }, string][];
    const navigation = controls.filter(
      ([control]) => control instanceof maplibre.NavigationControl,
    );
    const scale = controls.filter(
      ([control]) => control instanceof maplibre.ScaleControl,
    );

    expect(navigation).toHaveLength(1);
    expect(navigation[0][0].options).toEqual({ visualizePitch: true });
    expect(navigation[0][1]).toBe("top-right");
    expect(scale.map(([, position]) => position)).toEqual(["bottom-left"]);
  });

  it("opens with the attribution folded, and leaves it open once the reader opens it", () => {
    const map = start({
      kind: "extent",
      camera,
      basemap: null,
      bbox: [12, 41, 13, 42],
    });
    const attribution = document.createElement("details");
    attribution.className =
      "maplibregl-ctrl maplibregl-ctrl-attrib maplibregl-compact maplibregl-compact-show";
    (map.options.container as HTMLElement).append(attribution);

    map.fire("idle");
    const folded = !attribution.classList.contains("maplibregl-compact-show");
    attribution.classList.add("maplibregl-compact-show");
    map.fire("idle");

    expect(folded).toBe(true);
    expect(attribution.classList.contains("maplibregl-compact")).toBe(true);
    expect(attribution.classList.contains("maplibregl-compact-show")).toBe(
      true,
    );
  });

  it("fits one point without zooming past the streets", () => {
    const point = {
      type: "FeatureCollection" as const,
      features: [collection.features[0]],
    };
    const map = start({
      kind: "features",
      camera: { ...camera, fitData: true },
      basemap: null,
      data: point,
    });

    map.fire("load");

    expect(map.fitted).toEqual([[12.5, 41.9, 12.5, 41.9]]);
    expect(map.fitOptions[0]).toMatchObject({ maxZoom: 16 });
  });

  it("fills a bbox field with the bounds of the map", () => {
    const map = start({
      kind: "extent",
      camera,
      basemap: null,
      bbox: [12, 41, 13, 42],
    });
    const input = document.createElement("input");
    input.id = "field-bbox";
    const button = document.createElement("button");
    button.dataset.fgaBboxTarget = "field-bbox";
    document.body.append(input, button);
    map.fire("load");

    button.click();

    expect(input.value).toBe("12.000000,41.000000,13.000000,42.000000");
    expect(map.fitted).toEqual([[12, 41, 13, 42]]);
  });
});

describe("the worker", () => {
  it("points MapLibre at the worker the build emits", () => {
    expect(maplibre.setWorkerUrl).toHaveBeenCalledTimes(1);
    expect(String(maplibre.setWorkerUrl.mock.calls[0][0])).toContain(
      "maplibre-gl-worker",
    );
  });
});
