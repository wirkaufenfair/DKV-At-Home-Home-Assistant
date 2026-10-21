# DKV@Home Bridge (ohne Home Assistant)

Kleiner HTTP-Dienst, der die Freischaltung der Wallbox über DKV@Home
(Session starten/stoppen) lokal bereitstellt, zum Beispiel für **evcc**.
Er nutzt denselben API-Client wie die HA-Integration
([api.py](../custom_components/dkv_at_home/api.py)), braucht aber kein Home
Assistant. Der Refresh-Token wird bei jedem Aufruf rotiert und in
`tokens.json` gespeichert.

## Wo läuft die Bridge?

Die Bridge ist ein eigener Dienst und läuft **nicht in evcc**. evcc ruft sie
nur per HTTP auf. Sie läuft auf einem beliebigen Rechner, der dauerhaft an
ist, das DKV-Backend im Internet und evcc im Netz erreicht:

| Variante | Wann sinnvoll | Adresse in evcc |
| --- | --- | --- |
| **A: im selben LXC/derselben VM wie evcc** | evcc läuft auf Debian/Ubuntu (z. B. LXC aus den Proxmox-Helper-Skripten). Am wenigsten Aufwand. | `http://localhost:8099` |
| **B: eigener LXC/VM mit Docker** | evcc soll unberührt bleiben, oder evcc läuft selbst in Docker. | `http://<IP-der-Bridge>:8099` |

In beiden Fällen läuft das Skript, das evcc bei einem Ereignis aufruft
(siehe unten), dort, wo evcc läuft. Dort muss `curl` installiert sein.

## Variante A: im evcc-LXC/-VM (Debian/Ubuntu)

Im Proxmox-Webinterface den evcc-Container (oder die VM) auswählen und die
**Konsole** öffnen. Dort als root:

```bash
# 1. Abhängigkeiten und Code
apt update
apt install -y python3 python3-requests git curl
git clone https://github.com/wirkaufenfair/DKV-At-Home-Home-Assistant \
  /opt/dkv-bridge-src

# 2. Einmalig bei DKV anmelden (Ablauf siehe "Anmeldung" unten)
DKV_DATA_DIR=/var/lib/dkv-bridge python3 /opt/dkv-bridge-src/bridge/dkv_bridge.py login
```

Danach als Dienst einrichten, damit die Bridge nach einem Neustart
automatisch läuft. Diesen Block komplett in die Konsole einfügen:

```bash
cat > /etc/systemd/system/dkv-bridge.service <<'EOF'
[Unit]
Description=DKV@Home Bridge
After=network-online.target
Wants=network-online.target

[Service]
Environment=DKV_DATA_DIR=/var/lib/dkv-bridge
Environment=DKV_BIND=127.0.0.1
# Environment=DKV_BRIDGE_TOKEN=geheim
ExecStart=/usr/bin/python3 /opt/dkv-bridge-src/bridge/dkv_bridge.py serve
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now dkv-bridge
sleep 3
curl http://localhost:8099/status
```

Erwartet wird JSON mit `"active": false` und `"error": null`. Bei einem
Fehler zeigt `journalctl -u dkv-bridge -n 30` den Grund.

`DKV_BIND=127.0.0.1` sorgt dafür, dass die Bridge nur von diesem Rechner
erreichbar ist. Das ist bei Variante A ausreichend und sicher.

Test der Freischaltung: Auto anstecken, Wallbox freigeben („Laden bei
Verbindung“ in evcc) und ausführen:

```bash
curl -X POST http://localhost:8099/start
```

Das kann bis zu 60 Sekunden dauern. Antwort `"ok": true` bedeutet, dass DKV
die Session bestätigt hat. Mit `curl -X POST http://localhost:8099/stop`
wird sie wieder beendet.

Update später:

```bash
git -C /opt/dkv-bridge-src pull
systemctl restart dkv-bridge
```

## Variante B: eigener Rechner mit Docker

Den Build-Kontext bildet das Repo-Root, die Dateien liegen in `bridge/`:

```bash
git clone https://github.com/wirkaufenfair/DKV-At-Home-Home-Assistant
cd DKV-At-Home-Home-Assistant/bridge
docker compose run --rm -it dkv-bridge python dkv_bridge.py login
docker compose up -d
curl http://localhost:8099/status
```

