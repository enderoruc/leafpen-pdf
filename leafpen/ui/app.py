import sys
import traceback

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_ID, APP_NAME, ORG_NAME
from .. import i18n
from ..i18n import tr
from .main_window import MainWindow


def _excepthook(exc_type, exc, tb):
    """Show unexpected errors instead of silently killing the app."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.stderr.write(text)
    box = QMessageBox(QMessageBox.Icon.Critical, APP_NAME, tr("An unexpected error occurred."))
    box.setDetailedText(text)
    box.exec()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    # "system" follows the OS UI language (Turkish -> Turkish, anything else -> English).
    preference = str(QSettings(ORG_NAME, APP_ID).value("language", "system"))
    code = i18n.resolve(preference, QLocale.system().uiLanguages())
    i18n.set_language(code)
    qt_translator = QTranslator(app)  # standard buttons and dialogs
    if code != "en" and qt_translator.load(f"qtbase_{code}",
                                           QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt_translator)

    sys.excepthook = _excepthook
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.open_path(sys.argv[1])
    return app.exec()
