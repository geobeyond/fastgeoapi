# policy/auth.rego
package httpapi.authz

# HTTP API request
import input
default allow = true

# allow rules for different collections
# allow {
#     some collection
#     input.request_path[0] == "collections"
#     input.request_path[1] == collection
#     collection = "obs"
#     input.company == "osgeo"
# }

# allow {
#     some collection
#     input.request_path[0] == "collections"
#     input.request_path[1] == collection
#     collection = "lakes"
#     input.company == "geobeyond"
# }
