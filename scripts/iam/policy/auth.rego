# policy/auth.rego
package httpapi.authz

# HTTP API request
import input
default allow = true

##############################################################
# Uncomment the following lines for protected collections only
##############################################################

# default allow = false

# # Allow anyone to root and static files
# allow {
#     input.request_path = [""]
#     input.request_method == "GET"
# }

# allow {
#     input.request_path[0] == "static"
#     input.request_path[1] == "img"
#     input.request_method == "GET"
# }

# allow {
#     input.request_path[0] == "static"
#     input.request_path[1] == "css"
#     input.request_method == "GET"
# }

# # allow anyone to the collections metadata
# allow {
#     input.request_path = ["collections"]
#     input.request_method == "GET"
# }

# # allow rules for different collections
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
