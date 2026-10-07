import importlib.util
from pathlib import Path


def test_desktop_launcher_paths_and_icon(tmp_path):
    script = Path(__file__).parents[1]/"scripts/install-desktop.py"
    spec=importlib.util.spec_from_file_location("desktop",script)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    executable=tmp_path/'some path with % and "quotes"'/"ruuvilinux"
    icon=tmp_path/"icon.svg"; icon.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    target=module.install(executable,icon,tmp_path/"data")
    text=target.read_text()
    assert '%%' in text and '\\\\"quotes\\\\"' in text
    assert 'Terminal=false' in text and 'Name=RuuviLinux' in text
    assert (tmp_path/"data/icons/hicolor/scalable/apps/org.ruuvilinux.app.svg").exists()


def test_collector_service_reads_optional_private_settings(tmp_path):
    script = Path(__file__).parents[1]/"scripts/install-service.py"
    spec=importlib.util.spec_from_file_location("service",script)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    text=module.install(tmp_path/"bin with %"/"ruuvilinux-collector",tmp_path/"config 100%").read_text()
    # The settings file follows the configured XDG config home, with systemd % escaping.
    assert f'EnvironmentFile=-{tmp_path}/config 100%%/ruuvilinux/collector.env' in text
    assert 'bin with %%' in text and 'UMask=0077' in text
