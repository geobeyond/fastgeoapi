# Tutorials

## Authentication and Authorization

!!! tip "Familiarize with the topic"
    If you don't have prior experience with the topic, we recommend reading [Authentication and Authorization in Applications](https://www.permit.io/blog/authentication-vs-authorization), which is a really good introduction on the difference between Authentication and Authorization that helps you understand how they focus on two different purposes.

This tutorial aims to guide the user to configure **fastgeoapi** with a mechanism that fits with your security requirements.
The tool supports different security schemes for [OGC APIs](https://ogcapi.ogc.org/) served by [pygeoapi](https://pygeoapi.io) and allows optionally to enable a coarse or fine-grade authorization for a _collection_ and the endpoints based on user needs and use cases.

Supported security schemes are:

- **API KEY**: mostly used for machine to machine communication where a static shared secret can be kept secured or for internal interactions among microservices;
- **OAuth2**: commonly used for authorization to accessing resources between two systems and also for stronger machine to machine communication with external parties when a secret needs to be rotated;
- **OpenID Connect**: It looks like very similar to OAuth2 and in fact it is built on top of that. It allows to identify and authenticate a user in mobile and Single-Page Application (SPA).

!!! note "OAuth2 vs OpenID Connect"
    It is beneficial to clarify that they serve two different purposes. [OAuth2](https://en.wikipedia.org/wiki/OAuth) is a framework for _Authorization_ while [OpenID Connect](https://openid.net/developers/how-connect-works/) is a protocol for _Authentication_. If you would like to develop further the concepts then [this]() is an appropriate read.

## Configure and protect pygeoapi

The protection mechanisms introduced above are mutually exclusive and they apply to the whole `pygeoapi` application that is wrapped by _fastgeoapi_.
The configuration happens in the `.env` file where the environment variables for development and production are defined. As explained in the [getting-started](getting-started.md) section their prefix identifies the target environment (i.e. `DEV_` vs `PROD_`). Let's go through the different mechanisms.

Please make sure to have cloned the [repo](https://github.com/geobeyond/fastgeoapi) before starting the following sections.
Also, it is supposed to having set the environment for development with `ENV_STATE=dev` in the `.env` file.

### API KEY

The security configuration, in this case, can be enabled with these two additional settings:

```yml
# api-keys
DEV_API_KEY_ENABLED=false
DEV_PYGEOAPI_KEY_GLOBAL=pygeoapi
```

Setting `DEV_API_KEY_ENABLE` to `true` is the way to enable a flat protection to the whole `pygeoapi` sub-application. The value sets in the `DEV_PYGEOAPI_KEY_GLOBAL` is the secret key that must be used in the Header `X-API-KEY` to consume the API.

Start the server with the usual command:

<!-- termynal -->

```shell
$ uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload --loop asyncio
...
File "<frozen importlib._bootstrap>", line 1204, in _gcd_import
File "<frozen importlib._bootstrap>", line 1176, in _find_and_load
File "<frozen importlib._bootstrap>", line 1147, in _find_and_load_unlocked
File "<frozen importlib._bootstrap>", line 690, in _load_unlocked
File "<frozen importlib._bootstrap_external>", line 940, in exec_module
File "<frozen importlib._bootstrap>", line 241, in _call_with_frames_removed
File "/Users/francbartoli/code/fastgeoapi/app/main.py", line 188, in <module>
  app = create_app()
        ^^^^^^^^^^^^
File "/Users/francbartoli/code/fastgeoapi/app/main.py", line 138, in create_app
  raise ValueError(
ValueError: OPA_ENABLED, JWKS_ENABLED and API_KEY_ENABLED are mutually exclusive
```

This error is expected since more security schemes at the same time are enabled. Change their value accordingly:

```yml
DEV_API_KEY_ENABLED=true
DEV_OPA_ENABLED=false
DEV_JWKS_ENABLED=false
```

and then start again the server:

<!-- termynal -->

```shell
$ uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload --loop asyncio
...
2024-02-26 12:46:25.447 | DEBUG    | app.main:<module>:190 [id:None] - Global config: DevConfig(ENV_STATE='dev', HOST='0.0.0.0', PORT='5000', ROOT_PATH='', AWS_LAMBDA_DEPLOY=False, LOG_PATH='/tmp', LOG_FILENAME='fastgeoapi.log', LOG_LEVEL='debug', LOG_ENQUEUE=True, LOG_ROTATION='1 days', LOG_RETENTION='1 months', LOG_FORMAT='<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> [id:{extra[request_id]}] - <level>{message}</level>', OPA_ENABLED=False, OPA_URL='http://localhost:8383', APP_URI='http://localhost:5000', OIDC_WELL_KNOWN_ENDPOINT='http://localhost:8282/realms/pygeoapi/.well-known/openid-configuration', OIDC_CLIENT_ID='pygeoapi-client', OIDC_CLIENT_SECRET='2yholx8r3mqyUJaOoJiZhcqvQDQwmgyD', API_KEY_ENABLED=True, JWKS_ENABLED=False, OAUTH2_JWKS_ENDPOINT='https://uat.interop.pagopa.it/.well-known/jwks.json', OAUTH2_TOKEN_ENDPOINT='https://auth.uat.interop.pagopa.it/token.oauth2', PYGEOAPI_KEY_GLOBAL='pygeoapi', PYGEOAPI_BASEURL='http://localhost:5000', PYGEOAPI_CONFIG='pygeoapi-config.yml', PYGEOAPI_OPENAPI='pygeoapi-openapi.yml', PYGEOAPI_SECURITY_SCHEME='http', FASTGEOAPI_CONTEXT='/geoapi')
2024-02-26 12:46:25.448 | INFO     | logging:callHandlers:1706 [id:app] - Started server process [171]
2024-02-26 12:46:25.448 | INFO     | logging:callHandlers:1706 [id:app] - Started server process [171]
2024-02-26 12:46:25.448 | INFO     | logging:callHandlers:1706 [id:app] - Waiting for application startup.
2024-02-26 12:46:25.448 | INFO     | logging:callHandlers:1706 [id:app] - Waiting for application startup.
2024-02-26 12:46:25.449 | INFO     | logging:callHandlers:1706 [id:app] - Application startup complete.
2024-02-26 12:46:25.449 | INFO     | logging:callHandlers:1706 [id:app] - Application startup complete.
```

Let's get testing one of the collection available in the `pygeoapi-config.yml` (i.e. `obs`) without or with the API-KEY:

<!-- termynal -->

```shell
$ curl http://localhost:5000/geoapi/collections/obs -vv

*   Trying [::1]:5000...
* connect to ::1 port 5000 failed: Connection refused
*   Trying 127.0.0.1:5000...
* Connected to localhost (127.0.0.1) port 5000
> GET /geoapi/collections/obs HTTP/1.1
> Host: localhost:5000
> User-Agent: curl/8.4.0
> Accept: */*
>
< HTTP/1.1 401 Unauthorized
< date: Mon, 26 Feb 2024 14:22:28 GMT
< server: uvicorn
< content-length: 23
< content-type: application/json
<
* Connection #0 to host localhost left intact
{"detail":"no api key"}
```

Using the API-KEY we are overcoming the unauthorized error and getting the expected response:

<!-- termynal -->

```shell
# This time we are passing the correct security scheme with the secret
$ curl -H "X-API-KEY: pygeoapi" http://localhost:5000/geoapi/collections/obs -vv

*   Trying [::1]:5000...
* connect to ::1 port 5000 failed: Connection refused
*   Trying 127.0.0.1:5000...
* Connected to localhost (127.0.0.1) port 5000
> GET /geoapi/collections/obs HTTP/1.1
> Host: localhost:5000
> User-Agent: curl/8.4.0
> Accept: */*
> X-API-KEY: pygeoapi
>
< HTTP/1.1 200 OK
< date: Mon, 26 Feb 2024 14:25:14 GMT
< server: uvicorn
< content-length: 3552
< content-type: application/json
< x-powered-by: pygeoapi 0.16.dev0
< content-language: en-US
<
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
            "href":"http://localhost:5000/geoapi?f=json"
        },
        {
            "type":"text/html",
            "rel":"root",
            "title":"The landing page of this server as HTML",
            "href":"http://localhost:5000/geoapi?f=html"
        },
        {
            "type":"application/json",
            "rel":"self",
            "title":"This document as JSON",
            "href":"http://localhost:5000/geoapi/collections/obs?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"alternate",
            "title":"This document as RDF (JSON-LD)",
            "href":"http://localhost:5000/geoapi/collections/obs?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"alternate",
            "title":"This document as HTML",
            "href":"http://localhost:5000/geoapi/collections/obs?f=html"
        },
        {
            "type":"application/schema+json",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as JSON",
            "href":"http://localhost:5000/geoapi/collections/obs/queryables?f=json"
        },
        {
            "type":"text/html",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as HTML",
            "href":"http://localhost:5000/geoapi/collections/obs/queryables?f=html"
        },
        {
            "type":"application/geo+json",
            "rel":"items",
            "title":"items as GeoJSON",
            "href":"http://localhost:5000/geoapi/collections/obs/items?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"items",
            "title":"items as RDF (GeoJSON-LD)",
            "href":"http://localhost:5000/geoapi/collections/obs/items?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"items",
            "title":"Items as HTML",
            "href":"http://localhost:5000/geoapi/collections/obs/items?f=html"
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
* Connection #0 to host localhost left intact
}
```

### OAuth2

In this case we are challenging the client to present valid JSON Web Tokens (JWTs) and getting to verify the token’s signature against the public key with the JSON Web Key Set (JWKS) endpoint of the authorization server.

Change the `.env` file with these settings:

```yml
DEV_API_KEY_ENABLED=false
DEV_OPA_ENABLED=false
DEV_JWKS_ENABLED=true
```

And configure a valid JWKS and Token endpoint for the authorization server:

!!! Tip "Use OAuth2 playground"
    There are some playgrounds available which can be used for the sake of testing the workflow. Let's use the one from [Auth0 by Okta](https://openidconnect.net/).

```yml
# oidc-jwks-only
DEV_JWKS_ENABLED=true
DEV_OAUTH2_JWKS_ENDPOINT=https://samples.auth0.com/.well-known/jwks.json
DEV_OAUTH2_TOKEN_ENDPOINT=https://samples.auth0.com/oauth/token
```

Use the OAuth2 server infrastructure to get the `access token` and then use that to consume the protected resource from the **fastgeoapi** server.

Let's get testing the collection again:

<!-- termynal -->

```shell
# This time we are passing the OAuth2 security scheme with the retrieved token
$ curl -H "Authorization: Bearer <access_token>" http://localhost:5000/geoapi/collections/obs -vv

*   Trying [::1]:5000...
* connect to ::1 port 5000 failed: Connection refused
*   Trying 127.0.0.1:5000...
* Connected to localhost (127.0.0.1) port 5000
> GET /geoapi/collections/obs HTTP/1.1
> Host: localhost:5000
> User-Agent: curl/8.4.0
> Accept: */*
> X-API-KEY: pygeoapi
>
< HTTP/1.1 200 OK
< date: Mon, 26 Feb 2024 14:25:14 GMT
< server: uvicorn
< content-length: 3552
< content-type: application/json
< x-powered-by: pygeoapi 0.16.dev0
< content-language: en-US
<
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
            "href":"http://localhost:5000/geoapi?f=json"
        },
        {
            "type":"text/html",
            "rel":"root",
            "title":"The landing page of this server as HTML",
            "href":"http://localhost:5000/geoapi?f=html"
        },
        {
            "type":"application/json",
            "rel":"self",
            "title":"This document as JSON",
            "href":"http://localhost:5000/geoapi/collections/obs?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"alternate",
            "title":"This document as RDF (JSON-LD)",
            "href":"http://localhost:5000/geoapi/collections/obs?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"alternate",
            "title":"This document as HTML",
            "href":"http://localhost:5000/geoapi/collections/obs?f=html"
        },
        {
            "type":"application/schema+json",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as JSON",
            "href":"http://localhost:5000/geoapi/collections/obs/queryables?f=json"
        },
        {
            "type":"text/html",
            "rel":"http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "title":"Queryables for this collection as HTML",
            "href":"http://localhost:5000/geoapi/collections/obs/queryables?f=html"
        },
        {
            "type":"application/geo+json",
            "rel":"items",
            "title":"items as GeoJSON",
            "href":"http://localhost:5000/geoapi/collections/obs/items?f=json"
        },
        {
            "type":"application/ld+json",
            "rel":"items",
            "title":"items as RDF (GeoJSON-LD)",
            "href":"http://localhost:5000/geoapi/collections/obs/items?f=jsonld"
        },
        {
            "type":"text/html",
            "rel":"items",
            "title":"Items as HTML",
            "href":"http://localhost:5000/geoapi/collections/obs/items?f=html"
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
* Connection #0 to host localhost left intact
}
```

### OpenID Connect

TBD

## Configure a coarse or fine-grained authorization

### Policies as code

TBD
