"""Motore di decompilazione APK (androguard, puro Python).

Produce nella cartella di output:
  REPORT.md                 riepilogo (package, versioni, permessi, componenti, librerie, URL…)
  AndroidManifest.xml       manifest decodificato
  sources/                  codice Java ricostruito (una classe per file)
  resources/                strings.xml dalla tabella risorse + XML binari decodificati (layout, ecc.)
  strings/                  stringhe dei dex (dell'app / tutte) e URL trovati
  raw/                      contenuto originale dell'APK (immagini, asset, librerie native, dex)
"""
from __future__ import annotations

import os
import re
import struct
import threading
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LIBRARY_PREFIXES = (
    "android.", "androidx.", "kotlin.", "kotlinx.", "java.", "javax.", "dalvik.", "org.intellij.",
    "org.jetbrains.", "com.google.", "com.android.", "okhttp3.", "okio.", "retrofit2.", "com.squareup.",
    "io.reactivex.", "org.json.", "org.apache.", "coil.", "coil3.", "io.ktor.", "dagger.", "javax.inject.",
    "com.facebook.", "com.bumptech.", "io.coil_kt.", "org.chromium.", "com.airbnb.", "_COROUTINE.",
    "org.slf4j.", "ch.qos.", "com.fasterxml.", "io.grpc.", "com.jakewharton.", "timber.", "org.koin.",
    "net.sqlcipher.", "org.bouncycastle.", "kotlinx.", "io.sentry.", "com.crashlytics.", "META-INF.",
)

KNOWN_LIBRARIES = {
    "androidx.compose": "Jetpack Compose", "androidx.room": "Room (database)",
    "androidx.lifecycle": "AndroidX Lifecycle / ViewModel", "androidx.navigation": "Navigation",
    "androidx.datastore": "DataStore", "androidx.work": "WorkManager", "androidx.media3": "Media3 / ExoPlayer",
    "com.google.android.exoplayer2": "ExoPlayer", "kotlinx.coroutines": "Kotlin Coroutines",
    "kotlinx.serialization": "Kotlinx Serialization", "okhttp3": "OkHttp", "retrofit2": "Retrofit",
    "com.squareup.moshi": "Moshi", "com.google.gson": "Gson", "coil": "Coil", "coil3": "Coil 3",
    "com.bumptech.glide": "Glide", "com.google.firebase": "Firebase", "com.google.android.gms": "Google Play Services",
    "io.ktor": "Ktor", "dagger": "Dagger / Hilt", "org.koin": "Koin", "io.reactivex": "RxJava",
    "com.facebook": "Facebook SDK", "io.sentry": "Sentry", "com.airbnb.lottie": "Lottie",
}

URL_RE = re.compile(r"https?://[^\s\"'<>\\]{4,}")
ProgressCb = Callable[[float, str], None]
LogCb = Callable[[str], None]


class Cancelled(Exception):
    pass


@dataclass
class Options:
    scope_all_code: bool = False     # False = solo codice dell'app
    extract_strings: bool = True
    decode_resources: bool = True
    copy_raw: bool = True


@dataclass
class Result:
    out_dir: Path
    package: str = ""
    app_name: str = ""
    classes_ok: int = 0
    classes_failed: int = 0
    seconds: float = 0.0
    report_path: Path | None = None
    errors: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ utilità
def _long(p: Path) -> str:
    """Percorso utilizzabile anche oltre i 260 caratteri su Windows."""
    s = str(p.resolve())
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        s = "\\\\?\\" + s
    return s


