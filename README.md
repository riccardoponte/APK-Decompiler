# APK Decompiler

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

---

<a name="italiano"></a>
## 🇮🇹 Italiano

App desktop per Windows che decompila un file **.apk** Android: trascini il file nella finestra (o lo scegli con il pulsante) e ottieni una cartella con manifest, risorse, stringhe e **codice Java ricostruito**.

### Avvio — niente da installare

Doppio clic su **`APK Decompiler.bat`**. Puoi anche trascinare un `.apk` direttamente sul file `.bat`.
Python 3.14 e le librerie (PySide6, androguard) sono già in `runtime/`.
`APK Decompiler-debug.bat` avvia l'app con la console visibile.

### Uso

1. Trascina un `.apk` nell'area tratteggiata, oppure premi **Scegli file APK…**.
2. Controlla la cartella di output (predefinita: `<nome>_decompilato` accanto all'APK) e le opzioni:
   - **Solo il codice dell'app** (consigliato): decompila i package dell'app, ricavati dai componenti del manifest;
   - **Tutto**: include anche le librerie (androidx, kotlin, okhttp…), molto più lento;
   - stringhe e URL, risorse e layout XML, copia dei file originali.
3. Premi **Decompila**: avanzamento e registro in tempo reale, con possibilità di annullare.
4. Apri la cartella o il report, oppure usa la scheda **Risultato** per sfogliare i file e leggere il codice.

### Cosa produce

```
<nome>_decompilato/
  REPORT.md               package, versioni, SDK, firma, permessi, componenti, librerie, URL
  AndroidManifest.xml     manifest decodificato
  sources/                codice Java ricostruito, una classe per file
  resources/              strings.xml e XML di layout/risorse decodificati
  strings/                app_strings.txt, all_strings.txt, urls.txt
  raw/                    file originali (immagini, asset, librerie native, dex)
  decompile_errors.txt    classi non decompilabili (se presenti)
```

Esempio: `tube_converter.apk` (24 MB, 11 dex) → 299 classi in circa 10 secondi.

### Struttura del progetto

```
APK Decompiler.bat         avvio (senza console)
APK Decompiler-debug.bat   avvio con console
main.py                    punto di ingresso
apkdecomp/engine.py        motore: estrazione, manifest, risorse, stringhe, decompilazione (androguard)
apkdecomp/ui.py            interfaccia PySide6 con drag and drop e visualizzatore
runtime/                   Python 3.14 portatile + librerie
requirements.txt           librerie incluse
```

### Note

- Il codice Kotlin compilato viene ricostruito come Java: è leggibile ma non identico al sorgente originale.
- App offuscate (R8/ProGuard) avranno nomi di classi e metodi abbreviati.
- Usa l'app solo su APK di cui hai i diritti (app tue, open source o analisi autorizzate).

---

<a name="english"></a>
## 🇬🇧 English

Windows desktop app that decompiles an Android **.apk** file: drag the file onto the window (or pick it with the button) and get a folder with the manifest, resources, strings and **reconstructed Java code**.

### Start — nothing to install

Double-click **`APK Decompiler.bat`**. You can also drop an `.apk` straight onto the `.bat` file.
Python 3.14 and the libraries (PySide6, androguard) are already in `runtime/`.
`APK Decompiler-debug.bat` starts the app with a visible console.

### Usage

1. Drag an `.apk` onto the dashed area, or press **Scegli file APK…** (Choose APK file).
2. Check the output folder (default: `<name>_decompilato` next to the APK) and the options:
   - **App code only** (recommended): decompiles the app packages, detected from the manifest components;
   - **Everything**: libraries included (androidx, kotlin, okhttp…), much slower;
   - strings and URLs, resources and XML layouts, copy of the original files.
3. Press **Decompila** (Decompile): live progress and log, with cancel support.
4. Open the folder or the report, or use the **Risultato** (Result) tab to browse the files and read the code.

### Output

```
<name>_decompilato/
  REPORT.md               package, versions, SDK, signature, permissions, components, libraries, URLs
  AndroidManifest.xml     decoded manifest
  sources/                reconstructed Java code, one class per file
  resources/              strings.xml and decoded layout/resource XML
  strings/                app_strings.txt, all_strings.txt, urls.txt
  raw/                    original files (images, assets, native libraries, dex)
  decompile_errors.txt    classes that could not be decompiled (if any)
```

Example: `tube_converter.apk` (24 MB, 11 dex) → 299 classes in about 10 seconds.

### Project layout

```
APK Decompiler.bat         launcher (no console)
APK Decompiler-debug.bat   launcher with console
main.py                    entry point
apkdecomp/engine.py        engine: extraction, manifest, resources, strings, decompilation (androguard)
apkdecomp/ui.py            PySide6 interface with drag and drop and viewer
runtime/                   portable Python 3.14 + libraries
requirements.txt           bundled libraries
```

### Notes

- Compiled Kotlin is reconstructed as Java: readable, but not identical to the original source.
- Obfuscated apps (R8/ProGuard) will have shortened class and method names.
- Only use the app on APKs you have rights to (your own apps, open source, or authorized analysis).
