# Keenetic Telegram Router Bot (Entware)

Этот проект — Telegram-бот, который запускается **прямо на роутере Keenetic** (в окружении Entware) и позволяет управлять:

- **Router** (статус, сеть, DHCP, экспорт running-config, reboot и базовая диагностика)
- **HydraRoute** (Neo/Classic): start/stop/restart/status, HRweb link, работа с `domain.conf` и т.д.
- **NFQWS2** (+ web): управление сервисом, списками, логами, web-ссылкой, диагностика iptables/NFQUEUE
- **AWG Manager**: управление сервисом, web-ссылкой, health-check, `wg show`, выгрузка `settings.json`
- **OPKG**: update / list-upgradable / upgrade целевых пакетов

## Важно про безопасность

1) Бот **не даёт выполнять произвольные shell-команды**.
2) Доступ ограничен **по Telegram user_id** (admins).
3) По умолчанию бот принимает команды только в **личке админов**. Для групп/каналов используйте allow_chats.

## Установка (на роутере)

### 0) Нужен Entware
Убедитесь, что Entware установлен и `/opt` смонтирован.

### 1) Скопируйте проект на роутер
Например:

```sh
mkdir -p /opt/tmp/keenetic-tg-bot
cd /opt/tmp/keenetic-tg-bot
# сюда положите файлы bot.py, install.sh, config.example.json, S99keenetic-tg-bot
```

### 2) Запуск установщика

```sh
sh install.sh
```

### 3) Настройка

Отредактируйте:

`/opt/etc/keenetic-tg-bot/config.json`

Обязательно заполните:
- `bot_token`
- `admins` (ваш Telegram user_id)

### 4) Управление сервисом

```sh
/opt/etc/init.d/S99keenetic-tg-bot status
/opt/etc/init.d/S99keenetic-tg-bot restart
tail -n 200 /opt/var/log/keenetic-tg-bot.log
```

## Как узнать свой Telegram user_id
Самый простой способ: напишите любому боту, который показывает ID (например @userinfobot), или временно добавьте логирование в код.

## Мониторинг / уведомления
Бот умеет:
- присылать уведомления о падении сервисов (Hydra/NFQWS2/AWG)
- присылать уведомления об ошибках в логах (по словам ERROR/FATAL/PANIC)
- присылать уведомления о доступных обновлениях opkg (по расписанию)
- присылать уведомления об отсутствии интернета

Настройки в `config.json` → `monitor` и `notify`.

## Где править функциональность
Основной код: `/opt/keenetic-tg-bot/bot.py`

Внутри есть драйверы:
- RouterDriver
- HydraRouteDriver
- NfqwsDriver
- AwgDriver
- OpkgDriver

Добавляйте свои команды в меню обработчика callback-кнопок.


## Автоустановка

На роутере:

```sh
sh autoinstall.sh --all
```

Выборочно:

```sh
sh autoinstall.sh --bot --cron --weekly
sh autoinstall.sh --hydra --nfqws2 --nfqwsweb --awg
```


## Как залить на GitHub

Я не могу сам запушить репозиторий за тебя (нет доступа к твоему GitHub), но проект готов к публикации. На ПК в папке проекта:

```sh
git init
git add .
git commit -m "keenetic tg bot"
# создай пустой репозиторий на GitHub, затем:
git remote add origin <URL>
git branch -M main
git push -u origin main
```


## Автоопределение модулей

Бот сам определяет наличие компонентов (HydraRoute Neo/Classic, NFQWS2, NFQWS web, AWG, cron) и помечает/предлагает установить отсутствующие через меню **Установка/Сервис**.
