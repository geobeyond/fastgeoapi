# fastgeoapi-html

The HTML pages of [fastgeoapi](https://github.com/geobeyond/fastgeoapi): the
Jinja templates, the message catalogs and the compiled stylesheet and
scripts. Install it with `pip install "fastgeoapi[html]"` and set
`DEV_FASTGEOAPI_HTML_PAGES=native` (`PROD_FASTGEOAPI_HTML_PAGES=native` in
production).

The package holds files only. The code that renders the pages is part of
fastgeoapi, which pins this package to its own version.

[Native HTML pages](https://geobeyond.github.io/fastgeoapi/operators/how-to/html-pages/)
in the fastgeoapi documentation covers the configuration, the languages,
the maps and how to replace a template with your own.
