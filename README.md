# Keenetic TG Bot (alfa)

Telegram bot for Keenetic routers (Entware). Modular UI, component manager, and router utilities.

> Branch **`alfa`** is the active development branch.

## What it does

- **Home menu** with consistent buttons and submenus.
- **Router**:
  - system info (RAM/CPU/uptime, `/opt` usage, opkg architectures)
  - IPv4/IPv6 routes (paged)
  - IP addresses (paged)
  - iptables/ip6tables rules (paged)
  - DHCP clients list + per‑client details *(LAN/Wi‑Fi split if `iw` is available)*
  - reboot with confirmation
- **OPKG**:
  - `opkg update`, `opkg upgrade` (runs as a background job with animation)
  - installed packages list (paged)
  - package search (by sending text after pressing “Search”)
- **Components manager**:
  - install / remove (and some service actions) for:
    - HydraRoute (hrneo/hrweb)
    - NFQWS2 (+ optional web UI package)
    - AWG Manager
  - uses **architecture-aware feeds** and blocks “wrong arch” installs by selecting the correct repo URL.
- **HydraRoute / NFQWS2 / AWG**: short overview + service actions.
- **Speed tests**:
  - quick HTTP download test to quality endpoints (Cloudflare / Hetzner)
  - AWG speed test (if AWG Manager API is available)
  - optional `speedtest-go` (if present / installable)

## Supported architectures

- `mips`
- `mipsel`
- `aarch64`

> Pure Python runtime. External components are installed via OPKG feeds selected by detected Entware architecture.

## Install (Entware)

### One-liner (alfa)

Interactive install (no parameters):

```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/alfa/autoinstall.sh | sh
```

Installer debug mode:

```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/alfa/autoinstall.sh | sh -s -- --debug
```

Non-interactive (for scripts):

```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/alfa/autoinstall.sh | sh -s -- --yes --lang ru --token "YOUR_BOT_TOKEN" --admin 123456789
```

Options:
- `--branch alfa|main`
- `--token ...`
- `--admin <telegram_user_id>` (can be used multiple times)
- `--lang ru|en`
- `--debug`
- `--no-start`

## Config

Path:
- `/opt/etc/keenetic-tg-bot/config/config.json`

Key fields:
- `bot_token`
- `admins` (recommended)
- `language` (`ru` / `en`)
- `performance.debug` (enables verbose logging)

## Service

```sh
/opt/etc/init.d/S99keenetic-tg-bot start
/opt/etc/init.d/S99keenetic-tg-bot stop
/opt/etc/init.d/S99keenetic-tg-bot restart
/opt/etc/init.d/S99keenetic-tg-bot status
```

## Logs

- `/opt/var/log/keenetic-tg-bot.log` (rotating, main log)
- `/opt/var/log/keenetic-tg-bot-console.log` (stdout/stderr from daemon)
- `/opt/var/log/keenetic-tg-bot-install.log` (installer log)

## Troubleshooting

- **409 Conflict: terminated by other getUpdates request**
  - You have 2 instances of the bot running (or another host is using the same token).
  - Stop one instance, or change the bot token.
- **Slow UI**
  - Set admins to reduce load from random chats.
  - Turn off debug to reduce logging overhead.
  - The bot auto-adjusts worker counts based on RAM.

## Project layout

Repository:
- `keenetic-tg-bot/` → runtime files copied to `/opt/etc/keenetic-tg-bot`
  - `Main.py`
  - `config/`
  - `modules/`
  - `scripts/`

## Roadmap / ideas (uncertain)

See README_RU.md for a more detailed list and notes.


## Adding new modules (developer notes)

1. Create a driver in `keenetic-tg-bot/modules/drivers/` (shell wrapper / HTTP client).
2. Create a UI component in `keenetic-tg-bot/modules/components/` inheriting `ComponentBase`.
3. Register it in `keenetic-tg-bot/Main.py`:

```py
from modules.components.my_component import MyComponent
app.components["mx"] = MyComponent(my_driver)
```

Callback format: `mx|command|k=v&k2=v2`
