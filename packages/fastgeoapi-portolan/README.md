# fastgeoapi-portolan

Reads a [Portolan](https://github.com/portolan-sdi) catalog and writes the
pygeoapi resources that serve its GeoParquet and PMTiles collections with
[fastgeoapi](https://github.com/geobeyond/fastgeoapi). It prints them, or
merges them into an existing configuration and runs again when the catalog
changes.

It supports Python 3.10 and later, and comes with two commands that share
options, messages and exit codes.

From fastgeoapi, with the extra that also installs the providers the
resources need:

```bash
pip install "fastgeoapi[portolan]"
fastgeoapi config ingest --from-portolan https://example.org/catalog/ --into pygeoapi-config.yml
```

From portolan-cli, which loads it as a command plugin in the versions that
have them (the releases up to 1.0.0b0 do not):

```bash
pip install fastgeoapi-portolan
portolan fastgeoapi ingest --from-portolan ./catalog
```

The [guide](https://geobeyond.github.io/fastgeoapi/operators/how-to/portolan-ingest/)
covers what each collection becomes, how a configuration is merged and
checked before it is written, and the limits of the reader.
