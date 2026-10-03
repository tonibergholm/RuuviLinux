from PySide6.QtWidgets import QApplication, QWidget
from ruuvilinux.instance import InstanceGuard


def test_background_reuse_and_window_activation(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = InstanceGuard(tmp_path/'sensors.db')
    window = QWidget(); first.activated.connect(window.show)
    try:
        assert first.claim(background=True)
        second = InstanceGuard(tmp_path/'sensors.db')
        assert not second.claim(background=True)
        for _ in range(5): app.processEvents()
        assert not window.isVisible()
        third = InstanceGuard(tmp_path/'sensors.db')
        assert not third.claim()
        for _ in range(5): app.processEvents()
        assert window.isVisible()
    finally:
        window.close(); first.close()


def test_separate_databases_have_separate_collectors(tmp_path):
    app = QApplication.instance() or QApplication([])
    first,second = InstanceGuard(tmp_path/'one.db'),InstanceGuard(tmp_path/'two.db')
    try:
        assert first.claim() and second.claim()
        assert first.name != second.name
    finally:
        first.close(); second.close()
