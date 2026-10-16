---
icon: material/web
---

# :material-web: Serving the native HTML pages

The resources the API serves as JSON also have HTML pages at the same
URLs, which a browser gets with `f=html` or by sending `Accept: text/html`.
By default those pages come from pygeoapi's templates. fastgeoapi has its
own pages in the `fastgeoapi-html` package, and you can serve them
instead. The JSON responses are the same either way.

The native pages draw their maps with MapLibre: tile collections appear
in the styles you configured for them, and map collections as the images
the server renders. A process page has a form
that runs the process, and a job page follows the job until it ends. The
pages come in English and Italian.

## Turn them on

Install the `html` extra:

```shell
pip install "fastgeoapi[html]"
```

Then ask for the native pages in your `.env` file:

```shell
# For development
DEV_FASTGEOAPI_HTML_PAGES=native

# For production
PROD_FASTGEOAPI_HTML_PAGES=native
```

The extra brings in `fastgeoapi-html`, a package that holds files only:
the Jinja templates, the message catalogs, and the compiled stylesheet
and scripts. fastgeoapi pins it to its own version, so upgrading
`fastgeoapi[html]` upgrades both.

The default value, `pygeoapi`, keeps pygeoapi's pages. When the variable
says `native` and the package is not installed, the server does not
start, and the error says what to install:

```
HtmlPagesUnavailableError: native HTML pages need the fastgeoapi-html package: install fastgeoapi[html], or set DEV_FASTGEOAPI_HTML_PAGES (PROD_FASTGEOAPI_HTML_PAGES in production) to pygeoapi
```

From a checkout, `uv sync --extra html` installs the package from the
repository. Its compiled assets come from the frontend build: see
[the HTML pages](../../contributors/how-to/development-setup.md#the-html-pages)
in the development setup.

## The pages

The paths below are relative to the API's context, `FASTGEOAPI_CONTEXT`.

| Path                                                                      | Page                                                               |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `/`                                                                       | the landing page                                                   |
| `/conformance`                                                            | the conformance classes the server declares                        |
| `/collections`                                                            | the collections                                                    |
| `/collections/{id}`                                                       | one collection, with its map                                       |
| `/collections/{id}/items`                                                 | the features on a map, with a form that filters them, page by page |
| `/collections/{id}/items/{itemId}`                                        | one feature and its properties                                     |
| `/collections/{id}/queryables`, `/collections/{id}/schema`                | the properties a filter can use, and the collection schema         |
| `/collections/{id}/tiles`, `/collections/{id}/tiles/{tms}`                | the tilesets, and one tileset drawn on the map                     |
| `/collections/{id}/coverage`                                              | a coverage: its bands, and a form that narrows the download        |
| `/collections/{id}/position`, `area`, `cube` and the other EDR queries    | an EDR query: its form, the domain and its axes, the parameters    |
| `/collections/{id}/instances`, `/collections/{id}/instances/{instanceId}` | the EDR instances, and one instance                                |
| `/stac`, `/stac/{path}`                                                   | a STAC catalog or item, with its catalogs, items and assets        |
| `/TileMatrixSets`, `/TileMatrixSets/{id}`                                 | the tile matrix sets                                               |
| `/processes`, `/processes/{id}`                                           | the processes, and one process with the form that runs it          |
| `/jobs`, `/jobs/{jobId}`, `/jobs/{jobId}/results`                         | the jobs, one job as it runs, and its results                      |
| `/openapi`                                                                | the API definition in Swagger UI, or in ReDoc with `ui=redoc`      |

Each page links the other formats of the same resource, and its `Link`
header lists them as `alternate`.

## Languages

The pages are available in the languages listed in `server.languages`
of the pygeoapi configuration. A reader picks one with the `lang`
parameter or through the browser's `Accept-Language`, and the header of
each page links the others. The package has catalogs for English and Italian. In a
language with no catalog the text stays in English, while dates and
numbers are still written the way that language writes them.

Every page answers with `Content-Language` and with
`Vary: Accept, Accept-Language`, so a cache in front keeps one copy per
language and format.

## Maps

### The background

The maps are drawn over `server.map`, the key pygeoapi's own pages use:

```yaml
server:
  map:
    url: https://tile.openstreetmap.org/{z}/{x}/{y}.png
    attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    # fastgeoapi only: a MapLibre style to draw on instead of the tiles of `url`
    style: https://example.com/styles/basemap.json
```

`style` is optional and pygeoapi ignores it. It takes an `http` or
`https` URL. When the style fails to load, or takes more than four
seconds, the maps use the raster tiles of `url` instead. Without
`server.map.url` the maps show the data with no background.

### Where a map opens

A page that shows data, such as the items of a collection or one
feature, fits the map to that data. Otherwise the map opens on the first
of these that exists:

1. the collection's `view`, described below;
2. on tile pages, the center in the TileJSON, when its zoom is above 0;
3. the collection's first spatial extent;
4. the whole world.

`view` is a key fastgeoapi adds to a collection: a center, as longitude
and latitude, and a zoom level.

```yaml
resources:
  places:
    type: collection
    view:
      center: [12.49, 41.89]
      zoom: 14
```

Set it when the extent alone opens the map in the wrong place: a global
extent over data that sits in one city, or tiles that exist only at a
high zoom.

### Tiles and map images

A tile collection is drawn from its TileJSON. Its styles come from the
first of these that has any: a map provider in the same collection, the
`styles` or the `style` option of its tile provider (see the
`options.styles` and `options.style` rows of the
[PMTiles provider](pmtiles.md#configuration)), or a default style built
from the tiles themselves. When there are several, a control on the map
switches between them.

A collection with a map provider is drawn from the images the server
renders. Those maps do not zoom out below 2, because an image of the
whole world can take long enough to time out.

### Width

On a screen wider than 900 pixels the map sits beside the opening block
of the page. The ⤢ control on the map, labelled "Widen the map",
stretches it across the page, and pressing it again narrows it back. On
a narrower screen the page has one column and the control is hidden.

## Your own templates

Point `FASTGEOAPI_HTML_TEMPLATES` at a directory of templates:

```shell
DEV_FASTGEOAPI_HTML_TEMPLATES=/srv/fastgeoapi/templates
```

A template in that directory replaces the package's template of the same
name. Any template you leave out still comes from the package, so the
directory needs only the files you change. Start from a copy of the
package's file; this prints where they are:

```shell
python -c "import fastgeoapi_html; print(fastgeoapi_html.TEMPLATES)"
```

Every page extends `_layout.html`, which holds the header and the footer,
so replacing that one file changes them on every page. The header shows
`server.logo` and the browser tab `server.icon` from the pygeoapi
configuration, as on pygeoapi's pages; without them you get pygeoapi's
logo and icon.

Text you add to a template is shown as you wrote it, in every language:
the catalogs translate only the strings of the package.

!!! warning "Check your copies after an upgrade"

    A copied template matches the release you copied it from. A later
    release may pass a page new values or rename a block, and your copy
    will not have them. After upgrading, compare your files with the
    package's.

## Behind a proxy

The pages build their links from the server URL of the configuration,
as pygeoapi's JSON does. With `FASTGEOAPI_REVERSE_PROXY=true` they are
rewritten for the forwarded host along with the JSON; see
[behind a proxy](../tutorials/getting-started.md#behind-a-proxy).

The compiled stylesheet and scripts are served under `/_html` below the
context, with `Cache-Control: public, max-age=31536000, immutable`. Their
file names change with their content, so a cache can keep them for the
whole year. A proxy that filters paths has to let `/_html` through, or
the pages arrive without their style and their maps.
