"""Small QWidget plot, avoiding a dependency on Qt Charts."""
from datetime import datetime
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class HistoryChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.unit = "°C"
        self.setMinimumHeight(240)
        self.setAccessibleName("Sensor history chart")

    def set_data(self, rows, field):
        # Preserve missing readings as gaps rather than inventing measurements.
        self.points = [(r["time"], r[field]) for r in rows]
        self.unit = {"temperature": "°C", "humidity": "%", "pressure": "hPa"}[field]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self.palette().color(self.foregroundRole())
        painter.setPen(text)
        area = QRectF(65, 20, max(1, self.width() - 85), max(1, self.height() - 58))
        valid = [(t, v) for t, v in self.points if v is not None]
        if not valid:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "History appears as measurements arrive")
            return
        low, high = min(v for _, v in valid), max(v for _, v in valid)
        pad = max((high - low) * 0.15, 0.5)
        low -= pad; high += pad
        first, last = self.points[0][0], self.points[-1][0]
        span = max(last - first, 60)
        for step in range(5):
            y = area.bottom() - area.height() * step / 4
            grid = QColor(text); grid.setAlpha(35)
            painter.setPen(QPen(grid, 1))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(text)
            label = f"{low + (high-low)*step/4:.1f}"
            painter.drawText(QRectF(0, y-10, 57, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        painter.drawText(QRectF(0, 0, 58, 20), Qt.AlignmentFlag.AlignRight, self.unit)
        painter.drawText(QRectF(area.left(), area.bottom()+10, 100, 24), datetime.fromtimestamp(first).strftime("%H:%M"))
        painter.drawText(QRectF(area.right()-100, area.bottom()+10, 100, 24), Qt.AlignmentFlag.AlignRight, datetime.fromtimestamp(last).strftime("%H:%M"))
        accent = QColor("#2fb6a0")
        painter.setPen(QPen(accent, 2.5))
        path = QPainterPath()
        previous = None
        for t, v in self.points:
            if v is None:
                previous = None
                continue
            point = QPointF(area.left() + (t-first)/span*area.width(), area.bottom()-(v-low)/(high-low)*area.height())
            # Do not connect across sleep / radio gaps longer than five minutes.
            if previous is None or t - previous > 300:
                path.moveTo(point)
            else:
                path.lineTo(point)
            painter.drawEllipse(point, 2.5, 2.5)
            previous = t
        painter.drawPath(path)
