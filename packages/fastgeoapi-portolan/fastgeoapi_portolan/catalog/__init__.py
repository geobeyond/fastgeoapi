"""The core of the reader: what a catalog holds, and the rules for walking it.

The core reads nothing by itself and imports only the standard library, so
another project can vendor it and plug in its own way of fetching documents.
"""
