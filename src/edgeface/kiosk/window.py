# -*- coding: utf-8 -*-
"""The kiosk window: one page per screen id, driven entirely by the controller.

This file draws and forwards taps. Every decision about WHAT to draw was already made
in view_model.py and controller.py, which is why there is no logic here beyond layout.
"""
import os

from PyQt5 import QtCore, QtGui, QtWidgets

from edgeface.common.log import get_logger
from edgeface.kiosk import strings, view_model as vm
from edgeface.kiosk.widgets.numpad import NumPad
from edgeface.kiosk.widgets.preview import PreviewWidget

LOG = get_logger("kiosk.window")

STYLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
POLL_MS = 100
PREVIEW_MS = 200
ADMIN_GESTURE_MS = 3000       # long-press the corner to reach the admin screen


def load_stylesheet():
    with open(STYLE_PATH) as f:
        return f.read()


class Page(QtWidgets.QWidget):
    """Common furniture: title, message banner, optional fields, button row."""

    button_clicked = QtCore.pyqtSignal(object)

    def __init__(self, parent=None, with_preview=False, roi=None):
        super(Page, self).__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(48, 40, 48, 40)
        outer.setSpacing(20)

        self.title = QtWidgets.QLabel("")
        self.title.setObjectName("title")
        outer.addWidget(self.title)

        self.banner = QtWidgets.QLabel("")
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        outer.addWidget(self.banner)

        self.preview = PreviewWidget(roi=roi) if with_preview else None
        if self.preview is not None:
            outer.addWidget(self.preview, 1)

        self.fields = QtWidgets.QFormLayout()
        self.fields.setHorizontalSpacing(32)
        self.fields.setVerticalSpacing(14)
        outer.addLayout(self.fields)
        outer.addStretch(1)

        self.countdown = QtWidgets.QLabel("")
        self.countdown.setObjectName("countdown")
        outer.addWidget(self.countdown)

        self.buttons = QtWidgets.QHBoxLayout()
        self.buttons.setSpacing(16)
        outer.addLayout(self.buttons)

    def _clear_fields(self):
        while self.fields.count():
            item = self.fields.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _clear_buttons(self):
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def render(self, view):
        self.title.setText(view.title or "")
        self.banner.setText(view.message or "")
        self.banner.setVisible(bool(view.message))
        self.banner.setProperty("severity", view.severity)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)

        self._clear_fields()
        for label, value in view.fields:
            label_widget = QtWidgets.QLabel(label)
            label_widget.setObjectName("fieldLabel")
            value_widget = QtWidgets.QLabel(str(value))
            value_widget.setObjectName("fieldValue")
            self.fields.addRow(label_widget, value_widget)

        self.countdown.setText("" if view.countdown_s is None
                               else "Tự huỷ sau {} giây".format(int(view.countdown_s)))

        self._clear_buttons()
        self.buttons.addStretch(1)
        for button in view.buttons:
            widget = QtWidgets.QPushButton(button.label)
            if button.primary:
                widget.setObjectName("primary")
            elif button.kind in ("reject",):
                widget.setObjectName("danger")
            widget.clicked.connect(
                lambda _checked=False, b=button: self.button_clicked.emit(b))
            self.buttons.addWidget(widget)
        if self.preview is not None:
            self.preview.setVisible(view.show_preview)


class SearchPage(Page):
    """Manual lookup: type a code or a name, pick from the list."""

    query_changed = QtCore.pyqtSignal(str)
    patient_chosen = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super(SearchPage, self).__init__(parent)
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText(strings.LABEL_SEARCH)
        self.search_box.textChanged.connect(self.query_changed.emit)
        self.results = QtWidgets.QListWidget()
        self.results.itemActivated.connect(self._chosen)
        self.results.itemClicked.connect(self._chosen)
        layout = self.layout()
        layout.insertWidget(2, self.search_box)
        layout.insertWidget(3, self.results, 1)

    def _chosen(self, item):
        self.patient_chosen.emit(item.data(QtCore.Qt.UserRole))

    def render(self, view):
        super(SearchPage, self).render(view)
        self.results.clear()
        for code, name in view.fields:
            item = QtWidgets.QListWidgetItem("{}  —  {}".format(code, name))
            item.setData(QtCore.Qt.UserRole, code)
            self.results.addItem(item)


