import "maplibre-gl/dist/maplibre-gl.css";
import { Map as MapLibreMap, setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

import { readConfig } from "./config";

// MapLibre finds its worker next to its own module, under a name the build
// never emits: the worker is built on its own and its URL handed over.
setWorkerUrl(workerUrl);

export type Bbox = [number, number, number, number];

export interface Feature {
  type: "Feature";
  properties: Record<string, unknown> | null;
  geometry: {
    type: string;
    coordinates?: unknown;
    geometries?: unknown[];
  } | null;
  id?: string | number;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: Feature[];
}

export interface Camera {
  center?: [number, number];
  zoom?: number;
  bounds?: Bbox;
  minZoom?: number;
  fitData?: boolean;
}

export interface Basemap {
  url: string;
  attribution: string;
}

interface Labels {
  style: string;
}

export type MapConfig =
  | {
      kind: "tiles";
      camera: Camera;
      styles: { name: string; style: object }[];
      labels: Labels;
    }
  | {
      kind: "image";
      camera: Camera;
      basemap: Basemap | null;
      maps: { name: string; url: string }[];
      maxSize: number;
      labels: Labels;
    }
  | {
      kind: "features";
      camera: Camera;
      basemap: Basemap | null;
      data: FeatureCollection | string;
    }
  | { kind: "extent"; camera: Camera; basemap: Basemap | null; bbox: Bbox };

/** The part of a MapLibre source the island uses: an image's or a GeoJSON one's. */
export interface SourceLike {
  updateImage(image: object): void;
  setData(data: object): void;
}

/** The part of a MapLibre map the island uses: a fake stands in for it in tests. */
export interface MapLike {
  on(event: string, handler: () => void): void;
  addSource(id: string, source: object): void;
  getSource(id: string): SourceLike | undefined;
  addLayer(layer: object): void;
  setStyle(style: object): void;
  fitBounds(bounds: Bbox, options?: object): void;
  getBounds(): {
    getWest(): number;
    getSouth(): number;
    getEast(): number;
    getNorth(): number;
  };
  getCanvas(): { clientWidth: number; clientHeight: number };
}

export type MapClass = new (options: Record<string, unknown>) => MapLike;

const ACCENT = "#2c6db5";
const ACTIVE = "#d97706";
const DATA = "fga-data";
/** The feature under the pointer, drawn on its own above the others: points can overlap. */
const HOVERED = "fga-active";
/** The closest a map zooms to fit its data: one point would otherwise ask for zoom 22. */
const FIT_MAX_ZOOM = 16;
/** The deepest basemap tiles there are: past them MapLibre enlarges the last ones. */
const BASEMAP_MAX_ZOOM = 19;
const IMAGE = "fga-image";

/** The URL of a map image of ``bounds``, at the canvas size or less. */
export function mapImageUrl(
  base: string,
  bounds: Bbox,
  width: number,
  height: number,
  maxSize: number,
): string {
  const scale = Math.min(1, maxSize / Math.max(width, height, 1));
  const url = new URL(base);
  url.searchParams.set(
    "bbox",
    bounds.map((value) => value.toFixed(6)).join(","),
  );
  url.searchParams.set("width", String(Math.max(1, Math.round(width * scale))));
  url.searchParams.set(
    "height",
    String(Math.max(1, Math.round(height * scale))),
  );
  url.searchParams.set("f", "png");
  return url.toString();
}

/** A polygon feature of a box. */
export function extentFeature(bbox: Bbox): Feature {
  const [w, s, e, n] = bbox;
  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [w, s],
          [e, s],
          [e, n],
          [w, n],
          [w, s],
        ],
      ],
    },
  };
}

function collect(value: unknown, points: number[][]): void {
  if (Array.isArray(value) && typeof value[0] === "number") {
    points.push(value as number[]);
  } else if (Array.isArray(value)) {
    value.forEach((item) => collect(item, points));
  }
}

/** The bounds of every coordinate of the features; null when there is none. */
export function dataBounds(data: FeatureCollection): Bbox | null {
  const points: number[][] = [];
  data.features.forEach((feature) => {
    collect(feature.geometry?.coordinates, points);
    (feature.geometry?.geometries ?? []).forEach((geometry) =>
      collect((geometry as { coordinates?: unknown }).coordinates, points),
    );
  });
  if (points.length === 0) {
    return null;
  }
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

interface Style {
  version: 8;
  sources: object;
  layers: { id: string; type: string; source?: string; paint?: object }[];
}

/** The style a map of features or images starts from: the basemap, or a plain background. */
export function baseStyle(basemap: Basemap | null): Style {
  if (basemap === null) {
    return {
      version: 8,
      sources: {},
      layers: [
        {
          id: "background",
          type: "background",
          paint: { "background-color": "#eef2f6" },
        },
      ],
    };
  }
  return {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: [basemap.url.replace("{s}", "a")],
        tileSize: 256,
        maxzoom: BASEMAP_MAX_ZOOM,
        attribution: basemap.attribution,
      },
    },
    layers: [{ id: "basemap", type: "raster", source: "basemap" }],
  };
}

