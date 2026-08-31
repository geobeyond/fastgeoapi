# Serving

You are standing up an OGC API and keeping it running: choosing an
authentication chain, pointing collections at data, changing a
configuration that is already serving traffic.

<div class="grid cards" markdown>

- :material-school: **[Tutorials](tutorials/getting-started.md)**

  Learning-oriented. Start here if you have never run fastgeoapi: an
  instance up and behind authentication, from nothing.

- :material-wrench: **[How-to guides](how-to/index.md)**

  Task-oriented. You know what you want; these say how — data in a
  bucket, GeoParquet collections, editing a live configuration,
  turning on the MCP endpoint.

- :material-book-open-variant: **[Reference](reference/configuration.md)**

  Information-oriented. Every configuration key, every command, with
  no narrative attached.

</div>

- :material-lightbulb: **[Explanation](explanation/why-fastgeoapi.md)**

  Understanding-oriented. What fastgeoapi adds to pygeoapi, and why
  each piece is there.

</div>

## The two things that surprise people

**pygeoapi has no authentication.** That is most of what fastgeoapi is
for, and it is why the getting-started tutorial spends its length there
rather than on collections.

**A configuration does not have to be a local file, and applying it does
not have to be a restart.** It can live in a bucket, and a webhook
re-reads it in place. That changes what "changing the configuration"
means, which is why it has [an editor](how-to/configuration-editor.md)
of its own.
