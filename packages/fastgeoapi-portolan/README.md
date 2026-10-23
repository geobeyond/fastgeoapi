# fastgeoapi-portolan

Reads a [Portolan](https://github.com/portolan-sdi) catalog and writes the
pygeoapi resources that serve its GeoParquet and PMTiles collections with
[fastgeoapi](https://github.com/geobeyond/fastgeoapi).

Install it with `pip install "fastgeoapi[portolan]"` to run
`fastgeoapi config ingest`, or with `pip install fastgeoapi-portolan` next to
portolan-cli to run `portolan fastgeoapi ingest`. It supports Python 3.10 and
later.
