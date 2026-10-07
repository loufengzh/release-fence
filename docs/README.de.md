# release-fence: Anleitung

Eine Qualitätsprüfung für ZIP-Veröffentlichungen: erforderliche Dateien,
unerwünschte Pfade, Größenlimits und ein deterministisches SHA-256-Inventar.
Python 3.10+ mit zlib genügt; zur Laufzeit wird nur die Standardbibliothek verwendet.
Das Werkzeug entpackt nichts auf die Festplatte, führt keine Archivinhalte aus und
benötigt keinen Netzwerkzugriff.

## Einstieg

```sh
python -m pip install .
python examples/make_demo.py
release-fence check examples/demo.zip --policy examples/policy.json
release-fence scan examples/demo.zip > before.json
release-fence diff before.json before.json
```

`required` enthält genaue relative Dateipfade, keine Muster. Groß-/Kleinschreibung
wird beachtet. `forbidden` nutzt Python `fnmatchcase`: `*` passt auch auf `/` und
führende Punkte; `**` hat keine besondere rekursive Bedeutung. `*.pyc` erfasst
Dateien in jeder Tiefe. Ein oberster Archivordner wird nicht automatisch entfernt.

Standardwerte: `max_files` = 1000, `max_total_bytes` = 67108864 und
`max_member_bytes` = 16777216. Die Größenprüfung zählt tatsächlich dekomprimierte
Bytes. Unbekannte Felder, doppelte JSON-Schlüssel und falsche Typen sind Fehler.
Es gibt keine eingebauten Sprachprofile; die Regeln werden ausdrücklich festgelegt.

Exitcodes: 0 für vollständigen Scan, bestandene Prüfung oder unverändertes Inventar;
1 für Pfadverstöße bei `check` oder Änderungen bei `diff`; 2 für ungültige Eingaben,
nicht unterstützte ZIP-Merkmale, Ressourcenlimits oder I/O-Fehler. `scan` meldet
Pfadverstöße im JSON, gibt aber 0 zurück. Bei einem Größenlimit wird abgebrochen;
ein unvollständiges Inventar wird niemals ausgegeben.

## Grenzen

Nur stored/deflated ZIP, kein TAR, ZIP64, verschlüsseltes oder mehrteiliges ZIP,
selbstentpackender Vorspann oder symbolischer Link. Feste Grenzen: 64 MiB Archiv,
8 MiB Zentralverzeichnis, 10000 Einträge. Absolute Pfade, Backslashes, `..`,
doppelte Pfade und Dateien als übergeordnete Verzeichnisse werden abgewiesen.
Unicode wird nicht normalisiert; Groß-/Kleinschreibung bleibt erhalten.

Zeitstempel, Rechte, Kompression und leere Verzeichnisse werden in Dateieinträgen
und Inhaltsvergleichen nicht berücksichtigt. Explizite Verzeichniseinträge können
jedoch die Liste der Verstöße gegen verbotene Pfade verändern. `diff` vergleicht nur Dateiinhalt und Größe, keine Regelverstöße.
Umbenennungen erscheinen als Löschen und Hinzufügen. Das Werkzeug ist kein
Malwarescanner, Geheimnisdetektor, Herkunftsnachweis oder vollständiger ZIP-Validator.
Für nicht vertrauenswürdige Eingaben zusätzliche Betriebssystemlimits und Isolation
verwenden. Details: [englische Hauptdokumentation](../README.md).

Tests: `PYTHONPATH=src python -m unittest discover -s tests -v`.

CI testet Python 3.10–3.13 unter Linux und Python 3.12 unter Windows und macOS. Jeder Job baut ein Wheel, installiert es ohne Netzwerkzugriff in einer sauberen temporären virtuellen Umgebung und führt sämtliche Tests außerhalb des Quellverzeichnisses aus. Der Test der installierten CLI prüft Unicode-Dateinamen im Archiv, Pfade mit Leerzeichen, die Groß-/Kleinschreibung bei Verbotsregeln sowie scan/check/diff-Ausgaben und Exitcodes 0/1/2. Die Tests verwenden nur lokal erzeugte synthetische Daten; die Vorbereitung der Bauwerkzeuge kann Netzwerkzugriff benötigen.

Nach dem Build: `python .github/scripts/check_install.py dist/release_fence-0.1.0-py3-none-any.whl`.

Fehler beim Schreiben oder Leeren des JSON-Ergebnispuffers von `scan`, `check` oder `diff` führen zu Exit-Code 2, auch bei vollem Ausgabegerät oder geschlossener Pipe. Bereits geschriebene Daten können nicht zurückgenommen werden; unvollständige Ausgabe nach jedem E/A-Fehler verwerfen. Leere ZIP-Dateien dürfen einen regulären Archivkommentar enthalten, aber keine unberücksichtigten Bytes vor dem Enddatensatz.