class PinPage(Page):
    """PIN entry with the on-screen number pad."""

    submitted = QtCore.pyqtSignal(str)

    def __init__(self, parent=None, pin_length=6):
        super(PinPage, self).__init__(parent)
        self.pin_length = pin_length
        self._pin = ""
        self.dots = QtWidgets.QLabel("")
        self.dots.setObjectName("title")
        self.dots.setAlignment(QtCore.Qt.AlignCenter)
        pad = NumPad(accept_label=strings.BTN_OK)
        pad.digit_pressed.connect(self._append)
        pad.backspace_pressed.connect(self._backspace)
        pad.accepted.connect(self._submit)
        layout = self.layout()
        layout.insertWidget(2, self.dots)
        layout.insertWidget(3, pad, 1)

    def _redraw(self):
        self.dots.setText("●" * len(self._pin) + "○" * (self.pin_length - len(self._pin)))

    def _append(self, digit):
        if len(self._pin) < self.pin_length:
            self._pin += digit
            self._redraw()
        if len(self._pin) == self.pin_length:
            self._submit()

    def _backspace(self):
        self._pin = self._pin[:-1]
        self._redraw()

    def _submit(self):
        pin, self._pin = self._pin, ""
        self._redraw()
        self.submitted.emit(pin)

    def render(self, view):
        super(PinPage, self).render(view)
        self._redraw()


class EnrollFormPage(Page):
    """The form a nurse fills in before the five shots are taken."""

    submitted = QtCore.pyqtSignal(dict)
    cancelled = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super(EnrollFormPage, self).__init__(parent)
        self.inputs = {}
        form = QtWidgets.QFormLayout()
        form.setVerticalSpacing(16)
        for key, label in (("patient_code", strings.LABEL_CODE),
                           ("full_name", strings.LABEL_NAME),
                           ("birth_year", strings.LABEL_BIRTH_YEAR),
                           ("appointment_code", strings.LABEL_APPOINTMENT)):
            line = QtWidgets.QLineEdit()
            label_widget = QtWidgets.QLabel(label)
            label_widget.setObjectName("fieldLabel")
            form.addRow(label_widget, line)
            self.inputs[key] = line
        container = QtWidgets.QWidget()
        container.setLayout(form)
        self.layout().insertWidget(2, container, 1)

        row = QtWidgets.QHBoxLayout()
        start = QtWidgets.QPushButton(strings.BTN_ENROLL_START)
        start.setObjectName("primary")
        start.clicked.connect(self._submit)
        cancel = QtWidgets.QPushButton(strings.BTN_CANCEL)
        cancel.clicked.connect(self.cancelled.emit)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(start)
        self.layout().insertLayout(3, row)

    def values(self):
        data = {key: widget.text().strip() or None for key, widget in self.inputs.items()}
        if data.get("birth_year"):
            try:
                data["birth_year"] = int(data["birth_year"])
            except ValueError:
                pass
        return data

    def clear(self):
        for widget in self.inputs.values():
            widget.clear()

    def _submit(self):
        self.submitted.emit(self.values())


