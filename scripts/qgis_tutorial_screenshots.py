r"""Render the screenshots of the "Using fastgeoapi from QGIS" tutorial with QGIS itself.

This is an offline tool for the documentation, not part of the package.
It runs under the Python **inside the QGIS bundle**, headless, and grabs
QGIS's own widgets: the OAuth2 form filled as the tutorial says, the new
connection dialog, the authentication editor, and a map of Rome rendered
from the demo's vector tiles and features through the OAuth2
configuration. Screenshots taken by hand drift; these are regenerated
from the same values the tutorial quotes.

Run on macOS with the QGIS 4.x bundle (adjust ``APP``):

    APP=/Applications/QGIS-final-4_2_2.app
    PY=$APP/Contents/Resources/python3.12
    FASTGEOAPI_DEMO_CLIENT_ID=... FASTGEOAPI_DEMO_CLIENT_SECRET=... \
    QGIS_PREFIX_PATH=$APP QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 \
    PYTHONPATH=$PY:$PY/lib-dynload:$PY/site-packages \
    $APP/Contents/MacOS/python3.12 scripts/qgis_tutorial_screenshots.py

The two environment variables are only needed for the map, which really
talks to the demo; the forms are filled with placeholders and never show
the credential. The bundle's standard library is flat under
``Resources/python3.12``, which is why it goes on ``PYTHONPATH`` rather
than ``PYTHONHOME``. ``QGIS_PREFIX_PATH`` must be the ``.app`` root: with
``Contents/MacOS`` the provider plugins are not found and the OAPIF
layer is silently invalid.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ty: the qgis modules live in the QGIS bundle, not in the project's environment.
from qgis.core import (  # ty: ignore[unresolved-import]
    Qgis,
    QgsApplication,
    QgsAuthMethodConfig,
    QgsCoordinateReferenceSystem,
    QgsLineSymbol,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsProject,
    QgsRectangle,
    QgsRuleBasedRenderer,
    QgsVectorLayer,
    QgsVectorTileBasicRenderer,
    QgsVectorTileBasicRendererStyle,
    QgsVectorTileLayer,
)
from qgis.gui import QgsAuthConfigEditor, QgsNewHttpConnection  # ty: ignore[unresolved-import]
from qgis.PyQt.QtCore import QSize  # ty: ignore[unresolved-import]
from qgis.PyQt.QtGui import QColor, QImage  # ty: ignore[unresolved-import]
from qgis.PyQt.QtWidgets import (  # ty: ignore[unresolved-import]
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
)

DEMO = "https://fastgeoapi.fly.dev/geoapi"
RESOURCE = f"{DEMO}/"
OIDC_ENDPOINT = "https://76hxgq.logto.app/oidc/token"
SCOPE = "openid profile ci"
OUT = Path(__file__).resolve().parent.parent / "docs" / "images" / "qgis"


def oauth2_config(client_id: str, client_secret: str) -> dict:
    """The configuration the tutorial quotes, in the OAuth2 method's own JSON."""
    return {
        "version": 1,
        "configType": 1,
        "grantFlow": 4,
        "accessMethod": 0,
        "name": "fastgeoapi demo",
        "tokenUrl": OIDC_ENDPOINT,
        "clientId": client_id,
        "clientSecret": client_secret,
        "scope": SCOPE,
        "queryPairs": {"resource": RESOURCE},
        "persistToken": True,
        "requestTimeout": 30,
    }


def store(am, config: dict) -> str:
    """Save the configuration in QGIS's authentication store and return its id."""
    cfg = QgsAuthMethodConfig("OAuth2")
    cfg.setName(config["name"])
    cfg.setConfig("oauth2config", json.dumps(config))
    ok, _ = am.storeAuthenticationConfig(cfg)
    if not ok:
        sys.exit("could not store the authentication configuration")
    return cfg.id()


def grab(widget, name: str, size: tuple[int, int]) -> None:
    """Show the widget at the given size and save what it paints as a PNG."""
    # Resize after show: a dialog resized before it is shown snaps back to
    # its size hint and comes out squeezed, with scrollbars.
    widget.show()
    QApplication.processEvents()
    widget.resize(*size)
    QApplication.processEvents()
    time.sleep(0.5)
    QApplication.processEvents()
    pixmap = widget.grab()
    target = OUT / f"{name}.png"
    pixmap.save(str(target), "PNG")
    print(f"{target.relative_to(OUT.parent.parent)}: {pixmap.width()}x{pixmap.height()}")


def shot_oauth2_form(am) -> None:
    """Step 1: the OAuth2 form, grant Client Credentials, placeholders for the credential."""
    form = am.authMethodEditWidget("OAuth2", None)
    tabs = form.findChild(QTabWidget, "tabConfigs")
    for i in range(tabs.count()):
        if "configure" in tabs.tabText(i).lower() or "custom" in tabs.tabText(i).lower():
            tabs.setCurrentIndex(i)
    form.findChild(QComboBox, "cmbbxGrantFlow").setCurrentIndex(4)
    form.findChild(QLineEdit, "leTokenUrl").setText(OIDC_ENDPOINT)
    form.findChild(QLineEdit, "leClientId").setText("<client id>")
    form.findChild(QLineEdit, "leClientSecret").setText("<client secret>")
    form.findChild(QLineEdit, "leScope").setText(SCOPE)
    table = form.findChild(QTableWidget, "tblwdgQueryPairs")
    table.setRowCount(1)
    table.setItem(0, 0, QTableWidgetItem("resource"))
    table.setItem(0, 1, QTableWidgetItem(RESOURCE))
    table.resizeColumnsToContents()
    # The query pairs live in a collapsed group at the bottom of the form.
    # Python sees it as a plain QGroupBox (the widget comes from a plugin),
    # so the collapsed state is reached through the Qt property.
    for group in form.findChildren(QGroupBox):
        if "parameter" in group.title().lower():
            group.setProperty("collapsed", False)
    form.findChild(QCheckBox, "chkbxTokenPersist").setChecked(True)
    grab(form, "01-oauth2-configuration", (780, 1180))


