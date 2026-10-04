import {
  baseStyle,
  dataBounds,
  extentFeature,
  indexed,
  mapImageUrl,
  startMap,
  type FeatureCollection,
  type MapConfig,
} from "./map";

const maplibre = vi.hoisted(() => ({ setWorkerUrl: vi.fn() }));

vi.mock("maplibre-gl", () => ({
  Map: class {},
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
  states: unknown[] = [];
  images: unknown[] = [];
  bounds: [number, number, number, number] = [12, 41, 13, 42];

  constructor(options: Record<string, unknown>) {
    this.options = options;
    FakeMap.last = this;
  }
  on(event: string, handler: Handler) {
    (this.handlers[event] ??= []).push(handler);
  }
  fire(event: string) {
    (this.handlers[event] ?? []).forEach((handler) => handler());
  }
  addSource(id: string, source: Record<string, unknown>) {
    this.sources[id] = source;
  }
  getSource(id: string) {
    return id in this.sources
      ? { updateImage: (image: unknown) => this.images.push(image) }
      : undefined;
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
  setFeatureState(feature: unknown, state: unknown) {
    this.states.push([feature, state]);
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

  it("numbers the features so that the list can find them", () => {
    expect(
      indexed(collection).features.map(
        (feature) => feature.properties?.fga_index,
      ),
    ).toEqual([0, 1]);
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

  it("draws the features of the page and highlights the one under the pointer", () => {
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

    expect(map.sources["fga-data"].promoteId).toBe("fga_index");
    expect(map.fitted).toEqual([[12, 41, 14, 43]]);
    expect(map.states).toEqual([
      [{ source: "fga-data", id: 1 }, { active: true }],
    ]);
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
