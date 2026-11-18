"""The instructions the MCP server gives a client when it connects.

A client hands them to the model before the first tool call. They
describe how the generated tools fit together and hold for any pygeoapi
configuration. They name the tools by the pattern FastMCP derives from
the OpenAPI operation ids, and they give the condition for any tool that
only some collections have.
"""

SERVER_INSTRUCTIONS = """\
This server exposes an OGC API built with pygeoapi. Each tool is one \
operation of the API, and its name says which: getCollections lists the \
collections; describe<Collection>Collection, get<Collection>Queryables \
and get<Collection>Schema describe one; get<Collection>Features and \
get<Collection>Feature read its items.

Start from getCollections, and read a collection's queryables before \
filtering its items. Keep responses small with limit, offset and bbox, \
and pass skipGeometry=true when you need only the attributes. A \
getCQL2<Collection>Features tool, which takes a CQL2 JSON filter, exists \
only for collections whose data source applies the filter.

Processes are listed by getProcesses and run with execute<Process>Job, \
which takes the process inputs in an object named inputs. When the \
server runs a process asynchronously, follow the job with getJob and \
getJobResults. A collection that serves maps has a get<Collection>Map \
tool, which returns a PNG of a bbox given in longitude and latitude, \
512 pixels a side unless you ask otherwise. On a tile collection, \
get<Collection>TileSets lists its tilesets and get<Collection>TileSet \
describes one; the tiles themselves are not tools.
"""

SKILLS_INSTRUCTIONS = """\
The server also offers skills that explain the OGC API operations: how \
to filter and page through features, run a process and follow its job, \
or ask for a map or tiles. They describe each operation by its HTTP path, \
and the tool for a path is the one named after its operation, as above. \
Read ogcapi-orientation first.
"""


def build_server_instructions(skills: bool) -> str:
    """Build the instructions the server gives a client when it connects.

    Parameters
    ----------
    skills
        Whether the server offers the OGC API skills.

    Returns
    -------
    str
        The instructions on the tools, followed by the ones on the skills
        when ``skills`` is true.
    """
    if not skills:
        return SERVER_INSTRUCTIONS
    return f"{SERVER_INSTRUCTIONS}\n{SKILLS_INSTRUCTIONS}"
