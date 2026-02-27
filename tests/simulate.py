#!/usr/bin/env python3
"""
Offline simulation: runs without real Telegram library/network.

It monkeypatches minimal `telebot` stubs into sys.modules, then imports the bot
and renders a few screens to ensure the router-side code does not crash.

Run:
  python3 tests/simulate.py
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass


def install_telebot_stub() -> None:
    telebot = types.ModuleType("telebot")

    # apihelper submodule
    apihelper = types.ModuleType("telebot.apihelper")

    class ApiTelegramException(Exception):
        pass

    apihelper.ApiTelegramException = ApiTelegramException
    apihelper.CONNECT_TIMEOUT = 5
    apihelper.READ_TIMEOUT = 20
    telebot.apihelper = apihelper

    # types submodule
    types_mod = types.ModuleType("telebot.types")

    @dataclass
    class InlineKeyboardButton:
        text: str
        callback_data: str

    class InlineKeyboardMarkup:
        def __init__(self):
            self.rows = []

        def row(self, *buttons):
            self.rows.append(list(buttons))

    types_mod.InlineKeyboardButton = InlineKeyboardButton
    types_mod.InlineKeyboardMarkup = InlineKeyboardMarkup
    telebot.types = types_mod

    class TeleBot:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        # Decorators
        def message_handler(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco

        def callback_query_handler(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco

        # Telegram methods (no-op)
        def send_message(self, *args, **kwargs):
            return None

        def edit_message_text(self, *args, **kwargs):
            return None

        def answer_callback_query(self, *args, **kwargs):
            return None

        def delete_webhook(self, *args, **kwargs):
            return None

        def infinity_polling(self, *args, **kwargs):
            raise RuntimeError("Polling is not available in simulation")

    telebot.TeleBot = TeleBot

    sys.modules["telebot"] = telebot
    sys.modules["telebot.apihelper"] = apihelper
    sys.modules["telebot.types"] = types_mod


def main() -> int:
    install_telebot_stub()

    # Add bot path
    import os
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "keenetic-tg-bot"))
    sys.path.insert(0, base)

    from modules.utils.config import AppConfig
    from modules.utils.log import setup_logging
    from modules.app import App

    from modules.drivers.router import RouterDriver
    from modules.drivers.opkg import OpkgDriver
    from modules.drivers.hydraroute import HydraRouteDriver
    from modules.drivers.nfqws import NfqwsDriver
    from modules.drivers.awg import AwgDriver
    from modules.drivers.speedtest import SpeedTestDriver

    from modules.components.router import RouterComponent
    from modules.components.opkg import OpkgComponent
    from modules.components.components_manager import ComponentsManagerComponent
    from modules.components.hydra import HydraComponent
    from modules.components.nfqws import NfqwsComponent
    from modules.components.awg import AwgComponent
    from modules.components.speed import SpeedComponent
    from modules.components.settings import SettingsComponent

    setup_logging(debug=True, log_path="/tmp/keenetic-tg-bot-test.log")

    cfg = AppConfig(
        bot_token="123:ABC",
        admins=[1],
        language="en",
        debug=True,
        telegram_threads="auto",
        executor_workers="auto",
    )
    app = App(cfg, "/tmp/config.json")

    router_drv = RouterDriver(app.sh)
    opkg_drv = OpkgDriver(app.sh)
    hydra_drv = HydraRouteDriver(app.sh)
    nfqws_drv = NfqwsDriver(app.sh)
    awg_drv = AwgDriver(app.sh)
    speed_drv = SpeedTestDriver(app.sh)

    app.components = {
        "r": RouterComponent(router_drv),
        "o": OpkgComponent(opkg_drv),
        "c": ComponentsManagerComponent(opkg_drv, hydra_drv, nfqws_drv, awg_drv),
        "hy": HydraComponent(hydra_drv),
        "nq": NfqwsComponent(nfqws_drv),
        "aw": AwgComponent(awg_drv),
        "sp": SpeedComponent(speed_drv, opkg_drv, awg_drv),
        "st": SettingsComponent(),
    }

    # Render a few screens
    screens = [
        ("home", app.home_screen()),
        ("router menu", app.components["r"].render(app, "m", {})),
        ("settings", app.components["st"].render(app, "m", {})),
        ("opkg menu", app.components["o"].render(app, "m", {})),
    ]
    for name, s in screens:
        assert isinstance(s.text, str) and s.text
        # KB may be None for some screens; for these it's always present
        print(f"[ok] {name}: text={len(s.text)} chars, kb={'yes' if s.kb else 'no'}")

    print("Simulation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
