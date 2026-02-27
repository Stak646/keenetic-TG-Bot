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



### Update an already installed bot (no module reinstall)
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --update-bot --yes
```
If you see **409 Conflict (getUpdates)**, multiple bot instances are running. Fix:
```sh
/opt/etc/init.d/S99keenetic-tg-bot stop
ps w | grep -F /opt/etc/keenetic-tg-bot/bot.py | grep -v grep
/opt/etc/init.d/S99keenetic-tg-bot start
```


### Debug
- `/debug_on` — enable verbose command + timing logs
- `/debug_off` — disable
Log: `/opt/var/log/keenetic-tg-bot.log`


### Network stability
Polling is now wrapped with exponential backoff to recover from transient disconnects (RemoteDisconnected/timeouts).
