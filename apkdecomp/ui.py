"""Interfaccia grafica di APK Decompiler (PySide6)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QDir, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFileSystemModel, QFrame,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QSplitter, QTabWidget,
                               QTreeView, QVBoxLayout, QWidget)

from .engine import Cancelled, Decompiler, Options

APP_NAME = "APK Decompiler"
VERSION = "1.0"

PRIMARY = "#3DDC84"        # verde Android
PRIMARY_DARK = "#2BB56A"
BG = "#0F1114"
SURFACE = "#1A1D22"
SURFACE_VAR = "#252932"
OUTLINE = "#363B46"
ON = "#EEF1F5"
MUTED = "#A0A7B4"
ERROR = "#FF6B6B"

STYLE = f"""
* {{ font-family: 'Segoe UI', sans-serif; font-size: 10pt; color: {ON}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {OUTLINE}; border-radius: 14px; }}
QFrame#drop {{ background: {SURFACE}; border: 2px dashed {OUTLINE}; border-radius: 18px; }}
QFrame#drop[hover="true"] {{ border-color: {PRIMARY}; background: #17251d; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 20pt; font-weight: 700; }}
QLabel#big {{ font-size: 13pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#ok {{ color: {PRIMARY}; font-weight: 600; }}
QLabel#error {{ color: {ERROR}; }}
QPushButton {{ background: {SURFACE_VAR}; border: 1px solid {OUTLINE}; border-radius: 10px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {PRIMARY}; }}
QPushButton:disabled {{ color: #666; border-color: #2a2e36; }}
QPushButton#primary {{ background: {PRIMARY}; color: #08140d; border: none; font-weight: 700; padding: 11px 22px; font-size: 11pt; }}
QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#primary:disabled {{ background: #2c4a39; color: #8aa; }}
QPushButton#danger {{ color: {ERROR}; }}
QPlainTextEdit, QTreeView {{ background: {SURFACE}; border: 1px solid {OUTLINE}; border-radius: 10px; padding: 4px; selection-background-color: #2c5a40; }}
QProgressBar {{ background: {SURFACE_VAR}; border: none; border-radius: 4px; height: 8px; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 2px solid {OUTLINE}; background: {SURFACE_VAR}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: #666; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {SURFACE_VAR}; padding: 8px 18px; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {PRIMARY}; color: #08140d; font-weight: 600; }}
QHeaderView::section {{ background: {SURFACE_VAR}; border: none; padding: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: {OUTLINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QSplitter::handle {{ background: {BG}; }}
"""

TEXT_EXT = {".java", ".xml", ".txt", ".md", ".json", ".properties", ".smali", ".kt", ".html",
            ".js", ".css", ".pro", ".cfg", ".version", ".mf", ".sf", ".yml", ".yaml"}


def human_size(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def btn(text, obj=None, cb=None):
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    b.setCursor(Qt.PointingHandCursor)
    if cb:
        b.clicked.connect(cb)
    return b


def lbl(text, obj=None, wrap=False):
    x = QLabel(text)
    if obj:
        x.setObjectName(obj)
    x.setWordWrap(wrap)
    return x


class Bridge(QObject):
    progress = Signal(float, str)
    log = Signal(str)
    done = Signal(object, str)


class DropZone(QFrame):
    """Area di rilascio: accetta un file .apk trascinato o scelto con il picker."""

    def __init__(self, on_file):
        super().__init__()
        self.on_file = on_file
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setMinimumHeight(170)
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        icon = lbl("📦")
        icon.setStyleSheet("font-size: 34pt;")
        icon.setAlignment(Qt.AlignCenter)
        v.addWidget(icon)
        t = lbl("Trascina qui un file .apk", "big")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        m = lbl("oppure", "muted")
        m.setAlignment(Qt.AlignCenter)
        v.addWidget(m)
        v.addWidget(btn("Scegli file APK…", cb=self.pick), 0, Qt.AlignCenter)

    def pick(self):
        f, _ = QFileDialog.getOpenFileName(self, "Scegli file APK", str(Path.home() / "Downloads"),
                                           "Pacchetti Android (*.apk);;Tutti i file (*)")
        if f:
            self.on_file(f)

    @staticmethod
    def _apk_from(e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                p = u.toLocalFile()
                if p.lower().endswith(".apk") and os.path.isfile(p):
                    return p
        return None

    def _hover(self, on):
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if self._apk_from(e):
            e.acceptProposedAction()
            self._hover(True)
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._hover(False)

    def dropEvent(self, e):
        self._hover(False)
        p = self._apk_from(e)
        if p:
            e.acceptProposedAction()
            self.on_file(p)


class ResultBrowser(QWidget):
    """Albero dei file prodotti + visualizzatore di codice."""

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        sp = QSplitter(Qt.Horizontal)
        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        for c in (1, 2, 3):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self._open)
        self.tree.doubleClicked.connect(self._open_external)
        sp.addWidget(self.tree)
        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        f = QFont("Cascadia Mono")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.viewer.setFont(f)
        self.viewer.setPlaceholderText("Seleziona un file a sinistra per vederne il contenuto.\n"
                                       "Doppio clic per aprirlo con il programma predefinito.")
        sp.addWidget(self.viewer)
        sp.setSizes([320, 700])
        v.addWidget(sp)

    def set_root(self, path: str):
        idx = self.model.setRootPath(path)
        self.tree.setRootIndex(idx)
        report = os.path.join(path, "REPORT.md")
        if os.path.exists(report):
            self._show(report)

    def _show(self, path):
        p = Path(path)
        if p.is_dir():
            return
        if p.suffix.lower() in TEXT_EXT or p.stat().st_size < 200_000 and p.suffix == "":
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
                if len(txt) > 3_000_000:
                    txt = txt[:3_000_000] + "\n\n… (file troncato nella visualizzazione)"
                self.viewer.setPlainText(txt)
                return
            except OSError as e:
                self.viewer.setPlainText(f"Impossibile leggere il file: {e}")
                return
        self.viewer.setPlainText(f"{p.name}\n{human_size(p.stat().st_size)}\n\n"
                                 "File binario: doppio clic per aprirlo con il programma predefinito.")

    def _open(self, idx):
        self._show(self.model.filePath(idx))

    def _open_external(self, idx):
        p = self.model.filePath(idx)
        if os.path.isfile(p):
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1080, 820)
        self.setMinimumSize(820, 640)
        self.apk: str | None = None
        self.out_dir: str | None = None
        self.result_dir: str | None = None
        self.cancel = threading.Event()
        self.running = False
        self.bridge = Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.log.connect(self._on_log)
        self.bridge.done.connect(self._on_done)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)
        h = QVBoxLayout()
        h.setSpacing(2)
        h.addWidget(lbl(APP_NAME, "title"))
        h.addWidget(lbl("Decompila un file .apk: manifest, risorse, stringhe e codice Java ricostruito", "muted"))
        v.addLayout(h)

        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)

        # --- scheda Decompila
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 12, 0, 0)
        pv.setSpacing(12)
        self.drop = DropZone(self.set_apk)
        pv.addWidget(self.drop)

        self.file_card = QFrame()
        self.file_card.setObjectName("card")
        fc = QVBoxLayout(self.file_card)
        fc.setContentsMargins(16, 12, 16, 12)
        r = QHBoxLayout()
        self.file_lbl = lbl("", "big")
        r.addWidget(self.file_lbl, 1)
        r.addWidget(btn("Cambia", cb=self.drop.pick))
        fc.addLayout(r)
        self.file_info = lbl("", "muted", wrap=True)
        fc.addWidget(self.file_info)
        ro = QHBoxLayout()
        ro.addWidget(lbl("Cartella di output:"))
        self.out_lbl = lbl("", "muted", wrap=True)
        self.out_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ro.addWidget(self.out_lbl, 1)
        ro.addWidget(btn("Cambia cartella…", cb=self.pick_out))
        fc.addLayout(ro)
        opts = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(lbl("Codice da decompilare", "ok"))
        self.rb_app = QRadioButton("Solo il codice dell'app (consigliato, veloce)")
        self.rb_all = QRadioButton("Tutto, librerie incluse (molto più lento)")
        self.rb_app.setChecked(True)
        col1.addWidget(self.rb_app)
        col1.addWidget(self.rb_all)
        opts.addLayout(col1, 1)
        col2 = QVBoxLayout()
        col2.addWidget(lbl("Contenuti", "ok"))
        self.cb_strings = QCheckBox("Estrai stringhe e URL")
        self.cb_res = QCheckBox("Decodifica risorse e layout XML")
        self.cb_raw = QCheckBox("Copia i file originali (immagini, asset, .so)")
        for c in (self.cb_strings, self.cb_res, self.cb_raw):
            c.setChecked(True)
            col2.addWidget(c)
        opts.addLayout(col2, 1)
        fc.addLayout(opts)
        pv.addWidget(self.file_card)
        self.file_card.hide()

        ar = QHBoxLayout()
        self.go_btn = btn("Decompila", "primary", cb=self.start)
        self.go_btn.setEnabled(False)
        ar.addWidget(self.go_btn)
        self.cancel_btn = btn("Annulla", "danger", cb=self.do_cancel)
        self.cancel_btn.hide()
        ar.addWidget(self.cancel_btn)
        ar.addStretch()
        self.open_btn = btn("📁 Apri cartella", cb=lambda: self._open_path(self.result_dir))
        self.report_btn = btn("📄 Apri report", cb=lambda: self._open_path(
            os.path.join(self.result_dir or "", "REPORT.md")))
        self.browse_btn = btn("🔍 Esplora risultato", cb=lambda: self.tabs.setCurrentIndex(1))
        for b in (self.open_btn, self.report_btn, self.browse_btn):
            b.hide()
            ar.addWidget(b)
        pv.addLayout(ar)
        self.status = lbl("Nessun file selezionato.", "muted")
        pv.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        pv.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Il registro delle operazioni apparirà qui.")
        pv.addWidget(self.log, 1)
        self.tabs.addTab(page, "Decompila")

        self.browser = ResultBrowser()
        self.tabs.addTab(self.browser, "Risultato")
        self.tabs.setTabEnabled(1, False)

        foot = lbl(f"{APP_NAME} v{VERSION} • motore androguard • usa solo APK di cui hai i diritti", "muted")
        v.addWidget(foot)
        self.setAcceptDrops(True)

    # -- drag and drop anche sull'intera finestra
    def dragEnterEvent(self, e):
        if not self.running and DropZone._apk_from(e):
            e.acceptProposedAction()

    def dropEvent(self, e):
        p = DropZone._apk_from(e)
        if p and not self.running:
            self.set_apk(p)

    # -------------------------------------------------------------------
    def set_apk(self, path: str):
        if self.running:
            return
        if not zipfile_ok(path):
            QMessageBox.warning(self, APP_NAME, "Il file selezionato non è un APK valido.")
            return
        self.apk = path
        p = Path(path)
        self.out_dir = str(p.with_name(p.stem + "_decompilato"))
        self.file_lbl.setText(f"📦 {p.name}")
        self.file_info.setText(f"{human_size(p.stat().st_size)} • {p.parent}")
        self.out_lbl.setText(self.out_dir)
        self.file_card.show()
        self.drop.hide()
        self.go_btn.setEnabled(True)
        for b in (self.open_btn, self.report_btn, self.browse_btn):
            b.hide()
        self.bar.setValue(0)
        self.status.setText("Pronto: premi «Decompila».")

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella di output", str(Path(self.out_dir).parent))
        if d:
            self.out_dir = str(Path(d) / (Path(self.apk).stem + "_decompilato"))
            self.out_lbl.setText(self.out_dir)

    def start(self):
        if not self.apk:
            return
        out = Path(self.out_dir)
        if out.exists() and any(out.iterdir()):
            r = QMessageBox.question(self, APP_NAME, f"La cartella esiste già e non è vuota:\n{out}\n\n"
                                     "I file con lo stesso nome verranno sovrascritti. Continuare?")
            if r != QMessageBox.Yes:
                return
        opts = Options(scope_all_code=self.rb_all.isChecked(), extract_strings=self.cb_strings.isChecked(),
                       decode_resources=self.cb_res.isChecked(), copy_raw=self.cb_raw.isChecked())
        self.cancel = threading.Event()
        self.running = True
        self._set_busy(True)
        self.log.clear()
        b = self.bridge

        def job():
            try:
                res = Decompiler(self.apk, str(out), opts, b.progress.emit, b.log.emit, self.cancel).run()
                b.done.emit(res, "")
            except Cancelled:
                b.done.emit(None, "Operazione annullata.")
            except Exception as e:  # noqa: BLE001
                b.done.emit(None, f"{type(e).__name__}: {e}")

        threading.Thread(target=job, daemon=True).start()

    def do_cancel(self):
        self.cancel.set()
        self.status.setText("Annullamento in corso…")

    def _set_busy(self, busy):
        self.go_btn.setVisible(not busy)
        self.cancel_btn.setVisible(busy)
        for w in (self.rb_app, self.rb_all, self.cb_strings, self.cb_res, self.cb_raw):
            w.setEnabled(not busy)

    def _on_progress(self, p, text):
        self.bar.setValue(int(p * 1000))
        self.status.setText(text)

    def _on_log(self, line):
        self.log.appendPlainText(line)

    def _on_done(self, res, err):
        self.running = False
        self._set_busy(False)
        if res is None:
            self.status.setText(err)
            self.log.appendPlainText("✖ " + err)
            if err != "Operazione annullata.":
                QMessageBox.critical(self, APP_NAME, f"Decompilazione non riuscita:\n{err}")
            return
        self.result_dir = str(res.out_dir)
        self.status.setText(f"✔ Fatto: {res.classes_ok} classi decompilate in {res.seconds:.1f} s"
                            + (f" ({res.classes_failed} con errori)" if res.classes_failed else ""))
        for b in (self.open_btn, self.report_btn, self.browse_btn):
            b.show()
        self.tabs.setTabEnabled(1, True)
        self.browser.set_root(self.result_dir)

    @staticmethod
    def _open_path(p):
        if p and os.path.exists(p):
            if os.name == "nt" and os.path.isdir(p):
                subprocess.Popen(["explorer", os.path.normpath(p)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def closeEvent(self, e):
        if self.running:
            r = QMessageBox.question(self, APP_NAME, "Decompilazione in corso. Interrompere e chiudere?")
            if r != QMessageBox.Yes:
                e.ignore()
                return
            self.cancel.set()
        super().closeEvent(e)


def zipfile_ok(path: str) -> bool:
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            return any(n == "AndroidManifest.xml" for n in z.namelist())
    except Exception:  # noqa: BLE001
        return False


def run(argv=None):
    argv = argv if argv is not None else sys.argv
    # con pythonw.exe non esiste una console: evita errori se qualche libreria scrive su stdout
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("APKDecompiler.Desktop")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    icon = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    w = MainWindow()
    w.show()
    # file passato da riga di comando o trascinato sul .bat
    for a in argv[1:]:
        if a.lower().endswith(".apk") and os.path.isfile(a):
            w.set_apk(a)
            break
    return app.exec()
