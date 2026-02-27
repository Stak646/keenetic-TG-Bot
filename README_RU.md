# Keenetic TG Bot (alfa)

Telegram‑бот для роутеров Keenetic (Entware): управление компонентами, быстрые диагностические команды, модульное меню.

> Ветка **`alfa`** — активная ветка разработки.

## Что уже реализовано

- **Единый стиль кнопок** + саб‑меню + пагинация для больших списков.
- **Роутер**:
  - информация (RAM/CPU/uptime, место на `/opt`, архитектуры opkg)
  - маршруты IPv4/IPv6 (постранично)
  - IP‑адреса интерфейсов (постранично)
  - правила iptables/ip6tables (постранично)
  - DHCP‑клиенты + детальная карточка клиента  
    *(разделение LAN/Wi‑Fi включается автоматически, если есть `iw`)*
  - перезагрузка с подтверждением
- **OPKG**:
  - `opkg update`, `opkg upgrade` (в фоне + “анимация”)
  - список установленных пакетов (страницы)
  - поиск пакета (после нажатия “Поиск” отправьте текстом название)
- **Менеджер компонентов**:
  - установка/удаление (и часть действий сервиса) для:
    - HydraRoute (hrneo/hrweb)
    - NFQWS2 (+ опционально web‑интерфейс)
    - AWG Manager
  - **защита от неправильной архитектуры**: фиды выбираются по `opkg print-architecture`.
- **HydraRoute / NFQWS2 / AWG**: обзор + действия (start/stop/restart).
- **Speed test**:
  - быстрый HTTP‑тест загрузки на “качественные” узлы (Cloudflare / Hetzner)
  - AWG speed test (если доступно API AWG Manager)
  - опционально `speedtest-go` (если доступен/устанавливается)

## Поддерживаемые архитектуры

- `mips`
- `mipsel`
- `aarch64`

## Установка (Entware)

### One‑liner (alfa)

```sh
curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/alfa/autoinstall.sh | sh -s -- --yes --lang ru --token "YOUR_BOT_TOKEN" --admin 123456789
```

Опции:
- `--branch alfa|main`
- `--token ...`
- `--admin <telegram_user_id>` (можно несколько раз)
- `--lang ru|en`
- `--debug`
- `--no-start`

## Конфиг

Файл:
- `/opt/etc/keenetic-tg-bot/config/config.json`

Главное:
- `bot_token`
- `admins` (очень рекомендуется)
- `language` (`ru` / `en`)
- `performance.debug`

## Сервис

```sh
/opt/etc/init.d/S99keenetic-tg-bot start
/opt/etc/init.d/S99keenetic-tg-bot stop
/opt/etc/init.d/S99keenetic-tg-bot restart
/opt/etc/init.d/S99keenetic-tg-bot status
```

## Логи

- `/opt/var/log/keenetic-tg-bot.log` — основной лог (rotating)
- `/opt/var/log/keenetic-tg-bot-console.log` — вывод демона (stdout/stderr)

## Важные примечания

- Ошибка **409 Conflict** обычно означает, что бот запущен в двух местах (2 процесса/2 устройства с одним токеном).
- Бот сам подбирает количество workers по памяти роутера (консервативные значения).

## Структура проекта

В репозитории:
- `keenetic-tg-bot/` → копируется в `/opt/etc/keenetic-tg-bot`
  - `Main.py`
  - `config/`
  - `modules/`
  - `scripts/`

## Идеи “под вопросом” (нужна проверка на реальном Keenetic)

1. **Разделение DHCP клиентов на LAN/Wi‑Fi**  
   Работает, если доступна команда `iw` (получаем MAC‑адреса станций).  
   На некоторых моделях/прошивках `iw` может отсутствовать.

2. **Пакет speedtest-go в Entware**  
   На части архитектур может отсутствовать или тянуть много зависимостей.

3. **Точные названия пакетов NFQWS web**  
   В разных сборках имя может отличаться (`nfqws-keenetic-web` / другое).  
   В таком случае правится 1 строка в менеджере компонентов.

4. **AWG Manager API**  
   Эндпоинты могут немного отличаться в разных версиях.  
   Если какой-то пункт не работает — лог покажет URL/ошибку, легко поправим.

Если хотите — можем расширить эти пункты после 1‑2 логов с вашего роутера.


## Как добавить новый модуль (для расширений)

1. Драйвер (обёртка над shell/API) — `keenetic-tg-bot/modules/drivers/`
2. UI‑модуль — `keenetic-tg-bot/modules/components/` (наследник `ComponentBase`)
3. Регистрация в `keenetic-tg-bot/Main.py`:

```py
from modules.components.my_component import MyComponent
app.components["mx"] = MyComponent(my_driver)
```

Формат callback: `mx|command|k=v&k2=v2`
