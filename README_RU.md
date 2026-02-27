# Keenetic TG Bot (Entware)

Telegram-бот, который запускается **на роутере** (Entware `/opt`) и управляет: Router / HydraRoute / NFQWS2(+web) / AWG Manager / opkg + уведомления.

## Установка (one-liner)
Интерактивно (в начале выбор языка RU/EN):
```sh
opkg update && opkg install ca-certificates curl && \
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh
```

Автоматически:
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | \
sh -s -- --yes --bot --token 123456:ABCDEF --admin 599497434
```

Полный вывод:
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --debug
```

## Как получить bot_token
1) Telegram → **@BotFather**
2) `/newbot`
3) Скопируй токен вида `123456:ABCDEF...`

## Как узнать свой user_id
Проще всего: Telegram → **@userinfobot** → `Id: ...`

## Где лежат файлы
- Код и конфиг: `/etc/keenetic-tg-bot/` (на Keenetic `/etc` часто read-only, поэтому установщик автоматически использует `/opt/etc/keenetic-tg-bot/`)
- init-скрипт: `/opt/etc/init.d/S99keenetic-tg-bot`
- лог бота: `/opt/var/log/keenetic-tg-bot.log`
- лог установки: `/opt/var/log/keenetic-tg-bot-install.log`

<details>
<summary>Параметры установки</summary>

- `--lang ru|en`
- `--debug` / `-debug` — подробный вывод
- `--yes` — без вопросов
- `--bot` — установить/обновить бота
- `--token <BOT_TOKEN>` — токен BotFather
- `--admin <USER_ID>` — твой Telegram user_id (число)
- `--reconfig` — переписать config.json (спросит token/id)
- `--hydra` — HydraRoute Neo
- `--nfqws2` — NFQWS2
- `--nfqwsweb` — NFQWS web UI (также ставит NFQWS2)
- `--awg` — AWG Manager
- `--cron` — cron
- `--weekly` — автообновление каждый Чт 06:00

</details>

## Управление сервисом
```sh
/opt/etc/init.d/S99keenetic-tg-bot status
/opt/etc/init.d/S99keenetic-tg-bot restart
tail -n 200 /opt/var/log/keenetic-tg-bot.log
```

## Безопасность
Не публикуй токен. Если утёк — отзови у BotFather (`/revoke`) и запусти установку с `--bot --reconfig`.



### Обновление уже установленного бота (без переустановки модулей)
```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --update-bot --yes
```
Если видишь ошибку **409 Conflict (getUpdates)** — запущено несколько экземпляров. Исправь:
```sh
/opt/etc/init.d/S99keenetic-tg-bot stop
ps w | grep -F /opt/etc/keenetic-tg-bot/bot.py | grep -v grep
/opt/etc/init.d/S99keenetic-tg-bot start
```


### Debug
- `/debug_on` — включить подробный лог команд и времени выполнения
- `/debug_off` — выключить
Лог: `/opt/var/log/keenetic-tg-bot.log`


### Network stability
Polling is now wrapped with exponential backoff to recover from transient disconnects (RemoteDisconnected/timeouts).


### Если видишь Read timed out на api.telegram.org
- Проверь доступ с роутера: `curl -vk --connect-timeout 10 --max-time 20 https://api.telegram.org/`
- Если включены маршрутизации/обходы (HydraRoute/NFQWS/AWG), попробуй исключить `api.telegram.org` из туннелей или направить его напрямую через WAN.
