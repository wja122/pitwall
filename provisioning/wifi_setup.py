"""WiFi credential writer — uses nmcli to connect, updates config, reboots."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


def scan_wifi_networks() -> list[str]:
    """Return a deduplicated list of SSIDs in range, sorted by signal strength."""
    result = subprocess.run(
        ['nmcli', '-t', '-f', 'SSID,SIGNAL', 'device', 'wifi', 'list'],
        check=True, capture_output=True, text=True
    )
    seen: set[str] = set()
    networks: list[tuple[str, int]] = []
    for line in result.stdout.strip().split('\n'):
        if not line or line.startswith(':'):
            continue
        ssid_raw, signal_str = line.rsplit(':', 1)
        ssid = ssid_raw.replace('\\:', ':')
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            networks.append((ssid, int(signal_str)))
        except ValueError:
            continue
    networks.sort(key=lambda x: x[1], reverse=True)
    return [ssid for ssid, _ in networks]


def connect_and_reboot(ssid: str, password: str, config_path: Path) -> None:
    """Connect to ssid via nmcli, mark provisioning complete, and reboot.

    Raises RuntimeError with a human-readable message on connection failure.
    Caller is responsible for stopping AP mode before calling this.
    """
    if not ssid:
        raise ValueError('SSID cannot be empty.')
    subprocess.run(
        ['nmcli', 'device', 'wifi', 'rescan', 'ifname', 'wlan0'],
        check=False,  # rescan can return non-zero if already scanning; ignore
    )
    time.sleep(3)
    cmd = ['nmcli', 'device', 'wifi', 'connect', ssid, 'ifname', 'wlan0']
    if password:
        cmd += ['password', password]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        msg = e.stderr.strip() or e.stdout.strip() or f'Failed to connect to {ssid!r}'
        raise RuntimeError(msg)

    config = json.loads(config_path.read_text())
    config['provisioning_complete'] = True
    config['wifi_ssid'] = ssid
    config_path.write_text(json.dumps(config, indent=2))

    subprocess.run(['reboot', 'now'])