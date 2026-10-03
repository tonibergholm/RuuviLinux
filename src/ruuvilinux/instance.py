"""One collector/window per database, with a local activate command."""
import hashlib
from pathlib import Path
from PySide6.QtCore import QObject, QLockFile, QStandardPaths, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class InstanceGuard(QObject):
    activated = Signal()

    def __init__(self, database, parent=None):
        super().__init__(parent)
        digest = hashlib.sha256(str(Path(database).expanduser().resolve()).encode()).hexdigest()[:20]
        runtime = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation))
        self.name = str(runtime / f"ruuvilinux-{digest}")
        self.lock = QLockFile(self.name + ".lock")
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.accept)
        self.sockets = []

    def claim(self, background=False):
        if not self.lock.tryLock(0):
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if not socket.waitForConnected(1500):
                raise RuntimeError("RuuviLinux is already starting. Try opening it again shortly.")
            socket.write(b"PING\n" if background else b"SHOW\n")
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError("Could not start the local RuuviLinux window service.")
        return True

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.sockets.append(socket)
            buffer = bytearray()
            def read(socket=socket, buffer=buffer):
                buffer.extend(bytes(socket.readAll()))
                if len(buffer) > 32:
                    socket.abort()
                elif b"\n" in buffer:
                    if bytes(buffer).split(b"\n", 1)[0] == b"SHOW": self.activated.emit()
                    socket.disconnectFromServer()
            def cleanup(socket=socket):
                if socket in self.sockets: self.sockets.remove(socket)
                socket.deleteLater()
            socket.readyRead.connect(read)
            socket.disconnected.connect(cleanup)
            read()

    def close(self):
        self.server.close()
        self.lock.unlock()
