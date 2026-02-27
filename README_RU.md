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


## Быстрая диагностика и Debug
- Включить подробное логирование команд и времени выполнения:
  - `/debug_on`
  - `/debug_off`
- Логи: `/opt/var/log/keenetic-tg-bot.log`

> В Debug режиме бот пишет в лог все команды, rc и время выполнения. Это помогает ловить «долгие ответы».



## Меню Router
Добавлены саб-меню:
- **Сеть**: `ip addr (brief)`, `ip route v4/v6` (группировка по dev, default отдельно)
- **Firewall**: summary/raw для `iptables` (mangle/filter)
- **DHCP клиенты**: LAN / Wi‑Fi / All + карточка каждого клиента (best‑effort разделение)



## Анти-спам уведомлений
Уведомление «мало места на /opt» теперь приходит **не чаще 1 раза в 6 часов** (настраивается в `config.json`):
- `notify.disk_interval_sec`



### Обновление файлов бота
Если бот уже установлен и нужно обновить только файлы (bot.py/init):

```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --update-bot --yes
```