def _write(p: Path, data: bytes | str):
    os.makedirs(_long(p.parent), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    kw = {} if isinstance(data, bytes) else {"encoding": "utf-8", "newline": "\n"}
    with open(_long(p), mode, **kw) as fh:
        fh.write(data)


def _safe_part(s: str) -> str:
    s = re.sub(r'[<>:"|?*\x00-\x1f]', "_", s)
    return s[:150] or "_"


def class_to_dotted(desc: str) -> str:
    return desc[1:-1].replace("/", ".") if desc.startswith("L") and desc.endswith(";") else desc


def dex_strings(raw: bytes) -> list[str]:
    def uleb(b, o):
        r = s = 0
        while True:
            x = b[o]
            o += 1
            r |= (x & 0x7F) << s
            s += 7
            if x < 0x80:
                return r, o
    out = []
    try:
        n, off = struct.unpack_from("<II", raw, 0x38)
        for i in range(n):
            so = struct.unpack_from("<I", raw, off + 4 * i)[0]
            _, o = uleb(raw, so)
            e = raw.index(b"\0", o)
            out.append(raw[o:e].decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        pass
    return out


def is_noise_string(s: str) -> bool:
    """Scarta descrittori di tipo, firme di metodo, nomi di variabili e metadati Kotlin."""
    if not s.strip():
        return True
    if s[0] in "[(" or s.startswith("$") or s.startswith("L") and s.endswith(";"):
        return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*(\\[0-9]+)*", s):
        return True
    if re.fullmatch(r"[VZBSCIJFDL]+", s):
        return True
    return False


# ------------------------------------------------------------------ motore
class Decompiler:
    def __init__(self, apk_path: str, out_dir: str, options: Options,
                 progress: ProgressCb, log: LogCb, cancel: threading.Event):
        self.apk_path = Path(apk_path)
        self.out = Path(out_dir)
        self.opt = options
        self.progress = progress
        self.log = log
        self.cancel = cancel

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def run(self) -> Result:
        from loguru import logger
        logger.remove()   # androguard è molto verboso
        from androguard.core.apk import APK

        t0 = time.time()
        res = Result(self.out)
        self.out.mkdir(parents=True, exist_ok=True)

        self.progress(0.02, "Lettura dell'APK…")
        self.log(f"APK: {self.apk_path}")
        apk = APK(str(self.apk_path))
        res.package = apk.get_package() or ""
        res.app_name = self._safe(apk.get_app_name) or ""
        self.log(f"Package: {res.package}  •  Nome: {res.app_name}")
        self._check()

        # Manifest
        self.progress(0.05, "Decodifica del manifest…")
        try:
            xml = apk.get_android_manifest_axml().get_xml()
            _write(self.out / "AndroidManifest.xml", xml if isinstance(xml, bytes) else xml.encode())
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"Manifest: {e}")
            self.log(f"⚠ Manifest non decodificabile: {e}")

        # File grezzi
        if self.opt.copy_raw:
            self.progress(0.08, "Estrazione dei file originali…")
            self._extract_raw()
        self._check()

        # Risorse
        if self.opt.decode_resources:
            self.progress(0.12, "Decodifica delle risorse…")
            self._decode_resources(apk, res)
        self._check()

        # Codice
        app_prefixes = self._app_prefixes(apk)
        self.log("Package del codice dell'app: " + (", ".join(sorted(app_prefixes)) or "(non determinati)"))
        dex_names = sorted((n for n in apk.get_files() if re.fullmatch(r"classes\d*\.dex", n)),
                           key=lambda n: int(re.sub(r"\D", "", n) or 1))
        self.log(f"File dex: {len(dex_names)}")
        lib_counter: Counter = Counter()
        all_strings: set[str] = set()
        app_strings: set[str] = set()
        selected = []
        for i, name in enumerate(dex_names):
            self._check()
            raw = apk.get_file(name)
            strs = dex_strings(raw)
            for s in strs:
                if s.startswith("L") and s.endswith(";") and "/" in s:
                    dotted = class_to_dotted(s)
                    for k in KNOWN_LIBRARIES:
                        if dotted.startswith(k + "."):
                            lib_counter[KNOWN_LIBRARIES[k]] += 1
            has_app = any(("L" + p.replace(".", "/") + "/").encode() in raw for p in app_prefixes)
            if self.opt.scope_all_code or has_app:
                selected.append(name)
            if self.opt.extract_strings:
                all_strings.update(strs)
                if has_app:
                    app_strings.update(strs)
            self.progress(0.15 + 0.1 * (i + 1) / max(len(dex_names), 1), f"Lettura {name}…")

        self._decompile(apk, selected, app_prefixes, res)
        self._check()

        urls: set[str] = set()
        if self.opt.extract_strings:
            self.progress(0.95, "Salvataggio delle stringhe…")
            for s in all_strings:
                urls.update(m.group(0).rstrip(").,;") for m in URL_RE.finditer(s))
            app_clean = sorted(s for s in app_strings if not is_noise_string(s))
            _write(self.out / "strings" / "app_strings.txt", "\n".join(app_clean))
            _write(self.out / "strings" / "all_strings.txt", "\n".join(sorted(all_strings)))
            _write(self.out / "strings" / "urls.txt", "\n".join(sorted(urls)))
            self.log(f"Stringhe: {len(app_clean)} dell'app, {len(all_strings)} totali, {len(urls)} URL")

        res.seconds = time.time() - t0
        res.report_path = self._report(apk, res, app_prefixes, lib_counter, urls, dex_names, selected)
        self.progress(1.0, "Completato")
        self.log(f"✔ Completato in {res.seconds:.1f} s — {res.classes_ok} classi decompilate"
                 + (f", {res.classes_failed} con errori" if res.classes_failed else ""))
        return res

    # -------------------------------------------------------------- parti
    @staticmethod
    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default

    def _extract_raw(self):
        base = self.out / "raw"
        with zipfile.ZipFile(self.apk_path) as z:
            names = z.namelist()
            for i, n in enumerate(names):
                if i % 200 == 0:
                    self._check()
                parts = [p for p in n.replace("\\", "/").split("/") if p not in ("", ".", "..")]
                if not parts or n.endswith("/"):
                    continue
                try:
                    _write(base.joinpath(*[_safe_part(p) for p in parts]), z.read(n))
                except Exception as e:  # noqa: BLE001
                    self.log(f"⚠ {n}: {e}")
        self.log(f"File originali estratti: {len(names)}")

    def _decode_resources(self, apk, res: Result):
        from androguard.core.axml import AXMLPrinter
        base = self.out / "resources"
        try:
            arsc = apk.get_android_resources()
            if arsc is not None:
                for pkg in arsc.get_packages_names():
                    try:
                        xml = arsc.get_string_resources(pkg)
                        _write(base / _safe_part(pkg) / "values" / "strings.xml", xml)
                    except Exception as e:  # noqa: BLE001
                        self.log(f"⚠ strings.xml ({pkg}): {e}")
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"resources.arsc: {e}")
            self.log(f"⚠ resources.arsc: {e}")
        n = 0
        for name in apk.get_files():
            if not (name.startswith("res/") and name.endswith(".xml")):
                continue
            self._check()
            try:
                data = apk.get_file(name)
                if data[:4] == b"\x03\x00\x08\x00":       # XML binario Android
                    data = AXMLPrinter(data).get_xml()
                parts = [_safe_part(p) for p in name.split("/") if p not in ("", ".", "..")]
                _write(base.joinpath(*parts), data)
                n += 1
            except Exception as e:  # noqa: BLE001
                self.log(f"⚠ {name}: {e}")
        self.log(f"Risorse XML decodificate: {n}")

    def _app_prefixes(self, apk) -> set[str]:
        names = []
        for getter in (apk.get_activities, apk.get_services, apk.get_receivers, apk.get_providers):
            names += self._safe(getter, []) or []
        app_cls = self._safe(lambda: apk.get_attribute_value("application", "name"))
        if app_cls:
            names.append(app_cls)
        pkg = apk.get_package() or ""
        prefixes = set()
        for n in names:
            if n.startswith("."):
                n = pkg + n
            if n.startswith(LIBRARY_PREFIXES) or "." not in n:
                continue
            segs = n.split(".")[:-1]
            prefixes.add(".".join(segs[:2]) if len(segs) >= 2 else segs[0])
        if pkg and not pkg.startswith(LIBRARY_PREFIXES):
            segs = pkg.split(".")
            prefixes.add(".".join(segs[:3]) if len(segs) >= 3 else pkg)
        return prefixes

    def _decompile(self, apk, dex_names: list[str], app_prefixes: set[str], res: Result):
        from androguard.core.analysis.analysis import Analysis
        from androguard.core.dex import DEX
        from androguard.decompiler.decompile import DvClass

        if not dex_names:
            self.log("Nessun dex selezionato per la decompilazione.")
            return
        self.progress(0.27, "Analisi del bytecode…")
        dx = Analysis()
        dexes = []
        for name in dex_names:
            self._check()
            d = DEX(apk.get_file(name))
            dx.add(d)
            dexes.append(d)
        targets = []
        for d in dexes:
            for c in d.get_classes():
                dotted = class_to_dotted(c.get_name())
                if self.opt.scope_all_code or any(dotted.startswith(p + ".") for p in app_prefixes):
                    targets.append(c)
        total = len(targets)
        self.log(f"Classi da decompilare: {total}")
        src = self.out / "sources"
        failed_log = []
        for i, c in enumerate(targets):
            self._check()
            desc = c.get_name()
            parts = [_safe_part(p) for p in desc[1:-1].split("/")]
            path = src.joinpath(*parts[:-1], parts[-1] + ".java")
            try:
                dv = DvClass(c, dx)
                dv.process()
                _write(path, dv.get_source())
                res.classes_ok += 1
            except Exception as e:  # noqa: BLE001
                res.classes_failed += 1
                failed_log.append(f"{class_to_dotted(desc)}: {type(e).__name__}: {e}")
                _write(path, f"// Decompilazione non riuscita: {type(e).__name__}: {e}\n")
            if i % 5 == 0 or i == total - 1:
                self.progress(0.28 + 0.65 * (i + 1) / max(total, 1),
                              f"Decompilazione {i + 1}/{total}: {class_to_dotted(desc)}")
        if failed_log:
            _write(self.out / "decompile_errors.txt", "\n".join(failed_log))
            self.log(f"⚠ {len(failed_log)} classi con errori (vedi decompile_errors.txt)")

    def _report(self, apk, res: Result, prefixes, libs: Counter, urls, dex_names, selected) -> Path:
        g = self._safe
        perms = sorted(g(apk.get_permissions, []) or [])
        L = [f"# Report di decompilazione — {res.app_name or self.apk_path.name}", ""]
        L += ["| Voce | Valore |", "|---|---|",
              f"| File | `{self.apk_path.name}` ({self.apk_path.stat().st_size / 1048576:.1f} MB) |",
              f"| Nome app | {res.app_name} |",
              f"| Package | `{res.package}` |",
              f"| Versione | {g(apk.get_androidversion_name)} (code {g(apk.get_androidversion_code)}) |",
              f"| minSdk / targetSdk | {g(apk.get_min_sdk_version)} / {g(apk.get_target_sdk_version)} |",
              f"| Activity principale | `{g(apk.get_main_activity)}` |",
              f"| Package del codice dell'app | {', '.join(f'`{p}`' for p in sorted(prefixes)) or '-'} |",
              f"| File dex | {len(dex_names)} (decompilati: {', '.join(selected) or '-'}) |",
              f"| Classi decompilate | {res.classes_ok} (errori: {res.classes_failed}) |",
              f"| Tempo | {res.seconds:.1f} s |", ""]
        sig = g(lambda: [c.sha256_fingerprint.replace(" ", ":") for c in apk.get_certificates()], []) or []
        if sig:
            L += [f"**Firma (SHA-256):** `{sig[0]}`", ""]
        L += ["## Permessi", ""] + [f"- `{p}`" for p in perms] + [""]
        for title, getter in (("Activity", apk.get_activities), ("Service", apk.get_services),
                              ("Receiver", apk.get_receivers), ("Provider", apk.get_providers)):
            items = g(getter, []) or []
            if items:
                L += [f"## {title}", ""] + [f"- `{x}`" for x in items] + [""]
        if libs:
            L += ["## Librerie rilevate", ""] + [f"- {k}" for k, _ in libs.most_common()] + [""]
        native = sorted({n.split("/")[-1] for n in apk.get_files() if n.startswith("lib/") and n.endswith(".so")})
        if native:
            L += ["## Librerie native", ""] + [f"- `{n}`" for n in native] + [""]
        if urls:
            shown = sorted(urls)[:80]
            L += ["## URL trovati", ""] + [f"- {u}" for u in shown]
            if len(urls) > 80:
                L.append(f"- … altri {len(urls) - 80} in `strings/urls.txt`")
            L.append("")
        L += ["## Contenuto della cartella", "",
              "- `AndroidManifest.xml` — manifest decodificato",
              "- `sources/` — codice Java ricostruito (Kotlin compilato appare come Java)",
              "- `resources/` — `strings.xml` e XML di layout/risorse decodificati",
              "- `strings/app_strings.txt` — testi, URL, regex e messaggi del codice dell'app",
              "- `strings/all_strings.txt` — tutte le stringhe di tutti i dex",
              "- `raw/` — file originali (immagini, asset, librerie native, dex)", ""]
        if res.errors:
            L += ["## Avvisi", ""] + [f"- {e}" for e in res.errors] + [""]
        p = self.out / "REPORT.md"
        _write(p, "\n".join(str(x) for x in L))
        return p
