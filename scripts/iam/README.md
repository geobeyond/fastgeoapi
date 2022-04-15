# How to use Keycloak and Open Policy Agent

## Run Keycloak and OPA together

```shell
docker-compose up -d
```

## Configure Keycloak

Open the administration interface at `http://localhost:8282/auth` and access with the credentials `admin/admin`.

### Create a new realm

- _Add realm_ with the name `pygeoapi` and click on the _Create_ button
- In the _Clients_ menu under _Configure_ click on the button _Create_ on the top-right corner to _Add Client_ with a **Client ID** called `pygeoapi-client` and then click _Save_.
- In the _settings_ page
  - Set _Access Type_ to `confidential`
  - Set _Root URL_ to `http://localhost:5000`
  - Set _Valid Redirect URIs_ to `http://localhost:5000/*`
  - Set _Admin URL_ to `http://localhost:5000`
  - Set _Web Origins_ to `http://localhost:5000/*`
  - Click the _Save_ button
- Set _client_id_ and _client_secret_ in the application configuration

### Create new users

Add new users in the _Users_ menu

- Add _Username_ with value `francbartoli`
- Under _Credentials_
  - Set _Password_ to `francbartoli`
  - Set _Temporary_ to `off`
- Under _Attributes_

  - Set key/value
    - `user=francbartoli`
    - `company=geobeyond`

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

- Name: user
- Name: company

## Update the policy

If there are changes in the `auth.rego` then restart the OPA server

```shell
docker-compose stop opa
docker-compose up -d
```

## Get Access Token

```shell
export KC_RESPONSE=$(curl -X POST 'http://localhost:8282/auth/realms/pygeoapi/protocol/openid-connect/token' \
 -H "Content-Type: application/x-www-form-urlencoded" \
 -d "username=francbartoli" \
 -d 'password=francbartoli' \
 -d 'grant_type=password' \
 -d 'client_id=pygeoapi-client' \
 -d 'client_secret=YPwVOZMlAwF5dFgs9QkPetqVGgyteoFO' | jq -r '.')
```

```shell
KC_ACCESS_TOKEN=$(echo $KC_RESPONSE| jq -r .access_token)
KC_ID_TOKEN=$(echo $KC_RESPONSE| jq -r .id_token)
KC_REFRESH_TOKEN=$(echo $KC_RESPONSE| jq -r .refresh_token)
```

```shell
curl -v -X POST 'http://localhost:8282/auth/realms/pygeoapi/protocol/openid-connect/userinfo' -H "Content-Type: application/x-www-form-urlencoded" -H "Authorization: Bearer $KC_ACCESS_TOKEN" | jq .
```
