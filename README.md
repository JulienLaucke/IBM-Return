# IBM@Return – eigenständige Version

Rechnerrücksendungen gemeinsam verwalten, mit eigener Anmeldung und genau zwei Konten. Ein ChatGPT-Konto ist zum Betrieb und zur Nutzung dieser Version nicht erforderlich.

## Lieferumfang und Stand

- Bestehende deutschsprachige Oberfläche mit DHL/FedEx, Mitarbeitername, Versanddatum, Eingangsdatum, Anlass, optionaler Geräte- und Sendungsnummer.
- Zwei E-Mail-/Passwort-Konten; keine offene Registrierung.
- Gemeinsame Liste, Bearbeiten, Eingang nachtragen und Löschen mit Bestätigung.
- Dauerhafte SQLite-Datenbank; Schutz vor dem Überschreiben zwischenzeitlicher Änderungen.
- Passwortwechsel und Abmelden; acht Stunden gültige serverseitige Sitzungen.
- Ersteinrichtung mit einem einmaligen Einrichtungsschlüssel.
- Startfähige, bereits gebaute Oberfläche in `dist/` und ein Node.js-Server ohne zusätzliche Laufzeitpakete.
- Dockerfile, lokale Docker-Compose-Konfiguration und Render-Konfiguration für die spätere Bereitstellung.

Diese Version wurde lokal gebaut und mit automatisierten HTTP-Tests geprüft. Sie wurde noch nicht bei einem externen Hostinganbieter bereitgestellt. Der vorhandene ChatGPT-Sites-Link zeigt weiterhin die bisherige Version mit ChatGPT-Anmeldung. Bestehende Daten aus dieser bisherigen Version sind nicht in diesem Paket enthalten. Eine Datenübernahme kann bei der tatsächlichen Umstellung erfolgen.

## Schnell lokal starten

Voraussetzung: Node.js 24.14 oder neuer, empfohlen Node.js 24 LTS. Für den Start der mitgelieferten Version ist kein `npm install` notwendig.

1. Das ZIP entpacken und im Ordner `ibm-return-standalone` ein Terminal öffnen.
2. Lokale Konfiguration erzeugen:

```sh
node server/local-setup.mjs
```

3. Die neu angelegte `.env` öffnen. Den Wert von `SETUP_TOKEN` für die Ersteinrichtung bereithalten. Die Datei enthält keine Benutzerpasswörter.
4. Server starten:

```sh
node --env-file=.env server/index.mjs
```

5. Im Browser `http://localhost:3000` öffnen. Den Einrichtungsschlüssel und die beiden unterschiedlichen E-Mail-Adressen mit Passwörtern (jeweils 12–128 Zeichen) eintragen.
6. Anmelden. Das zweite Konto kann sein Startpasswort anschließend über **Passwort** ändern.

Es werden keine E-Mails verschickt. Die E-Mail-Adresse dient als Anmeldename; sie wird nicht über einen E-Mail-Code verifiziert. Die Zuordnung der beiden Konten übernimmt die Person mit dem Einrichtungsschlüssel. Nach der Einrichtung kann über die öffentliche Oberfläche kein weiteres Konto angelegt werden.

Die lokale Konfiguration bindet nur an den eigenen Rechner. Für die gemeinsame Nutzung übers Internet die Produktionskonfiguration mit HTTPS verwenden.

## Externe Bereitstellung: Render

`render.yaml` enthält eine konkrete Konfiguration für einen Docker-Webdienst mit genau einer Instanz, Region Frankfurt und 1 GB dauerhaftem Speicher. Das Anlegen verursacht Hostingkosten; vor dem Erstellen den aktuellen Gesamtpreis im Render-Konto prüfen. Die Verbindung zum Konto und die Bestätigung des kostenpflichtigen Dienstes stehen noch aus.

1. Dieses Projekt in einem eigenen privaten Git-Repository bereitstellen. `dist/`, `server/`, `Dockerfile` und `render.yaml` müssen enthalten sein; `.env` und `data/` nicht hochladen.
2. In Render dieses Repository als Blueprint verbinden und die Kosten prüfen.
3. Render baut das Docker-Image aus der bereits mitgelieferten Oberfläche und startet den Server. Render setzt `RENDER_EXTERNAL_URL`; die App verwendet diese HTTPS-Adresse als zulässigen Ursprung.
4. In den Umgebungsvariablen des Dienstes den automatisch erzeugten `SETUP_TOKEN` anzeigen. Nur zur Ersteinrichtung verwenden.
5. Die neue HTTPS-Adresse öffnen und beide Konten einrichten.
6. Nach erfolgreicher Einrichtung kann `SETUP_TOKEN` aus den Hosting-Umgebungsvariablen entfernt werden. Die Konten liegen dann in der Datenbank; erneute öffentliche Einrichtung ist gesperrt.

Bei einer eigenen Domain `APP_ORIGIN` auf die tatsächlich verwendete HTTPS-Origin ohne abschließenden Schrägstrich setzen. Alle Benutzer sollen diese eine Adresse verwenden. Die App akzeptiert keine fremden Origins für Änderungen.

