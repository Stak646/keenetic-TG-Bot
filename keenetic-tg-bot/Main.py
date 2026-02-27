#!/opt/bin/python3
from __future__ import annotations

import os
import sys

# Ensure local imports work even if cwd differs
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from modules.app import App
from modules.utils.config import load_config
from modules.utils.log import setup_logging
from modules.utils.shell import Shell
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


def main() -> int:
    cfg_path = os.path.join(BASE_DIR, "config", "config.json")
    cfg = load_config(cfg_path)

    logger = setup_logging(debug=cfg.debug)

    if not cfg.bot_token:
        logger.error("Bot token not set. Edit %s", cfg_path)
        print(f"Bot token not set. Edit: {cfg_path}")
        return 2

    app = App(cfg, cfg_path)

    # Drivers
    router_drv = RouterDriver(app.sh)
    opkg_drv = OpkgDriver(app.sh)
    hydra_drv = HydraRouteDriver(app.sh)
    nfqws_drv = NfqwsDriver(app.sh)
    awg_drv = AwgDriver(app.sh, host=cfg.awg_host, port=cfg.awg_port, timeout_sec=cfg.awg_timeout_sec, debug=cfg.debug)
    speed_drv = SpeedTestDriver(app.sh)

    # Components
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

    app.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
