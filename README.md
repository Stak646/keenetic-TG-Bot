# Keenetic TG Bot (Entware)

Бот работает **на роутере** (Entware `/opt`) и управляет: Router / HydraRoute / NFQWS2(+web) / AWG Manager / opkg + уведомления.

## Важно
- **Не вставляй** угловые скобки `< >` в команды (в shell это спецсимволы).
- Если ты случайно засветил токен — **отзови его у @BotFather** (/revoke) и выдай новый.

## Установка (one‑liner)
Интерактивно (скрипт спрашивает y/N и попросит token + user_id при установке бота):
```sh
opkg update && opkg install ca-certificates curl && \
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh
```

Без вопросов (передай токен и ID):
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | \
sh -s -- --yes --bot --token 123456:ABCDEF --admin 599497434
```

## Как получить bot_token
1) Telegram → **@BotFather**
2) `/newbot`
3) Скопируй токен вида `123456:ABCDEF...`

## Как узнать свой user_id
Проще всего: Telegram → **@userinfobot** → поле `Id: ...`

## Где лежат файлы в Entware
- Код бота: `/opt/keenetic-tg-bot/bot.py`
- Конфиг: `/opt/etc/keenetic-tg-bot/config.json`
- Init-скрипт: `/opt/etc/init.d/S99keenetic-tg-bot`
- Лог: `/opt/var/log/keenetic-tg-bot.log`

## Управление
```sh
/opt/etc/init.d/S99keenetic-tg-bot status
/opt/etc/init.d/S99keenetic-tg-bot restart
tail -n 200 /opt/var/log/keenetic-tg-bot.log
```
