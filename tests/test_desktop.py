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