class KioskWindow(QtWidgets.QMainWindow):
    def __init__(self, controller, cfg, fullscreen=True):
        super(KioskWindow, self).__init__()
        self.controller = controller
        self.cfg = cfg
        self.setWindowTitle(strings.APP_TITLE)
        self.setStyleSheet(load_stylesheet())

        roi = (cfg.get("subject") or {}).get("roi")
        self.stack = QtWidgets.QStackedWidget()
        self.pages = {
            vm.IDLE: Page(),
            vm.GUIDANCE: Page(with_preview=True, roi=roi),
            vm.CANDIDATE: Page(),
            vm.ALERT: Page(),
            vm.ERROR: Page(),
            vm.SEARCH: SearchPage(),
            vm.PIN: PinPage(pin_length=(cfg.get("auth") or {}).get("pin_length", 6)),
            vm.ADMIN: Page(),
            vm.PATIENTS: Page(),
            vm.STATUS: Page(),
            vm.ENROLL: Page(with_preview=True, roi=roi),
        }
        for page in self.pages.values():
            page.button_clicked.connect(self._on_button)
            self.stack.addWidget(page)
        self.enroll_form = EnrollFormPage()
        self.enroll_form.submitted.connect(self._on_enroll_form)
        self.enroll_form.cancelled.connect(self._close_enroll_form)
        self.stack.addWidget(self.enroll_form)

        self.pages[vm.SEARCH].query_changed.connect(self._on_query)
        self.pages[vm.SEARCH].patient_chosen.connect(self._on_patient_chosen)
        self.pages[vm.PIN].submitted.connect(self._on_pin)
        self.setCentralWidget(self.stack)

        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self.refresh)
        self._poll.start(POLL_MS)
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start(PREVIEW_MS)

        # Hidden way into the admin screen: long-press the bottom-left corner.
        self._gesture = QtCore.QTimer(self)
        self._gesture.setSingleShot(True)
        self._gesture.timeout.connect(self._open_admin)

        if fullscreen:
            self.showFullScreen()
            self.setCursor(QtCore.Qt.BlankCursor)
        self.refresh()

    # ------------------------------------------------------------------ events
    def refresh(self):
        self.controller.poll()
        view = self.controller.view()
        page = self.pages.get(view.screen, self.pages[vm.IDLE])
        if view.screen == vm.ADMIN and self.stack.currentWidget() is self.enroll_form:
            return                                   # the nurse is filling in the form
        page.render(view)
        self.stack.setCurrentWidget(page)

    def _refresh_preview(self):
        page = self.stack.currentWidget()
        preview = getattr(page, "preview", None)
        if preview is None or not preview.isVisible():
            return
        preview.show_jpeg(self.controller.preview_bytes())

    def _on_button(self, button):
        if button.kind == "cancel" and self.controller.local_screen == vm.ADMIN:
            self.controller.logout()
        else:
            self.controller.on_button(button)
        self.refresh()

    def _on_query(self, text):
        self.controller.search(text)
        self.pages[vm.SEARCH].render(self.controller.view())

    def _on_patient_chosen(self, code):
        self.controller.choose_patient(code)
        self.refresh()

    def _on_pin(self, pin):
        operators = self.controller.auth.operators()
        if not operators:
            LOG.warning("no operator configured: run scripts/db_admin.py create-operator")
            return
        self.controller.unlock(operators[0]["operator_id"], pin)
        self.refresh()

    def open_enroll_form(self):
        self.enroll_form.clear()
        self.enroll_form.render(vm.View(screen=vm.ENROLL, title=strings.ENROLL_TITLE,
                                        message="", severity=vm.OK))
        self.stack.setCurrentWidget(self.enroll_form)

    def _close_enroll_form(self):
        self.refresh()

    def _on_enroll_form(self, form):
        self.controller.start_enroll(form)
        self.refresh()

    def _open_admin(self):
        self.controller.open_admin_tab(vm.ADMIN)
        self.refresh()

    def mousePressEvent(self, event):
        corner = (event.x() < 120 and event.y() > self.height() - 120)
        if corner:
            self._gesture.start(ADMIN_GESTURE_MS)
        super(KioskWindow, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._gesture.stop()
        super(KioskWindow, self).mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        elif event.key() == QtCore.Qt.Key_F2:      # keyboard shortcut for the admin screen
            self._open_admin()
        else:
            super(KioskWindow, self).keyPressEvent(event)