Der Speicher muss dauerhaft unter `/app/data` eingebunden und für den Containerbenutzer `node` (UID 1000) beschreibbar sein. Ein kostenloser Render-Dienst ohne dauerhaften Datenträger ist für diese SQLite-Version nicht vorgesehen. Bei einem Anbieterwechsel kann derselbe Docker-Container auf einem anderen Docker-fähigen Host mit persistentem Volume und HTTPS betrieben werden.

## Betrieb, Sicherung und Wiederherstellung

Die Datei `returns.sqlite` sowie die SQLite-Begleitdateien liegen unter `DATA_DIR`. Dieser Ordner wird niemals über HTTP ausgeliefert. Das Datenverzeichnis nicht löschen oder durch einen leeren Datenträger ersetzen: Ohne die Datenbank fehlen Konten und Rücksendungen.

Ein konsistentes Backup der laufenden Datenbank anlegen:

```sh
node --env-file=.env server/backup.mjs ./backups/returns.sqlite
```

Im Hosting-Terminal sind die Umgebungsvariablen bereits gesetzt; dort `--env-file=.env` weglassen. Einen neuen Backup-Dateinamen wählen, die Datei anschließend geschützt außerhalb des laufenden Dienstes aufbewahren. Backups enthalten personenbezogene Einträge und Passwort-Hashes.

Wiederherstellung: Dienst stoppen; bestehende Datenbank einschließlich `returns.sqlite-wal` und `returns.sqlite-shm` zusammen als Sicherung weglegen; das konsistente Backup als `returns.sqlite` in `DATA_DIR` kopieren und für UID 1000 beschreibbar machen; danach den Dienst neu starten. Eine Wiederherstellung ersetzt den Datenstand durch den Zeitpunkt des Backups.

Ein vergessenes Passwort kann die Person mit Zugang zum Hosting-Terminal zurücksetzen:

```sh
node server/reset-password.mjs
```

Das Werkzeug fragt E-Mail-Adresse und ein neues, verborgen eingegebenes Passwort ab. Es ändert nur ein vorhandenes Konto und widerruft dessen bisherige Sitzungen. Es erzeugt kein drittes Konto.

## Lokaler Docker-Test

Nach `node server/local-setup.mjs`:

```sh
docker compose up --build
```

Öffnen: `http://localhost:3000`. Docker Compose nutzt ein eigenes dauerhaftes Volume. Es ist nicht dieselbe Datenbank wie beim direkten lokalen Node-Start. Diese Compose-Datei ist ausschließlich für den lokalen Test konfiguriert; für den Internetbetrieb HTTPS und Produktionsmodus verwenden.

## Entwicklung

Frontend: React, TypeScript, Vite, Tailwind und die vorhandenen UI-Komponenten. Backend: Node.js HTTP, `node:sqlite`, `node:crypto`. Die übernommenen Build-Abhängigkeiten und ihr pnpm-Lockfile sind enthalten; der produktive Server benötigt keine npm-Pakete.

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm run build
corepack pnpm run typecheck
node --test tests/*.test.mjs
```

Nach UI-Änderungen immer `dist/` neu bauen und zusammen mit dem Quelltext bereitstellen. Der Dockerfile installiert keine Build-Werkzeuge, sondern verwendet genau diesen fertigen Build.

Für Vite-Entwicklung den Server zusätzlich auf Port 3000 starten. Die Entwicklungsoberfläche auf Port 5173 verwenden und `APP_ORIGIN=http://localhost:5173` setzen. Der Vite-Proxy leitet `/api` an den Backendserver weiter. Diese Konfiguration ist für lokale Entwicklung bestimmt.

## Verifikation

Die automatisierten Tests prüfen reale HTTP-Anfragen gegen eine temporäre Datenbank:

- Abweisen nicht angemeldeter Datenzugriffe und fremder Origins.
- Ersteinrichtung mit Schlüssel, genau zwei Konten, keine erneute Registrierung.
- Passwort-Hashes, Cookie-Eigenschaften und fehlgeschlagene Anmeldung.
- Gemeinsames Erstellen, Anzeigen, Bearbeiten und Löschen.
- Datumseingaben, wiederholte Speicherversuche und Konflikte bei gleichzeitiger Bearbeitung.
- Dauerhafte Einträge und Sitzungen nach einem Serverneustart.
- Passwortwechsel, Sitzungsablauf, Logout und Anmelde-Drosselung.
- Kein HTTP-Zugriff auf Serverdateien, Datenbank oder Konfiguration.

Der Build und die TypeScript-Prüfung waren erfolgreich. Ein Browser-End-to-End-Test und ein Test beim externen Hostinganbieter stehen noch aus. Die App enthält keine automatische DHL-/FedEx-Sendungsabfrage und keine IBM-Systemanbindung.

## Technische Referenzen

- [Node.js SQLite](https://nodejs.org/api/sqlite.html)
- [Node.js Crypto](https://nodejs.org/api/crypto.html)
- [Render: Docker](https://render.com/docs/docker)
- [Render: Persistente Datenträger](https://render.com/docs/disks)
- [Render: Blueprint-Konfiguration](https://render.com/docs/blueprint-spec)
- [Render: Preise](https://render.com/pricing)
