"""Install a user service for collection without any desktop app process."""
import os
from pathlib import Path
import sys

def install(executable, config_home):
    units=Path(config_home)/"systemd/user";units.mkdir(parents=True,exist_ok=True)
    path=str(Path(executable).resolve()).replace('%','%%').replace('\\','\\\\').replace('"','\\"')
    service=units/'ruuvilinux-collector.service'
    service.write_text(f'''[Unit]
Description=RuuviTag background BLE and MQTT collector

[Service]
Type=simple
# Optional private settings, e.g. RUUVILINUX_HA_HOST for Home Assistant.
EnvironmentFile=-%h/.config/ruuvilinux/collector.env
ExecStart="{path}"
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
UMask=0077

[Install]
WantedBy=default.target
''')
    return service

if __name__=='__main__':
    install(sys.argv[1],os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
