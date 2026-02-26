# Keenetic TG Bot (Entware)

A Telegram bot running **on the router** (Entware `/opt`) to manage: Router / HydraRoute / NFQWS2(+web) / AWG Manager / opkg + notifications.

## Install (one‑liner)
Interactive (language selection RU/EN at start):
```sh
opkg update && opkg install ca-certificates curl && \
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh
```

Non‑interactive (no questions; you must pass token + user id):
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | \
sh -s -- --yes --bot --token 123456:ABCDEF --admin 599497434
```

Full install output:
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --debug
```

## Get a bot token (bot_token)
1) Telegram → **@BotFather**
2) Run `/newbot`
3) Copy the token like `123456:ABCDEF...`

## Find your Telegram user id
Easiest: Telegram → **@userinfobot** → `Id: ...`

## Paths after install
- Bot code + config: `/etc/keenetic-tg-bot/` (on Keenetic /etc is often read-only, so installer will use `/opt/etc/keenetic-tg-bot/` automatically)
- init script: `/opt/etc/init.d/S99keenetic-tg-bot`
- bot log: `/opt/var/log/keenetic-tg-bot.log`
- install log: `/opt/var/log/keenetic-tg-bot-install.log`

## Service control
```sh
/opt/etc/init.d/S99keenetic-tg-bot status
/opt/etc/init.d/S99keenetic-tg-bot restart
tail -n 200 /opt/var/log/keenetic-tg-bot.log
```

<details>
<summary>Installer options (click to expand)</summary>

- `--lang ru|en` — message language
- `--debug` or `-debug` — verbose output + command logs
- `--yes` — non‑interactive mode
- `--bot` — install/update the bot
- `--token <BOT_TOKEN>` — BotFather token
- `--admin <USER_ID>` — your Telegram user id (number)
- `--reconfig` — rewrite config.json (prompts token/id)
- `--hydra` — HydraRoute Neo
- `--nfqws2` — NFQWS2
- `--nfqwsweb` — NFQWS web UI (auto‑enables `--nfqws2`)
- `--awg` — AWG Manager
- `--cron` — cron
- `--weekly` — weekly auto‑update every **Thu 06:00**

</details>

## Security
- Do not leak your bot token (if leaked, revoke it in BotFather with `/revoke`).
- Do not expose local service APIs to the internet.

## Made with AI
This project was created and iterated with the help of an **AI assistant (ChatGPT)** at the author's request.
