# Keenetic TG Bot (Entware)

A Telegram bot running **on the router** (Entware `/opt`) to manage: Router / HydraRoute / NFQWS2(+web) / AWG Manager / opkg + notifications.

## Install (one-liner)
Interactive (RU/EN language selection at start):
```sh
opkg update && opkg install ca-certificates curl && \
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh
```

Non-interactive:
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | \
sh -s -- --yes --bot --token 123456:ABCDEF --admin 599497434
```

Verbose output:
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --debug
```

## Get a bot token
1) Telegram → **@BotFather**
2) Run `/newbot`
3) Copy token like `123456:ABCDEF...`

## Find your Telegram user id
Easiest: Telegram → **@userinfobot** → `Id: ...`

## Where files are stored
- Bot code + config: `/etc/keenetic-tg-bot/` (on Keenetic `/etc` is often read-only, installer will automatically use `/opt/etc/keenetic-tg-bot/`)
- init script: `/opt/etc/init.d/S99keenetic-tg-bot`
- bot log: `/opt/var/log/keenetic-tg-bot.log`
- install log: `/opt/var/log/keenetic-tg-bot-install.log`

<details>
<summary>Installer options</summary>

- `--lang ru|en`
- `--debug` / `-debug` — verbose output
- `--yes` — non-interactive mode
- `--bot` — install/update bot
- `--token <BOT_TOKEN>` — BotFather token
- `--admin <USER_ID>` — Telegram user id number
- `--reconfig` — rewrite config.json (prompts token/id)
- `--hydra` — HydraRoute Neo
- `--nfqws2` — NFQWS2
- `--nfqwsweb` — NFQWS web UI (also installs NFQWS2)
- `--awg` — AWG Manager
- `--cron` — cron
- `--weekly` — weekly auto-update every Thu 06:00

</details>

## Service control
```sh
/opt/etc/init.d/S99keenetic-tg-bot status
/opt/etc/init.d/S99keenetic-tg-bot restart
tail -n 200 /opt/var/log/keenetic-tg-bot.log
```

## Security
Do not leak your bot token. If leaked, revoke it in BotFather (`/revoke`) and re-run installer with `--bot --reconfig`.


## Debug & troubleshooting
- Enable verbose command logging:
  - `/debug_on`
  - `/debug_off`
- Logs: `/opt/var/log/keenetic-tg-bot.log`

In Debug mode the bot logs each command, return code and execution time.



## Router menus
Sub-menus added:
- **Network**: `ip addr (brief)`, `ip route v4/v6` (grouped by dev; default route separated)
- **Firewall**: iptables summary/raw (mangle/filter)
- **DHCP clients**: LAN / Wi‑Fi / All + per-client details (best-effort LAN/Wi‑Fi split)



## Notification anti-spam
Low disk space notifications for `/opt` are throttled (default: **once per 6 hours**), configurable in `config.json`:
- `notify.disk_interval_sec`



### Updating bot files
If the bot is already installed and you want to refresh bot.py/init:

```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --update-bot --yes
```
