# How to use Keycloak and Open Policy Agent

## Run Keycloak and OPA together

```shell
docker-compose up -d
```

## Configure Keycloak

Open the administration interface at `http://localhost:8282/auth` and access with the credentials `admin/admin`.

### Create a new realm

- *Add realm* with the name `pygeoapi` and click on the *Create* button
- In the *Clients* menu under *Configure* click on the button *Create* on the top-right corner to *Add Client* with a **Client ID** called `pygeoapi-client` and then click *Save*.
- In the *settings* page
  - Set *Access Type* to `confidential`
  - Set *Root URL* to `http://localhost:5000`
  - Set *Valid Redirect URIs* to `http://localhost:5000/*`
  - Set *Admin URL* to `http://localhost:5000`
  - Set *Web Origins* to `http://localhost:5000/*`
  - Click the *Save* button
- Set *client_id* and *client_secret* in the application configuration

### Create new users

Add new users in the *Users* menu

- Add *Username* with value `francbartoli`
- Under *Credentials*
  - Set *Password* to `francbartoli`
  - Set *Temporary* to `off`
- Under *Attributes*
  - Set key/value
    - `user=francbartoli`
    - `company=geobeyond`

- Add *Username* with value `tomkralidis`
- Under *Credentials*
  - Set *Password* to `tomkralidis`
  - Set *Temporary* to `off`
- Under *Attributes*
  - Set key/value
    - `user=tomkralidis`
    - `company=osgeo`

### Create the mapping

Under the tab *Mappers* of the new realm set the following mapping:

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
