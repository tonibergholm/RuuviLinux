"""Install a user service for collection without any desktop app process."""
import os
from pathlib import Path
import sys

def install(executable, config_home):
    config_home=Path(config_home).expanduser().resolve()
    units=config_home/"systemd/user";units.mkdir(parents=True,exist_ok=True)
    path=str(Path(executable).resolve()).replace('%','%%').replace('\\','\\\\').replace('"','\\"')
    # Settings live under the same config root as the unit; only % is special here.
    settings=str(config_home/"ruuvilinux/collector.env").replace('%','%%')
    service=units/'ruuvilinux-collector.service'
    service.write_text(f'''[Unit]
Description=RuuviTag background BLE and MQTT collector

[Service]
Type=simple
# Optional private settings, e.g. RUUVILINUX_HA_HOST for Home Assistant.
EnvironmentFile=-{settings}
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