Die Tokens liegen in `bridge/data/tokens.json`. Da die Bridge hier im Netz
erreichbar ist, in `docker-compose.yml` unbedingt `DKV_BRIDGE_TOKEN`
setzen (die Zeile ist vorbereitet, nur auskommentieren).

## Anmeldung (`login`)

1. `login` zeigt eine Anmelde-URL. Diese im Browser öffnen und bei DKV
   anmelden.
2. Nach dem Login versucht der Browser, `com.dkv-mobility.app://oauth2redirect?code=…`
   zu öffnen, und zeigt eine Meldung oder bleibt leer. Diese URL aus dem
   Netzwerk-Tab der Browser-Entwicklertools (F12) kopieren.
3. Die URL im Terminal bei `Eingabe:` einfügen. Der reine `code` oder ein
   vorhandener Refresh-Token geht ebenfalls.

Das ist derselbe Ablauf wie im Einrichtungsdialog der HA-Integration.

> Ein Refresh-Token darf nur von **einer** Stelle genutzt werden. Die Bridge
> braucht deshalb einen eigenen Login. Wird der Token der HA-Integration
> übernommen, muss die Integration danach neu verbunden werden.

## API

| Aufruf | Antwort |
| --- | --- |
| `GET /status` | JSON: `active`, `activeSessionId`, `status`, `name`, `error`, `updated` |
| `GET /active` | `true` / `false` (Klartext) |
| `GET /health` | wie `/status`, aber HTTP 503 wenn die letzte Abfrage fehlschlug |
| `POST /start` | startet die Session, wartet bis zu 60 s auf die Bestätigung; 504 bei Timeout |
| `POST /stop` | stoppt die Session, wartet bis zu 60 s; 504 bei Timeout |

Der Status wird alle 30 Sekunden im Hintergrund abgefragt. `/start`
tut nichts, wenn bereits eine Session läuft.

Umgebungsvariablen: `DKV_DATA_DIR`, `DKV_BIND`, `DKV_PORT` (8099),
`DKV_POLL_SECONDS`, `DKV_LOG_LEVEL`, `DKV_BRIDGE_TOKEN`. Mit
`DKV_BRIDGE_TOKEN` verlangen die POST-Aufrufe `Authorization: Bearer <token>`.
Die Bridge hat sonst keine Authentifizierung, nur im lokalen Netz betreiben.

## evcc einrichten

**Ungetestet**, die Syntax bitte gegen die eigene evcc-Version prüfen.

Wie bei der HA-Integration gilt: Die Wallbox muss beim DKV-Start sofort
laden dürfen, in evcc also **„Laden bei Verbindung“** aktivieren.

### Freischaltung beim Anstecken (KEBA bleibt direkt in evcc)

evcc kann bei Ereignissen ein Skript aufrufen, das die Bridge anstößt. In der
`evcc.yaml`:

```yaml
messaging:
  events:
    connect:
      title: DKV
      msg: Fahrzeug verbunden
  services:
    - type: script
      cmdline: /usr/local/bin/dkv-start.sh
      timeout: 90s
```

Das Skript `/usr/local/bin/dkv-start.sh` (ausführbar machen mit
`chmod +x`). Bei Variante B `localhost` durch die IP der Bridge ersetzen,
den `Authorization`-Header nur setzen, wenn `DKV_BRIDGE_TOKEN` gesetzt ist:

```bash
#!/bin/sh
curl -fsS -X POST -H "Authorization: Bearer geheim" http://localhost:8099/start
```

Danach evcc neu starten. Test ohne Auto: das Skript von Hand ausführen und
`curl http://localhost:8099/status` prüfen. Der Start wird nur bestätigt,
wenn ein Auto angesteckt und die Wallbox freigegeben ist.

### Eigener Charger nur für Start/Stopp

Wenn evcc den Ladevorgang selbst über die DKV-Session schalten soll
(`enable`/`enabled`), eignet sich ein `custom`-Charger mit `http`-Plugins
auf `/active`, `/start` und `/stop`. Leistung und Fahrzeugstatus kommen dabei
nicht von DKV, deshalb passt das nur, wenn sie anders geliefert werden.
