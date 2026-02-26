# Keenetic TG Bot (Entware)

Telegram‑бот, который запускается **на роутере** (Entware `/opt`) и управляет: Router / HydraRoute / NFQWS2(+web) / AWG Manager / opkg + уведомления.

## Установка (one‑liner)
Интерактивно (в начале выбор языка RU/EN):
```sh
opkg update && opkg install ca-certificates curl && \
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh
```

Автоматически (без вопросов, но нужен токен и user_id):
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | \
sh -s -- --yes --bot --token 123456:ABCDEF --admin 599497434
```

Полный вывод установки:
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --debug
```

## Как получить bot_token
1) Telegram → **@BotFather**
2) `/newbot`
3) Скопируй токен вида `123456:ABCDEF...`

## Как узнать свой user_id
Проще всего: Telegram → **@userinfobot** → поле `Id: ...`

## Где лежат файлы после установки
- Код и конфиг: `/etc/keenetic-tg-bot/` (на Keenetic /etc часто read-only, поэтому установщик автоматически использует `/opt/etc/keenetic-tg-bot/`)
- init‑скрипт: `/opt/etc/init.d/S99keenetic-tg-bot`
- лог бота: `/opt/var/log/keenetic-tg-bot.log`
- лог установки: `/opt/var/log/keenetic-tg-bot-install.log`

## Управление
```sh
/opt/etc/init.d/S99keenetic-tg-bot status
/opt/etc/init.d/S99keenetic-tg-bot restart
tail -n 200 /opt/var/log/keenetic-tg-bot.log
```

<details>
<summary>Параметры установки (нажми чтобы раскрыть)</summary>

- `--lang ru|en` — язык сообщений
- `--debug` или `-debug` — подробный вывод команд + лог
- `--yes` — автоматический режим (без вопросов)
- `--bot` — установить/обновить бота
- `--token <BOT_TOKEN>` — токен BotFather
- `--admin <USER_ID>` — твой Telegram user_id числом
- `--reconfig` — перезаписать config.json (спросит token/id)
- `--hydra` — HydraRoute Neo
- `--nfqws2` — NFQWS2
- `--nfqwsweb` — NFQWS web UI (автоматически включает `--nfqws2`)
- `--awg` — AWG Manager
- `--cron` — cron
- `--weekly` — автообновление каждую **четверг 06:00**

</details>

## Безопасность
- Не публикуй токен (если утёк — отзови у BotFather `/revoke`).
- Не открывай наружу локальные API сервисов.

## Сделано с помощью ИИ
Проект создавался и дорабатывался с помощью **ИИ‑ассистента (ChatGPT)** по запросам автора.
