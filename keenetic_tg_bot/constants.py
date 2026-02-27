# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

# Config paths:
# On Keenetic, /etc is often read-only, so default is /opt/etc.
DEFAULT_CONFIG_PATH = "/opt/etc/keenetic-tg-bot/config.json"
ALT_CONFIG_PATH = "/etc/keenetic-tg-bot/config.json"

LOG_PATH = "/opt/var/log/keenetic-tg-bot.log"

# HydraRoute Neo paths
HR_DIR = Path("/opt/etc/HydraRoute")
HR_NEO_CONF = HR_DIR / "hrneo.conf"
HR_DOMAIN_CONF = HR_DIR / "domain.conf"
HR_IP_LIST = HR_DIR / "ip.list"
HR_NEO_LOG_DEFAULT = Path("/opt/var/log/LOGhrneo.log")

# NFQWS2 paths
NFQWS_DIR = Path("/opt/etc/nfqws2")
NFQWS_CONF = NFQWS_DIR / "nfqws2.conf"
NFQWS_LISTS_DIR = NFQWS_DIR / "lists"
NFQWS_LOG = Path("/opt/var/log/nfqws2.log")
NFQWS_INIT = Path("/opt/etc/init.d/S51nfqws2")
NFQWS_NETFILTER_HOOK = Path("/opt/etc/ndm/netfilter.d/100-nfqws2.sh")

# NFQWS web
NFQWS_WEB_CONF = Path("/opt/etc/nfqws_web.conf")

# AWG Manager
AWG_INIT = Path("/opt/etc/init.d/S99awg-manager")
AWG_SETTINGS = Path("/opt/etc/awg-manager/settings.json")

TARGET_PKGS = [
    "hrneo",
    "hrweb",
    "hydraroute",
    "nfqws2-keenetic",
    "nfqws-keenetic-web",
    "awg-manager",
]