/** Fill, line and point layers of a GeoJSON source, in ``color``. */
export function dataLayers(source: string, color: string = ACCENT): object[] {
  return [
    {
      id: `${source}-fill`,
      type: "fill",
      source,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": color, "fill-opacity": 0.25 },
    },
    {
      id: `${source}-line`,
      type: "line",
      source,
      filter: ["!=", ["geometry-type"], "Point"],
      paint: { "line-color": color, "line-width": 2 },
    },
    {
      id: `${source}-point`,
      type: "circle",
      source,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-color": color,
        "circle-radius": 5,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1,
      },
    },
  ];
}

function boundsOf(map: MapLike): Bbox {
  const bounds = map.getBounds();
  return [
    bounds.getWest(),
    bounds.getSouth(),
    bounds.getEast(),
    bounds.getNorth(),
  ];
}

function corners([w, s, e, n]: Bbox): number[][] {
  return [
    [w, n],
    [e, n],
    [e, s],
    [w, s],
  ];
}

function picker(
  names: string[],
  label: string,
  choose: (index: number) => void,
): HTMLSelectElement {
  const select = document.createElement("select");
  select.className = "style-picker";
  select.setAttribute("aria-label", label);
  names.forEach((name, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = name;
    select.append(option);
  });
  select.addEventListener("change", () => choose(Number(select.value)));
  return select;
}

const NOTHING: FeatureCollection = { type: "FeatureCollection", features: [] };

function addData(map: MapLike, data: FeatureCollection | string): void {
  map.addSource(DATA, { type: "geojson", data });
  dataLayers(DATA).forEach((layer) => map.addLayer(layer));
  map.addSource(HOVERED, { type: "geojson", data: NOTHING });
  dataLayers(HOVERED, ACTIVE).forEach((layer) => map.addLayer(layer));
}

function linkPage(map: MapLike, data: FeatureCollection | null): void {
  document
    .querySelectorAll<HTMLElement>("[data-fga-feature]")
    .forEach((item) => {
      const feature = data?.features[Number(item.dataset.fgaFeature)];
      if (feature === undefined) {
        return;
      }
      item.addEventListener("mouseenter", () =>
        map
          .getSource(HOVERED)
          ?.setData({ type: "FeatureCollection", features: [feature] }),
      );
      item.addEventListener("mouseleave", () =>
        map.getSource(HOVERED)?.setData(NOTHING),
      );
    });
  document
    .querySelectorAll<HTMLElement>("[data-fga-bbox-target]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        const input = document.getElementById(
          button.dataset.fgaBboxTarget ?? "",
        );
        if (input instanceof HTMLInputElement) {
          input.value = boundsOf(map)
            .map((value) => value.toFixed(6))
            .join(",");
        }
      });
    });
}

/** Builds the map of ``config`` inside ``element``. */
export function startMap(
  element: HTMLElement,
  config: MapConfig,
  MapType: MapClass = MapLibreMap as unknown as MapClass,
): MapLike {
  const container = document.createElement("div");
  container.className = "fga-map-canvas";
  let image = 0;
  let map: MapLike;
  const refreshImage = (): void => {
    if (config.kind !== "image") {
      return;
    }
    const canvas = map.getCanvas();
    const bounds = boundsOf(map);
    const url = mapImageUrl(
      config.maps[image].url,
      bounds,
      canvas.clientWidth,
      canvas.clientHeight,
      config.maxSize,
    );
    const source = map.getSource(IMAGE);
    if (source === undefined) {
      map.addSource(IMAGE, {
        type: "image",
        url,
        coordinates: corners(bounds),
      });
      map.addLayer({ id: IMAGE, type: "raster", source: IMAGE });
    } else {
      source.updateImage({ url, coordinates: corners(bounds) });
    }
  };
  if (config.kind === "tiles" && config.styles.length > 1) {
    element.append(
      picker(
        config.styles.map((style) => style.name),
        config.labels.style,
        (index) => map.setStyle(config.styles[index].style),
      ),
    );
  }
  if (config.kind === "image" && config.maps.length > 1) {
    element.append(
      picker(
        config.maps.map((each) => each.name),
        config.labels.style,
        (index) => {
          image = index;
          refreshImage();
        },
      ),
    );
  }
  element.append(container);
  const camera = config.camera;
  map = new MapType({
    container,
    style:
      config.kind === "tiles"
        ? config.styles[0].style
        : baseStyle(config.basemap),
    center: camera.center ?? [0, 0],
    zoom: camera.zoom ?? 0,
    minZoom: camera.minZoom ?? 0,
    attributionControl: { compact: true },
  });
  map.on("load", () => {
    if (config.kind === "features") {
      addData(map, config.data);
    } else if (config.kind === "extent") {
      addData(map, {
        type: "FeatureCollection",
        features: [extentFeature(config.bbox)],
      });
    }
    const fit =
      config.kind === "extent"
        ? config.bbox
        : config.kind === "features" &&
            camera.fitData &&
            typeof config.data !== "string"
          ? dataBounds(config.data)
          : camera.bounds;
    if (fit) {
      map.fitBounds(fit, {
        padding: 24,
        animate: false,
        maxZoom: FIT_MAX_ZOOM,
      });
    }
    refreshImage();
    linkPage(
      map,
      config.kind === "features" && typeof config.data !== "string"
        ? config.data
        : null,
    );
  });
  map.on("moveend", refreshImage);
  return map;
}

class FgaMap extends HTMLElement {
  connectedCallback(): void {
    startMap(this, readConfig<MapConfig>(this));
  }
}

if (!customElements.get("fga-map")) {
  customElements.define("fga-map", FgaMap);
}
