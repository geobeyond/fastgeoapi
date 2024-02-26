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

### API KEY

The configuration can be controlled with these two settings:

```yml
# api-keys
DEV_API_KEY_ENABLED=false
DEV_PYGEOAPI_KEY_GLOBAL=pygeoapi
```

Setting `DEV_API_KEY_ENABLE` to `true` is the way to enable a flat protection to the whole `pygeoapi` sub-application. The value sets in the `DEV_PYGEOAPI_KEY_GLOBAL` is the secret key that must be used in the Header `X-API-KEY` to consume the API.

### OAuth2

TBD

### OpenID Connect

TBD

## Configure a coarse or fine-grained authorization

### Policies as code

TBD
