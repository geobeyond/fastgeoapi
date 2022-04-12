# policy/auth.rego
package httpapi.authz

# HTTP API request
import input
default allow = true