def shot_new_connection(authcfg: str) -> None:
    """Step 2: the new OGC API - Features connection, pointing at the landing page."""
    dialog = QgsNewHttpConnection(
        None, QgsNewHttpConnection.ConnectionType.ConnectionWfs, "qgis/connections-wfs/", ""
    )
    dialog.findChild(QLineEdit, "txtName").setText("fastgeoapi demo")
    dialog.findChild(QLineEdit, "txtUrl").setText(DEMO)
    versions = dialog.findChild(QComboBox, "cmbVersion")
    versions.setCurrentIndex(versions.findText("OGC API - Features"))
    configs = dialog.findChild(QComboBox, "cmbConfigSelect")
    for i in range(configs.count()):
        if configs.itemText(i).startswith("fastgeoapi demo"):
            configs.setCurrentIndex(i)
    grab(dialog, "02-new-connection", (760, 820))


def shot_config_editor() -> None:
    """The Options > Authentication list once the configuration exists."""
    grab(QgsAuthConfigEditor(None, True, True), "00-authentication-list", (900, 300))


def shot_map(authcfg: str) -> None:
    """The result: grey vector tiles under the main roads from the features layer."""
    tiles = QgsVectorTileLayer(
        f"type=xyz&url={DEMO}/collections/lazio-roads-tiles/tiles/WebMercatorQuad/"
        f"{{z}}/{{y}}/{{x}}?f%3Dpbf&zmin=0&zmax=13&authcfg={authcfg}",
        "Lazio roads (tiles)",
    )
    style = QgsVectorTileBasicRendererStyle("roads", "roads", Qgis.GeometryType.Line)
    style.setSymbol(QgsLineSymbol.createSimple({"color": "#9a9a9a", "width": "0.3"}))
    style.setEnabled(True)
    renderer = QgsVectorTileBasicRenderer()
    renderer.setStyles([style])
    tiles.setRenderer(renderer)
    features = QgsVectorLayer(
        f"url='{DEMO}' typename='lazio-roads' authcfg='{authcfg}' restrictToRequestBBOX='1'",
        "lazio-roads",
        "OAPIF",
    )
    # Do not call featureCount() on this layer: it would page through the
    # whole collection. The main roads are picked by a renderer rule, on
    # the client: QGIS pushes a layer filter to the server only when the
    # conformance declares the Part 3 `filter` classes, which pygeoapi
    # does not (see the tutorial), so a subset string would fetch nothing.
    main_roads = QgsRuleBasedRenderer.Rule(None)
    rule = QgsRuleBasedRenderer.Rule(
        QgsLineSymbol.createSimple({"color": "#e4572e", "width": "1.1"}),
        filterExp="\"class\" IN ('motorway','trunk','primary','secondary')",
        label="main roads",
    )
    main_roads.appendChild(rule)
    features.setRenderer(QgsRuleBasedRenderer(main_roads))
    if not (tiles.isValid() and features.isValid()):
        sys.exit(f"layers invalid: tiles={tiles.isValid()} features={features.isValid()}")
    QgsProject.instance().addMapLayers([tiles, features])
    settings = QgsMapSettings()
    settings.setLayers([features, tiles])
    settings.setBackgroundColor(QColor(255, 255, 255))
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    settings.setOutputSize(QSize(1280, 800))
    settings.setOutputDpi(110)
    # Rome, from the Vatican to Termini: small enough for the features
    # layer to page through in about a minute, dense enough to read.
    settings.setExtent(QgsRectangle(1389400, 5142600, 1395800, 5146600))
    job = QgsMapRendererParallelJob(settings)
    started = time.perf_counter()
    job.start()
    job.waitForFinished()
    if job.errors():
        sys.exit(f"render errors: {[e.message for e in job.errors()]}")
    target = OUT / "03-map-rome.png"
    # An indexed palette keeps two-colour line work under the repository's
    # 500 KB limit for added files (1.2 MB as ARGB, ~230 KB indexed).
    job.renderedImage().convertToFormat(QImage.Format.Format_Indexed8).save(str(target), "PNG", 0)
    print(
        f"{target.relative_to(OUT.parent.parent)}: rendered in {time.perf_counter() - started:.1f}s"
    )


def main() -> None:
    """Boot QGIS headless, store the configuration, and write the four images."""
    OUT.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    am = app.authManager()
    if not am.setMasterPassword("screenshots", True):
        sys.exit("the authentication store could not be opened")
    # The forms show placeholders; the map needs the real demo client.
    client_id = os.environ.get("FASTGEOAPI_DEMO_CLIENT_ID")
    client_secret = os.environ.get("FASTGEOAPI_DEMO_CLIENT_SECRET")
    authcfg = store(
        am, oauth2_config(client_id or "<client id>", client_secret or "<client secret>")
    )
    shot_config_editor()
    shot_oauth2_form(am)
    shot_new_connection(authcfg)
    if client_id and client_secret:
        shot_map(authcfg)
    else:
        print("FASTGEOAPI_DEMO_CLIENT_ID/SECRET not set: the map is skipped")
    app.exitQgis()


if __name__ == "__main__":
    main()
