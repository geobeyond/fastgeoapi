# Getting started

## Development

TBD

## Production

TDB

### Behind a proxy

If the deployment is operated behind a proxy (i.e. Traefik, Nginx, WSO2 Gateway, etc), fastgeoapi provides a reverse proxy configuration to return the pygeoapi links accordingly to the urls called by the users.
The configuration is disabled by default with the following configuration `PROD_FASTGEOAPI_REVERSE_PROXY=false` in the `.env` file. The most relevant configurations for production in a reverse proxy scenario are:

- `PROD_FASTGEOAPI_CONTEXT`: the base path where pygeoapi is operated, i.e. `/geoapi`
- `PROD_FASTGEOAPI_REVERSE_PROXY`: boolean flag to enable or disable the reverse proxy configuration, i.e. `true`

At runtime, if the variable `FASTGEOAPI_REVERSE_PROXY` has the value `true` the returned pygeoapi links are dynamic. This means, for example, that a Kubernetes Ingress with multiple hosts might be supported
in a transparent way:

```yml
# snippet example of a kubernetes ingress with multiple hosts
spec:
  rules:
  - host: public.pygeoapi.io
    http:
      paths:
      - backend:
          serviceName: fastgeoapi-svc
          servicePort: 5000
        path: /geoapi
        pathType: ImplementationSpecific
  - host: private.pygeoapi.io
    http:
      paths:
      - backend:
          serviceName: fastgeoapi-svc
          servicePort: 5000
        path: /geoapi
        pathType: ImplementationSpecific
```

If the user calls the public url `http://public.pygeoapi.io` the response contains the links which respect this base url without the need to have it hard-coded in the pygeoapi configuration `pygeoapi-config.yml`.

<!-- termynal -->

```shell
# Using a security scheme driven by an api-key
$ curl -H "X-API-KEY: pygeoapi" http://public.pygeoapi.io/geoapi/collections/obs

{
    "id":"obs",
    "title":"Observations",
    "description":"My cool observations",
    "keywords":[
        "observations",
        "monitoring"
    ],
    "links":[
        {
            "type":"text/csv",
            "rel":"canonical",
            "title":"data",
            "href":"https://github.com/mapserver/mapserver/blob/branch-7-0/msautotest/wxs/data/obs.csv",
            "hreflang":"en-US"
        },
        {
            "type":"text/csv",
            "rel":"alternate",
            "title":"data",
            "href":"https://raw.githubusercontent.com/mapserver/mapserver/branch-7-0/msautotest/wxs/data/obs.csv",
            "hreflang":"en-US"
        },
        {
            "type":"application/json",
            "rel":"root",
            "title":"The landing page of this server as JSON",
            "href":"http://public.pygeoapi.io/geoapi?f=json"
        },
        {
            "type":"text/html",
            "rel":"root",
            "title":"The landing page of this server as HTML",
            "href":"http://public.pygeoapi.io/geoapi?f=html"
        },
        {
            "type":"application/json",
            "rel":"self",
            "title":"This document as JSON",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"alternate",
            "title":"This document as RDF (JSON-LD)",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"alternate",
            "title":"This document as HTML",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs?f=html"
        },
        {
            "type":"application/schema+json",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as JSON",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/queryables?f=json"
        },
        {
            "type":"text/html",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as HTML",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/queryables?f=html"
        },
        {
            "type":"application/geo+json",
            "rel":"items",
            "title":"items as GeoJSON",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/items?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"items",
            "title":"items as RDF (GeoJSON-LD)",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/items?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"items",
            "title":"Items as HTML",
            "href":"http://public.pygeoapi.io/geoapi/collections/obs/items?f=html"
        }
    ],
    "extent":{
        "spatial":{
            "bbox":[
                [
                    -180,
                    -90,
                    180,
                    90
                ]
            ],
            "crs":"http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        },
        "temporal":{
            "interval":[
                [
                    "2000-10-30T18:24:39+00:00",
                    "2007-10-30T08:57:29+00:00"
                ]
            ]
        }
    },
    "itemType":"feature",
    "crs":[
        "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    ],
    "storageCRS":"http://www.opengis.net/def/crs/OGC/1.3/CRS84"
}
```

The same result would have been got if a private endpoint is hit, i.e. `http://private.pygeoapi.io/geoapi/collections/obs`
