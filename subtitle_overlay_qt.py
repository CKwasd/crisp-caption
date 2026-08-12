#!/usr/bin/env python3
"""Transparent subtitle overlay backed by PySide6 QWebEngineView.

Run this while bridge_server.py is already serving /ws. It is intentionally
standalone so the native transparent-window behavior can be tested without
changing the existing browser control UI.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import signal
import sys
from pathlib import Path

from overlay_page import qt_overlay_html

try:
    from PySide6.QtCore import QEasingCurve, QPoint, QRect, QPropertyAnimation, QTimer, QUrl, Qt
    from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QPushButton, QWidget, QVBoxLayout
except ImportError as exc:  # pragma: no cover - only used for local setup hints
    raise SystemExit(
        "PySide6 is required for the native overlay test.\n"
        "Install it with: py -m pip install PySide6"
    ) from exc


DEFAULT_WS_URL = "ws://127.0.0.1:8765/ws"
DEFAULT_EDGE_HANDLE_PX = 9
DEFAULT_CORNER_HANDLE_PX = 24
SIDE_HANDLE_LENGTH_PX = 92
HANDLE_VISUAL_THICKNESS = 14
CORNER_HANDLE_VISUAL_SIZE = 58
CONTROL_MARGIN_PX = 22
CONTROL_HIDE_GRACE_MS = 650
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
VK_CONTROL = 0x11
CONFIG_PATH = Path.home() / ".crispasr-overlay.json"
DEFAULT_WIDTH = 1180
DEFAULT_HEIGHT = 340
DEFAULT_FONT_PX = 34


def load_overlay_config() -> dict[str, int]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for key in ("x", "y", "width", "height", "font"):
        if key in data:
            try:
                out[key] = int(data[key])
            except (TypeError, ValueError):
                continue
    return out


def save_overlay_config(geometry: QRect, font_px: int) -> None:
    # ponytail: best-effort, saved on shutdown only; losing it on crash is acceptable
    try:
        CONFIG_PATH.write_text(
            json.dumps(
                {
                    "x": geometry.x(),
                    "y": geometry.y(),
                    "width": geometry.width(),
                    "height": geometry.height(),
                    "font": font_px,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


class ResizeHandlesLayer(QWidget):
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        parent = self.parent()
        if not isinstance(parent, SubtitleOverlay):
            return

        frame = parent._frame_rect()
        metrics = parent._handle_metrics(frame)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(20, 96, 230, 235), metrics["visual_thickness"])
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        cx = frame.center().x()
        cy = frame.center().y()
        half_horizontal = metrics["horizontal_side_len"] // 2
        half_vertical = metrics["vertical_side_len"] // 2
        painter.drawLine(cx - half_horizontal, frame.top(), cx + half_horizontal, frame.top())
        painter.drawLine(cx - half_horizontal, frame.bottom(), cx + half_horizontal, frame.bottom())
        painter.drawLine(frame.left(), cy - half_vertical, frame.left(), cy + half_vertical)
        painter.drawLine(frame.right(), cy - half_vertical, frame.right(), cy + half_vertical)

        length = metrics["corner_visual_len"]
        for x, y, x_dir, y_dir in (
            (frame.left(), frame.top(), 1, 1),
            (frame.right(), frame.top(), -1, 1),
            (frame.left(), frame.bottom(), 1, -1),
            (frame.right(), frame.bottom(), -1, -1),
        ):
            path = QPainterPath()
            path.moveTo(x + x_dir * length, y)
            path.lineTo(x, y)
            path.lineTo(x, y + y_dir * length)
            painter.drawPath(path)
MIN_OVERLAY_WIDTH = 360
MIN_OVERLAY_HEIGHT = 140
CLOSE_BUTTON_SIZE = 30


class SubtitleOverlay(QWidget):
    def __init__(
        self,
        *,
        ws_url: str,
        width: int | None,
        height: int | None,
        x: int | None,
        y: int | None,
        font_px: int | None,
        mode: str,
        hold_sec: float,
        fade_sec: float,
        edge_px: int,
        corner_px: int,
        normal_window: bool,
    ) -> None:
        super().__init__()
        cfg = load_overlay_config()
        self.font_px = font_px if font_px is not None else int(cfg.get("font") or DEFAULT_FONT_PX)
        self.edge_handle_px = max(8, edge_px)
        self.corner_handle_px = max(self.edge_handle_px, corner_px)
        self._control_down = False
        self._cursor_inside_overlay = False
        self._mouse_passthrough = False
        self._shutting_down = False
        self._resize_mode = ""
        self._drag_start_global = QPoint()
        self._drag_start_geometry = QRect()

        self.setWindowTitle("CrispASR Subtitle Overlay")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        window_type = Qt.Window if normal_window else Qt.Tool
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
            | window_type
        )

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.view.setStyleSheet("background: transparent;")
        self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.view.setHtml(
            qt_overlay_html(ws_url, self.font_px, mode=mode, hold_sec=hold_sec, fade_sec=fade_sec),
            QUrl("http://127.0.0.1:8765/"),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.frame = QWidget(self)
        self.frame.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.frame.setStyleSheet(
            """
            background: rgba(24, 34, 48, 64);
            border: 2px solid rgba(120, 190, 255, 210);
            border-radius: 8px;
            """
        )
        self.frame_opacity = QGraphicsOpacityEffect(self.frame)
        self.frame_opacity.setOpacity(0.0)
        self.frame.setGraphicsEffect(self.frame_opacity)
        self.frame_animation = QPropertyAnimation(self.frame_opacity, b"opacity", self)
        self.frame_animation.setDuration(160)
        self.frame_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.frame_animation.finished.connect(self._on_frame_animation_finished)
        self.frame.hide()

        self.handles_layer = ResizeHandlesLayer(self)
        self.handles_layer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.handles_layer.setStyleSheet("background: transparent;")
        self.handles_layer.hide()
        self.handles_opacity = QGraphicsOpacityEffect(self.handles_layer)
        self.handles_opacity.setOpacity(0.0)
        self.handles_layer.setGraphicsEffect(self.handles_opacity)
        self.handles_animation = QPropertyAnimation(self.handles_opacity, b"opacity", self)
        self.handles_animation.setDuration(160)
        self.handles_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.handles_animation.finished.connect(self._on_handles_animation_finished)

        self.close_button = QPushButton("x", self)
        self.close_button.setFixedSize(CLOSE_BUTTON_SIZE, CLOSE_BUTTON_SIZE)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setStyleSheet(
            """
            QPushButton {
              background: rgba(15, 23, 32, 210);
              border: 1px solid rgba(255, 255, 255, 150);
              border-radius: 15px;
              color: rgba(255, 255, 255, 230);
              font: 700 18px/1 system-ui, sans-serif;
              padding-bottom: 2px;
            }
            QPushButton:hover {
              background: rgba(220, 60, 72, 235);
              border-color: rgba(255, 255, 255, 220);
            }
            """
        )
        self.close_button.clicked.connect(self.shutdown)
        self.close_button.hide()

        self.close_button_opacity = QGraphicsOpacityEffect(self.close_button)
        self.close_button_opacity.setOpacity(0.0)
        self.close_button.setGraphicsEffect(self.close_button_opacity)
        self.close_button_animation = QPropertyAnimation(self.close_button_opacity, b"opacity", self)
        self.close_button_animation.setDuration(160)
        self.close_button_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.close_button_animation.finished.connect(self._on_close_button_animation_finished)

        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.timeout.connect(self._hide_frame)

        self.control_timer = QTimer(self)
        self.control_timer.timeout.connect(self._sync_control_state)
        self.control_timer.start(50)

        self.resize(
            width if width is not None else cfg.get("width", DEFAULT_WIDTH),
            height if height is not None else cfg.get("height", DEFAULT_HEIGHT),
        )
        self._place_window(x if x is not None else cfg.get("x"), y if y is not None else cfg.get("y"))

        QShortcut(QKeySequence("Esc"), self, activated=self._hide_frame)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.shutdown)

    def enterEvent(self, event) -> None:  # noqa: N802, ANN001
        super().enterEvent(event)
        self._cursor_inside_overlay = True
        self.leave_timer.stop()

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        super().leaveEvent(event)
        self._cursor_inside_overlay = False
        if not self._resize_mode:
            self.leave_timer.start(CONTROL_HIDE_GRACE_MS)

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier:
            self._begin_resize_or_move(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._resize_mode:
            self._resize_or_move(event.globalPosition().toPoint())
            event.accept()
            return
        if event.modifiers() & Qt.ControlModifier:
            self._show_frame()
            self._set_resize_cursor(event.position().toPoint())
        else:
            if not self._resize_mode:
                self._hide_frame()
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._resize_mode:
            self._resize_mode = ""
            self.unsetCursor()
            if not QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.leave_timer.start(120)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._is_control_pressed():
            delta = event.angleDelta().y()
            if delta:
                new_font = max(14, min(96, self.font_px + (2 if delta > 0 else -2)))
                if new_font != self.font_px:
                    self.font_px = new_font
                    self._apply_font()
            event.accept()
            return
        super().wheelEvent(event)

    def _apply_font(self) -> None:
        main = self.font_px
        js = (
            f"document.getElementById('main').style.fontSize='{main}px';"
            f"document.getElementById('partial').style.fontSize='{max(16, round(main * 0.72))}px';"
            f"document.getElementById('trans').style.fontSize='{max(16, round(main * 0.88))}px';"
        )
        try:
            self.view.page().runJavaScript(js)
        except RuntimeError:
            pass

    def keyPressEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.key() == Qt.Key_Control and self._cursor_inside_overlay:
            self._show_frame()
            self._set_resize_cursor(self.mapFromGlobal(self.cursor().pos()))
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.key() == Qt.Key_Control and not self._resize_mode:
            self._hide_frame()
            self.unsetCursor()
        super().keyReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        self.frame.setGeometry(self._frame_rect())
        self.frame.raise_()
        self.handles_layer.setGeometry(self.rect())
        self.handles_layer.update()
        self.handles_layer.raise_()
        self._position_close_button()

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        self._set_mouse_passthrough(True)

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._shutting_down:
            super().closeEvent(event)
            return
        self.shutdown()
        event.accept()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        save_overlay_config(self.geometry(), self.font_px)
        self.control_timer.stop()
        self.leave_timer.stop()
        self._set_mouse_passthrough(False)
        try:
            self.view.page().runJavaScript(
                "window.__crispasrWs && window.__crispasrWs.readyState < 2 && "
                "window.__crispasrWs.close(1000, 'overlay closed');"
            )
            self.view.setUrl(QUrl("about:blank"))
            self.view.close()
            self.view.deleteLater()
        except RuntimeError:
            pass
        self.close()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
            QTimer.singleShot(50, lambda: app.exit(0))

    def _place_window(self, x: int | None, y: int | None) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            if x is not None and y is not None:
                self.move(x, y)
            return

        area = screen.availableGeometry()
        target_x = x if x is not None else area.x() + (area.width() - self.width()) // 2
        target_y = y if y is not None else area.y() + area.height() - self.height() - 58
        self.move(target_x, target_y)

    def _set_mouse_passthrough(self, enabled: bool) -> None:
        if self._mouse_passthrough == enabled:
            return
        self._mouse_passthrough = enabled
        if sys.platform != "win32":
            self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)
            return
        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        get_window_long = user32.GetWindowLongW
        set_window_long = user32.SetWindowLongW
        ex_style = get_window_long(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED
        if enabled:
            ex_style |= WS_EX_TRANSPARENT
        else:
            ex_style &= ~WS_EX_TRANSPARENT
        set_window_long(hwnd, GWL_EXSTYLE, ex_style)

    def _is_control_pressed(self) -> bool:
        if sys.platform == "win32":
            return bool(ctypes.windll.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        return bool(QApplication.keyboardModifiers() & Qt.ControlModifier)

    def _sync_control_state(self) -> None:
        control_down = self._is_control_pressed()
        cursor_inside = self.frameGeometry().contains(QCursor.pos())
        changed = control_down != self._control_down or cursor_inside != self._cursor_inside_overlay
        self._control_down = control_down
        self._cursor_inside_overlay = cursor_inside
        if not changed:
            return

        if control_down and (cursor_inside or self._resize_mode):
            self._set_mouse_passthrough(False)
            self._show_frame()
        elif not self._resize_mode:
            self._hide_frame()
            self.unsetCursor()
            self._set_mouse_passthrough(True)

    def _show_frame(self) -> None:
        if not self._resize_mode and not (self._control_down and self._cursor_inside_overlay):
            return
        self.leave_timer.stop()
        self.frame.setGeometry(self._frame_rect())
        self.frame.raise_()
        self.frame.show()
        self.handles_layer.setGeometry(self.rect())
        self.handles_layer.update()
        self.handles_layer.raise_()
        self.handles_layer.show()
        self._position_close_button()
        self.close_button.raise_()
        self.close_button.show()
        self._animate_frame_opacity(0.72)
        self._animate_handles_opacity(1.0)
        self._animate_close_button_opacity(1.0)

    def _hide_frame(self) -> None:
        if not self._resize_mode:
            self._animate_frame_opacity(0.0)
            self._animate_handles_opacity(0.0)
            self._animate_close_button_opacity(0.0)

    def _animate_frame_opacity(self, opacity: float) -> None:
        self.frame_animation.stop()
        self.frame_animation.setStartValue(self.frame_opacity.opacity())
        self.frame_animation.setEndValue(opacity)
        self.frame_animation.start()

    def _animate_handles_opacity(self, opacity: float) -> None:
        self.handles_animation.stop()
        self.handles_animation.setStartValue(self.handles_opacity.opacity())
        self.handles_animation.setEndValue(opacity)
        self.handles_animation.start()

    def _animate_close_button_opacity(self, opacity: float) -> None:
        self.close_button_animation.stop()
        self.close_button_animation.setStartValue(self.close_button_opacity.opacity())
        self.close_button_animation.setEndValue(opacity)
        self.close_button_animation.start()

    def _on_frame_animation_finished(self) -> None:
        if self.frame_opacity.opacity() <= 0.01:
            self.frame.hide()

    def _on_handles_animation_finished(self) -> None:
        if self.handles_opacity.opacity() <= 0.01:
            self.handles_layer.hide()

    def _on_close_button_animation_finished(self) -> None:
        if self.close_button_opacity.opacity() <= 0.01:
            self.close_button.hide()

    def _position_close_button(self) -> None:
        frame = self._frame_rect()
        margin = 14
        self.close_button.move(frame.right() - CLOSE_BUTTON_SIZE - margin, frame.top() + margin)

    def _frame_rect(self) -> QRect:
        return self.rect().adjusted(
            CONTROL_MARGIN_PX,
            CONTROL_MARGIN_PX,
            -CONTROL_MARGIN_PX,
            -CONTROL_MARGIN_PX,
        )

    def _handle_metrics(self, frame: QRect) -> dict[str, int]:
        min_dim = max(1, min(frame.width(), frame.height()))
        return {
            "visual_thickness": max(8, min(HANDLE_VISUAL_THICKNESS, round(min_dim * 0.032))),
            "horizontal_side_len": max(44, min(SIDE_HANDLE_LENGTH_PX, round(frame.width() * 0.075))),
            "vertical_side_len": max(38, min(SIDE_HANDLE_LENGTH_PX, round(frame.height() * 0.18))),
            "corner_visual_len": max(30, min(CORNER_HANDLE_VISUAL_SIZE, round(min_dim * 0.14))),
            "edge_hit_px": max(5, min(self.edge_handle_px, round(min_dim * 0.024))),
            "corner_hit_px": max(12, min(self.corner_handle_px, round(min_dim * 0.07))),
        }

    def _begin_resize_or_move(self, event) -> None:  # noqa: ANN001
        self._show_frame()
        self._resize_mode = self._hit_test(event.position().toPoint()) or "move"
        self._drag_start_global = event.globalPosition().toPoint()
        self._drag_start_geometry = self.geometry()
        self._set_cursor_for_mode(self._resize_mode)

    def _resize_or_move(self, current_global: QPoint) -> None:
        delta = current_global - self._drag_start_global
        start = self._drag_start_geometry
        geom = QRect(start)

        if self._resize_mode == "move":
            self.move(start.topLeft() + delta)
            return

        if "left" in self._resize_mode:
            new_left = min(start.left() + delta.x(), start.right() - MIN_OVERLAY_WIDTH)
            geom.setLeft(new_left)
        if "right" in self._resize_mode:
            geom.setRight(max(start.right() + delta.x(), start.left() + MIN_OVERLAY_WIDTH))
        if "top" in self._resize_mode:
            new_top = min(start.top() + delta.y(), start.bottom() - MIN_OVERLAY_HEIGHT)
            geom.setTop(new_top)
        if "bottom" in self._resize_mode:
            geom.setBottom(max(start.bottom() + delta.y(), start.top() + MIN_OVERLAY_HEIGHT))

        self.setGeometry(geom)

    def _hit_test(self, pos: QPoint) -> str:
        frame = self._frame_rect()
        metrics = self._handle_metrics(frame)
        corner_hit = metrics["corner_hit_px"]
        if (
            abs(pos.x() - frame.left()) <= corner_hit
            and abs(pos.y() - frame.top()) <= corner_hit
        ):
            return "top-left"
        if (
            abs(pos.x() - frame.right()) <= corner_hit
            and abs(pos.y() - frame.top()) <= corner_hit
        ):
            return "top-right"
        if (
            abs(pos.x() - frame.left()) <= corner_hit
            and abs(pos.y() - frame.bottom()) <= corner_hit
        ):
            return "bottom-left"
        if (
            abs(pos.x() - frame.right()) <= corner_hit
            and abs(pos.y() - frame.bottom()) <= corner_hit
        ):
            return "bottom-right"

        center_x = frame.center().x()
        center_y = frame.center().y()
        half_horizontal = metrics["horizontal_side_len"] // 2
        half_vertical = metrics["vertical_side_len"] // 2
        edge_hit = metrics["edge_hit_px"]
        in_center_x_handle = abs(pos.x() - center_x) <= half_horizontal
        in_center_y_handle = abs(pos.y() - center_y) <= half_vertical

        if abs(pos.y() - frame.top()) <= edge_hit and in_center_x_handle:
            return "top"
        if abs(pos.y() - frame.bottom()) <= edge_hit and in_center_x_handle:
            return "bottom"
        if abs(pos.x() - frame.left()) <= edge_hit and in_center_y_handle:
            return "left"
        if abs(pos.x() - frame.right()) <= edge_hit and in_center_y_handle:
            return "right"
        return ""

    def _set_resize_cursor(self, pos: QPoint) -> None:
        self._set_cursor_for_mode(self._hit_test(pos) or "move")

    def _set_cursor_for_mode(self, mode: str) -> None:
        if mode in {"top-left", "bottom-right"}:
            self.setCursor(Qt.SizeFDiagCursor)
        elif mode in {"top-right", "bottom-left"}:
            self.setCursor(Qt.SizeBDiagCursor)
        elif mode in {"left", "right"}:
            self.setCursor(Qt.SizeHorCursor)
        elif mode in {"top", "bottom"}:
            self.setCursor(Qt.SizeVerCursor)
        elif mode == "move":
            self.setCursor(Qt.SizeAllCursor)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL, help="Bridge WebSocket URL.")
    parser.add_argument("--width", type=int, default=None, help="Overlay window width.")
    parser.add_argument("--height", type=int, default=None, help="Overlay window height.")
    parser.add_argument("--x", type=int, default=None, help="Overlay left position.")
    parser.add_argument("--y", type=int, default=None, help="Overlay top position.")
    parser.add_argument(
        "--font-px",
        type=int,
        default=None,
        help="Main subtitle font size (default: saved config or 34).",
    )
    parser.add_argument(
        "--mode",
        choices=("source", "trans", "both"),
        default="both",
        help="Display mode: source text, translation (fallback source), or both lines.",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=2.0,
        help="Minimum seconds each line stays before the next may replace it.",
    )
    parser.add_argument(
        "--fade",
        type=float,
        default=4.0,
        help="Seconds of inactivity before the subtitle fades out (0 = never).",
    )
    parser.add_argument(
        "--edge-px",
        type=int,
        default=DEFAULT_EDGE_HANDLE_PX,
        help="Ctrl-drag side resize hit thickness in pixels.",
    )
    parser.add_argument(
        "--corner-px",
        type=int,
        default=DEFAULT_CORNER_HANDLE_PX,
        help="Ctrl-drag corner resize hit radius in pixels.",
    )
    parser.add_argument(
        "--normal-window",
        action="store_true",
        help="Use a normal Qt window instead of the default tool window.",
    )
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    ns = parse_args(argv)
    app = QApplication(argv)
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    signal_timer = QTimer(app)
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(100)
    app._crispasr_signal_timer = signal_timer  # Keep Ctrl+C signal pump alive.
    overlay = SubtitleOverlay(
        ws_url=ns.ws_url,
        width=ns.width,
        height=ns.height,
        x=ns.x,
        y=ns.y,
        font_px=ns.font_px,
        mode=ns.mode,
        hold_sec=ns.hold,
        fade_sec=ns.fade,
        edge_px=ns.edge_px,
        corner_px=ns.corner_px,
        normal_window=ns.normal_window,
    )
    overlay.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
