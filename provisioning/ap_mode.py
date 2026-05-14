"""AP mode manager — starts hostapd + dnsmasq for the PITWALL setup hotspot."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

HOSTAPD_CONF = Path('/tmp/pitwall-hostapd.conf')
DNSMASQ_CONF = Path('/tmp/pitwall-dnsmasq.conf')


class APMode:
    """Manages hostapd and dnsmasq subprocesses for the PITWALL setup hotspot."""

    SSID       = 'PITWALL'
    INTERFACE  = 'wlan0'
    GATEWAY_IP = '10.3.3.3'

    def __init__(self) -> None:
        self._hostapd_proc: subprocess.Popen | None = None
        self._dnsmasq_proc: subprocess.Popen | None = None

    def start(self) -> None:
        """Bring up the PITWALL hotspot."""
        subprocess.run(['nmcli', 'device', 'set', self.INTERFACE, 'managed', 'no'], check=True)
        subprocess.run(['ip', 'addr', 'add', f'{self.GATEWAY_IP}/24', 'dev', self.INTERFACE], check=True)
        subprocess.run(['ip', 'link', 'set', self.INTERFACE, 'up'], check=True)
        self._write_hostapd_conf(HOSTAPD_CONF)
        self._write_dnsmasq_conf(DNSMASQ_CONF)
        self._hostapd_proc = subprocess.Popen(['hostapd', str(HOSTAPD_CONF)])
        self._dnsmasq_proc = subprocess.Popen(['dnsmasq', '--no-daemon', f'--conf-file={DNSMASQ_CONF}'])

    def stop(self) -> None:
        """Tear down the hotspot and re-enable NetworkManager on wlan0."""
        for proc in (self._dnsmasq_proc, self._hostapd_proc):
            if proc is not None:
                proc.terminate()
                proc.wait()
        self._hostapd_proc = None
        self._dnsmasq_proc = None
        subprocess.run(['ip', 'link', 'set', self.INTERFACE, 'down'], check=True)
        subprocess.run(['ip', 'addr', 'flush', 'dev', self.INTERFACE], check=True)
        subprocess.run(['nmcli', 'device', 'set', self.INTERFACE, 'managed', 'yes'], check=True)

    def _write_hostapd_conf(self, path: Path) -> None:
        """Write a minimal hostapd config to path."""
        path.write_text(textwrap.dedent(f"""\
            interface={self.INTERFACE}
            driver=nl80211
            ssid={self.SSID}
            hw_mode=g
            channel=6
            auth_algs=1
        """))

    def _write_dnsmasq_conf(self, path: Path) -> None:
        """Write a dnsmasq config with DHCP range and DNS wildcard to path."""
        path.write_text(textwrap.dedent(f"""\
            interface={self.INTERFACE}
            dhcp-range=10.3.3.2,10.3.3.20,255.255.255.0,24h
            address=/#/{self.GATEWAY_IP}
            no-resolv
        """))
