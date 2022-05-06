# How to use Keycloak and Open Policy Agent

## Run Keycloak and OPA together

```shell
docker-compose up -d
```

## Configure Keycloak

Open the administration interface at `http://localhost:8282/auth` and access with the credentials `admin/admin`.

### Create a new realm

- _Add realm_ with the name `pygeoapi` and click on the _Create_ button
![Add a realm](https://user-images.githubusercontent.com/31009679/167174126-71da0d0b-85ea-4336-9d60-6690c0d334f4.png)
- In the _Clients_ menu under _Configure_ click on the button _Create_ on the top-right corner to _Add Client_ with a **Client ID** called `pygeoapi-client` and then click _Save_.
![Screenshot 2022-05-06 at 16 15 13](https://user-images.githubusercontent.com/31009679/167174235-0877435f-0f67-4db9-947a-7d1d4b08a714.png)

- In the _settings_ page
  - Set _Access Type_ to `confidential`
  - Set _Root URL_ to `http://localhost:5000`
  - Set _Valid Redirect URIs_ to `http://localhost:5000/*`
  - Set _Admin URL_ to `http://localhost:5000`
  - Set _Web Origins_ to `http://localhost:5000/*`
  - Click the _Save_ button
![Screenshot 2022-05-06 at 16 16 17](https://user-images.githubusercontent.com/31009679/167174338-ea4680b1-d0e9-47fc-b4bc-21771526791c.png)

- Set _client_id_ and _client_secret_ in the application configuration

### Create new users

![Screenshot 2022-05-06 at 16 16 41](https://user-images.githubusercontent.com/31009679/167174787-fb3556cc-2a7b-4d79-b325-94716f01712e.png)

Add new users in the _Users_ menu

- Add _Username_ with value `francbartoli`
- Under _Credentials_
  - Set _Password_ to `francbartoli`
  - Set _Temporary_ to `off`
- Under _Attributes_

  - Set key/value
    - `user=francbartoli`
    - `company=geobeyond`

![Screenshot 2022-05-06 at 16 16 51](https://user-images.githubusercontent.com/31009679/167174913-f8cc061f-d57f-452a-aeb2-26292a32eade.png)
![Screenshot 2022-05-06 at 16 17 15](https://user-images.githubusercontent.com/31009679/167174930-36cd24bc-fa80-48f8-9ace-aadbc7ec19d4.png)


- Add _Username_ with value `tomkralidis`
- Under _Credentials_
  - Set _Password_ to `tomkralidis`
  - Set _Temporary_ to `off`
- Under _Attributes_
  - Set key/value
    - `user=tomkralidis`
    - `company=osgeo`

### Create the mapping

Under the tab _Mappers_ of the new realm set the following mapping:

- Name: user-mapping
- Name: company-mapping

![Screenshot 2022-05-06 at 17 36 55](https://user-images.githubusercontent.com/31009679/167175131-1616e798-3f73-4a55-bde4-fb245588d55e.png)


## Update the policy

If there are changes in the `auth.rego` then restart the OPA server

```shell
docker-compose stop opa
docker-compose up -d
```

### Company based authorization policy

Let's imagine our users have some attributes, for example the `company` where they are working. In this case we'd like to use it for authorization purposes. If certain rules are added to the policy file, such as:

- allow users from company `osgeo` to access only the collection `obs`

```rego
allow {
    some collection
    input.request_path[0] == "collections"
    input.request_path[1] == collection
    collection = "obs"
    input.company == "osgeo"
}
```

- allow users from company `geobeyond` to access only the collection `lakes`

```rego
allow {
    some collection
    input.request_path[0] == "collections"
    input.request_path[1] == collection
    collection = "lakes"
    input.company == "geobeyond"
}
```

## Get Access Token

```shell
export KC_RESPONSE=$(curl -X POST 'http://localhost:8282/auth/realms/pygeoapi/protocol/openid-connect/token' \
 -H "Content-Type: application/x-www-form-urlencoded" \
 -d "username=francbartoli" \
 -d 'password=pygeoapi' \
 -d 'grant_type=password' \
 -d 'client_id=pygeoapi-client' \
 -d 'client_secret=eCjOPQsddOd1KoImn7ONlof9TxUIbJX1' \
 -d 'response_type=code id_token token' | jq -r '.')
```

Obtain the different response objects:

```shell
KC_ACCESS_TOKEN=$(echo $KC_RESPONSE| jq -r .access_token)
KC_ID_TOKEN=$(echo $KC_RESPONSE| jq -r .id_token)
KC_REFRESH_TOKEN=$(echo $KC_RESPONSE| jq -r .refresh_token)
```

Verify that the user information is correct:

```shell
curl -X GET 'http://localhost:8282/auth/realms/pygeoapi/protocol/openid-connect/userinfo' -H "Content-Type: application/x-www-form-urlencoded" -H "Authorization: Bearer $KC_ACCESS_TOKEN" | jq .
```

you would get something like this:

```json
{
  "sub": "f18a75db-e2a7-4d43-88b0-7bd9330a5c4d",
  "email_verified": false,
  "company": "geobeyond",
  "preferred_username": "francbartoli",
  "user": "francbartoli"
}
```

## Get pygeoapi collections

Get all collections:

```shell
curl -X GET 'http://localhost:5000/api/collections' \
-H "Content-Type: application/x-www-form-urlencoded" \
-H "Authorization: Bearer $KC_ACCESS_TOKEN" | jq .
```

Get the `lakes` collection:

```shell
curl -X GET 'http://localhost:5000/api/collections/lakes' \
-H "Content-Type: application/x-www-form-urlencoded" \
-H "Authorization: Bearer $KC_ACCESS_TOKEN" | jq .
```

you would get the following content:

```json
{
  "id": "lakes",
  "title": "Large Lakes",
  "description": "lakes of the world, public domain",
  "keywords": [
    "lakes",
    "water bodies"
  ],
  "links": [
    {
      "type": "text/html",
      "rel": "canonical",
      "title": "information",
      "href": "http://www.naturalearthdata.com/",
      "hreflang": "en-US"
    },
    {
      "type": "application/json",
      "rel": "self",
      "title": "This document as JSON",
      "href": "http://localhost:5000/api/collections/lakes?f=json"
    },
    {
      "type": "application/ld+json",
      "rel": "alternate",
      "title": "This document as RDF (JSON-LD)",
      "href": "http://localhost:5000/api/collections/lakes?f=jsonld"
    },
    {
      "type": "text/html",
      "rel": "alternate",
      "title": "This document as HTML",
      "href": "http://localhost:5000/api/collections/lakes?f=html"
    },
    {
      "type": "application/json",
      "rel": "queryables",
      "title": "Queryables for this collection as JSON",
      "href": "http://localhost:5000/api/collections/lakes/queryables?f=json"
    },
    {
      "type": "text/html",
      "rel": "queryables",
      "title": "Queryables for this collection as HTML",
      "href": "http://localhost:5000/api/collections/lakes/queryables?f=html"
    },
    {
      "type": "application/geo+json",
      "rel": "items",
      "title": "items as GeoJSON",
      "href": "http://localhost:5000/api/collections/lakes/items?f=json"
    },
    {
      "type": "application/ld+json",
      "rel": "items",
      "title": "items as RDF (GeoJSON-LD)",
      "href": "http://localhost:5000/api/collections/lakes/items?f=jsonld"
    },
    {
      "type": "text/html",
      "rel": "items",
      "title": "Items as HTML",
      "href": "http://localhost:5000/api/collections/lakes/items?f=html"
    }
  ],
  "extent": {
    "spatial": {
      "bbox": [
        [
          -180,
          -90,
          180,
          90
        ]
      ],
      "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    },
    "temporal": {
      "interval": [
        [
          "2011-11-11T11:11:11+00:00",
          null
        ]
      ]
    }
  },
  "itemType": "feature"
}
```

while getting the `obs` collection:

```shell
curl -X GET 'http://localhost:5000/api/collections/obs' \
-H "Content-Type: application/x-www-form-urlencoded" \
-H "Authorization: Bearer $KC_ACCESS_TOKEN" | jq .
```

the result is a deny since the user works for the company `geobeyond` and the collection `obs` is only accessible to the `osgeo` company:

```json
{
  "message": "Unauthorized"
}
```
