"""Turn the collections of a Portolan catalog into pygeoapi resources for fastgeoapi.

The package reads catalogs and writes YAML only. It never imports fastgeoapi
or pygeoapi: the providers it configures are named as strings, and what it
needs from fastgeoapi, a validator, arrives through an entry point.
"""
