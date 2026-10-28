---
icon: material/compass-outline
---

# :material-compass-outline: Ingesting a Portolan catalog

A [Portolan](https://github.com/portolan-sdi) catalog describes data that
already sits in a bucket: STAC documents for the catalog and its
collections, GeoParquet tables and PMTiles archives next to them. The
ingest command reads such a catalog and writes the pygeoapi resources that
serve its collections, using the GeoParquet and PMTiles providers. It can
print them, or merge them into the configuration you already keep, and it
runs again whenever the catalog changes.

```bash
pip install "fastgeoapi[portolan]"
fastgeoapi config ingest --from-portolan https://example.org/catalog/
```

The extra installs `fastgeoapi-portolan` together with the `geoparquet` and
`pmtiles` extras, so the resources it writes can also be served. Without
it, `fastgeoapi config ingest` is still listed, and it says which extra to
install.

## Two commands, one implementation

The same command is a plugin of portolan-cli:

```bash
pip install fastgeoapi-portolan
portolan fastgeoapi ingest --from-portolan ./catalog
```

Both run the code of `fastgeoapi-portolan`, so their options, messages and
exit codes are the same. The package supports Python 3.10 and later, as
portolan-cli does; fastgeoapi itself needs 3.12. portolan-cli loads it
only in a version with command plugins, which the releases up to 1.0.0b0
do not have.

`--from-portolan` takes the root `catalog.json` or the folder that holds
it, as a local path or a URL: `https://`, `s3://`, `gs://` or `az://`.
For a catalog in a bucket, pass the storage options the way a fastgeoapi
configuration spells them:

```bash
fastgeoapi config ingest --from-portolan s3://my-bucket/catalog/ \
  --store-option region=eu-west-1 --store-option skip_signature=true
```

`true` and `false` are read as booleans and every other value as a string.
The same options also go into each provider the command writes.

## Printing or merging

Without `--into`, the command prints a `resources:` block on stdout and a
summary of what it did on stderr, so the YAML can be redirected on its own:

```bash
fastgeoapi config ingest --from-portolan ./catalog > resources.yml
```

With `--into`, it merges the resources into a configuration document, a
local path or a bucket URL, writes it back to the same place, and prints
the summary on stdout:

```bash
fastgeoapi config ingest --from-portolan ./catalog --into pygeoapi-config.yml
```

```
catalog: /srv/catalog/catalog.json
into: pygeoapi-config.yml
added:
  roads
    data: collection asset
    id_field: id (column name)
    geometry_column: geometry (column name)
skipped:
  dem: format not handled yet: image/tiff; application=geotiff; profile=cloud-optimized
warnings:
  the catalog declares no Portolan schema: read as plain STAC
```

Under each resource the summary lists where its values came from, so a
guess the command made can be checked and overridden. `--json` prints the
same summary as JSON:

```json
{
  "catalog": "/srv/catalog/catalog.json",
  "into": "pygeoapi-config.yml",
  "added": ["roads"],
  "updated": [],
  "skipped": [{ "collection": "dem", "reason": "format not handled yet: ..." }],
  "missing": [],
  "pruned": [],
  "choices": { "roads": ["data: collection asset", "..."] },
  "warnings": ["the catalog declares no Portolan schema: read as plain STAC"]
}
```

| Exit code | When                                                                                                                                                                                        |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`       | the resources were printed or written, even if some collections were skipped                                                                                                                |
| `1`       | an error, and nothing was written: an unreadable root, a document that would not validate, a concurrent edit, or, with `--strict`, a skipped collection or a problem found by `--check-ids` |
| `2`       | the command line itself is wrong, such as a missing `--from-portolan`                                                                                                                       |

Writing a configuration does not put it into service. As with the
[editor](configuration-editor.md), the command never calls the reload
webhook; reload when you have checked the result.

## What a collection becomes

Each collection the handlers can serve becomes one resource, with the
collection's id as its id (put `--prefix` in front to keep two catalogs
apart). The resource takes from the collection:

- `title`, `description` and `keywords`;
- `links`: the README (`describedby`), the source (`via`) and the license,
  made absolute; a license given only as an SPDX id gets a link to its
  SPDX page;
- `extents`: the first `bbox` in CRS84 and the first temporal interval;
- `providers`: one per handler that recognises the collection's assets;
- `ingest`: where the resource came from (see [Provenance](#provenance)).

A collection without a title, a description or a spatial extent is skipped,
and the summary gives the reason. A Portolan catalog always has them; a
plain STAC catalog may not, since STAC does not require a title.
`--collection <id>`, repeatable, ingests only the collections named.

### GeoParquet collections

The handler looks for the data in this order:

1. `partition:glob`, when the collection declares it, resolved against the
   collection;
2. a collection asset of type `application/vnd.apache.parquet` with the
   role `data`; its `alternate.s3.href` wins when it is an `s3://` URL;
3. the data assets of the collection's items, which all have to sit in one
   folder; the provider then reads `<folder>/*.parquet`.

An `https://` URL of an S3 bucket, virtual-hosted or path-style, is
rewritten as an `s3://` URL with the bucket's region and unsigned reads, so
DuckDB reads it as a bucket. An `s3` alternate in the bucket of the asset's
`https://` URL gets the same region and unsigned reads.
Data at any other `https://` URL is written as it is when it names one
`.parquet` file; a glob or a folder there is skipped with the reason,
since HTTP cannot list the files.

The id column and the geometry column come from the first source that
names them:

| Column   | 1st                                  | 2nd                                                  | 3rd                                       |
| -------- | ------------------------------------ | ---------------------------------------------------- | ----------------------------------------- |
| id       | `table:primary_key`, with one column | a column called `id`, `fid`, `objectid` or `gid`     | `--id-field <collection>=<column>`        |
| geometry | `table:primary_geometry`             | a column called `geometry`, `geom` or `wkb_geometry` | `--geometry-column <collection>=<column>` |

Column names come from `table:columns` in the collection, in its data
asset, in its items and in their properties. When none fits, the
collection is skipped and the reason names the option to pass. A
partitioned collection with an item that does not conform is skipped as a
whole, with the items named: serving half a dataset would be worse.

A guessed id column may not be unique, and the provider then answers
`/items/{id}` with one of the features that share the id. `--check-ids`
reads only the id column of each GeoParquet collection and counts the rows
that repeat an id or have none. A count above zero is a warning in the
summary:

```text
warnings:
  roads: the id column id is not unique: 2 rows repeat an id or have none
```

Data that cannot be read gets a warning too, with DuckDB's message. With
`--strict` either one stops the command before it prints or writes. The
option needs duckdb, which the `portolan` extra of fastgeoapi installs;
with the portolan-cli plugin, run `pip install duckdb`.

### PMTiles collections

The archive is the collection's asset of type `application/vnd.pmtiles`
with the role `visual`, or else its link with `rel: pmtiles`. The catalog
says neither the zoom nor the tile format, so the command reads both from
the archive by byte range:

- the zoom span of the `vector_layers` in the archive's metadata, or the
  header's when there are none;
- the format from the tile type: `pbf`, `png`, `jpg`, `webp` or `avif`. An
  archive of another type is skipped.

The assets with the role `style` become the collection's named styles. A
style is named by its `title`, or else by its key without a `style-`
prefix or a `-style` suffix, and the one with the role `default` opens the
pages. A style is kept only when one of its sources reads the archive,
through the same URL or a file of the same name, and all the kept styles
have to call that source by the same name, which becomes `style_source`.
The summary explains every style left out.

### Formats not handled yet

A collection with data neither handler reads, such as a Cloud Optimized
GeoTIFF or a FlatGeobuf file, is skipped with the media types it has:

```
dem: format not handled yet: image/tiff; application=geotiff; profile=cloud-optimized
```

## Merging into a configuration

### Provenance

Every resource the command writes carries the catalog and the collection
it came from:

```yaml
ingest:
  from: portolan
  catalog: https://example.org/catalog/catalog.json
  collection: roads
  schema: https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json
```

There is no date in it, so an ingest that finds nothing new leaves the
document exactly as it was, and does not even write it. The catalog is
stored as its root document: `https://example.org/catalog/` and
`https://example.org/catalog/catalog.json` are the same catalog, and so are
a folder and the `catalog.json` in it.

### What changes, and what stays

Only `resources` changes. Every other line keeps its bytes, comments,
quotes and `${VAR}` placeholders included.

- New collections are added at the end of `resources`.
- Resources with the same provenance are updated key by key. The keys
  the command writes (`type`, `title`, `description`, `keywords`, `links`,
  `extents`, `providers`, `ingest`) are replaced, and the others, such as a
  `view` you added, stay. Among the providers only the GeoParquet and
  PMTiles ones are replaced, so a map provider added by hand stays too.
- A resource with the same id written by hand, or ingested from another
  catalog, is left alone and listed under `skipped`.
- Collections gone from the catalog are listed as missing and kept.
  `--prune` removes them, under three conditions:
  - only resources of this catalog are removed;
  - with `--collection`, only the selected ones;
  - only after a walk that read the whole catalog. If a document could not
    be read or the walk stopped at its limit, a collection may still be
    there, so nothing is pruned and a warning says why. A collection the
    catalog still lists but this run skipped is never missing.
- A collection whose archive, style, metadata or items do not answer
  (anything but a missing or oversized object) is skipped with the
  reason, and its resource stays as it was: a second ingest during an
  outage does not drop a provider or a style. The next run reads it again.

pygeoapi reads `${NAME}` anywhere in the configuration as a variable of
the server's environment. A collection whose text would carry one into
the document, in its id, title, description, keywords, links, style names
or columns, is skipped, and the reason names the field. The
`--store-option` values are yours and are written as given.

### The save rule

Before writing, the command checks the merged document the way the
editor's save does: the document as written first, then what would run
once its placeholders are resolved from the environment. A `${VAR}` with no
value in the environment where the command runs blocks the write, as it
blocks `PUT /editor/config`:

```
error: pygeoapi-config.yml would not be a valid configuration, nothing written:
  ${FASTGEOAPI_CONTEXT} has no value in this environment
```

`portolan fastgeoapi ingest` finds the same check through an entry point
of fastgeoapi, without importing it. Where fastgeoapi is not installed, the
plugin writes and the summary says that the document was not validated.

### Concurrent edits

The command writes only if nobody changed the document since it read it.

- For a local file, its modification time and size are compared before
  writing and again just before the new file replaces it, in one rename. A
  symbolic link stays a link, and the file keeps its permissions.
- For an object in a bucket, the write is conditional on the ETag (and the
  version) read with it. A store that returns neither is refused: the
  command never writes blindly.

When the document changed, the command stops with `changed since it was read: not written` and exit code 1. Run it again on the new version.

## How the reader checks a catalog

The reader walks from the root through its child catalogs down to the
collections. It reads the items of a collection only when a handler needs
them, which is the case for GeoParquet data kept in the items.

Every catalog and collection is checked against the JSON Schemas the
package ships, without going to the network: STAC 1.1.0, the Portolan
profile from v0.1.0 to v0.2.0, and the extensions of the Portolan registry,
such as `table`, `file`, `partition` and `alternate-assets`. They are
copied from [rashid](https://github.com/portolan-sdi/rashid), Portolan's
validator.

- A collection that does not conform is not ingested. The summary lists
  it under `skipped`, with the first error and how many follow:
  `does not conform to <schema>: <where> <what> (+2 more)`. With `--strict`
  it is an error.
- A schema the package does not ship, such as a newer version of an
  extension, is not checked, and one warning names it. The rest of the
  document is still checked, and the collection stays in.
- The profile is the Portolan version a collection declares, or else
  the root's. A collection that declares another version than the root is
  checked against its own, with a warning.
- A catalog without the Portolan profile is read as plain STAC: only
  the STAC and extension schemas apply, and a warning says so.
- The reader does not follow translation trees (`alternate` links with an
  `hreflang`), children linked from a collection, since collections do not
  nest, and links back to documents already read.
- A child that cannot be read, or is not JSON, is skipped with the
  reason, and the walk goes on. A root that cannot be read is an error.

The reader checks the schemas only. Checks on bytes, hosts and rules that
span several documents are rashid's: run it for a full conformance report.

## Limits and trust

The reader follows what a catalog links, so it has limits a catalog cannot
push past:

| Option                 | Default | What it bounds                                                                                  |
| ---------------------- | ------- | ----------------------------------------------------------------------------------------------- |
| `--max-documents`      | 10 000  | documents in one walk, the root included, and items read for one collection                     |
| `--max-document-bytes` | 32 MiB  | each document read: catalogs, collections, items, styles, and the metadata of a PMTiles archive |

- A walk that reaches `--max-documents` stops following links and warns
  how many it left. A collection that links more items than that is
  skipped.
- A document larger than `--max-document-bytes` is skipped with the reason,
  and a style is left out. When it is the root, the command stops. PMTiles
  metadata over the limit is not read, and the zoom comes from the header.

A catalog served over the network cannot reach your disk. A `file:` URL in
a remote document is refused wherever it appears: in a link, a data asset,
a `partition:glob`, a PMTiles archive or a style. A path in a remote
document resolves against the remote host, so it cannot point at local
files either. A fragment (`#...`) in an href is ignored, as it only names a
part of a document.

Ingest catalogs you trust. The reader follows their links to wherever they
point, hosts on your own network included, and the resources it writes
make fastgeoapi read the same places. The command is meant for an operator
running it on a catalog they chose, not for URLs taken from other users.
