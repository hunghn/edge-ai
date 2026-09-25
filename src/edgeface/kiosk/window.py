# -*- coding: utf-8 -*-
"""The kiosk window: one page per screen id, driven entirely by the controller.

This file draws and forwards taps. Every decision about WHAT to draw was already made
in view_model.py and controller.py, which is why there is no logic here beyond layout.
"""
import os
import re

from PyQt5 import QtCore, QtGui, QtWidgets

from edgeface.common.log import get_logger
from edgeface.kiosk import strings, theme, view_model as vm
from edgeface.kiosk.widgets.numpad import NumPad
from edgeface.kiosk.widgets.preview import PreviewWidget

LOG = get_logger("kiosk.window")

STYLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
POLL_MS = 100
PREVIEW_FPS_DEFAULT = 15
ADMIN_GESTURE_MS = 3000       # long-press the corner to reach the admin screen


def load_stylesheet():
    """The stylesheet with its colour placeholders filled in from theme.py."""
    import io

    with io.open(STYLE_PATH, encoding="utf-8") as f:
        qss = theme.apply_tokens(f.read())
    leftover = set(re.findall(r"@[a-z_]+", qss))
    if leftover:
        LOG.warning("stylesheet has unknown colour names: %s", ", ".join(sorted(leftover)))
    return qss


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

        # What is currently on screen. None, not (), so the first render always builds.
        self._fields_shown = None
        self._buttons_shown = None

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

        # Rebuild only what changed. render() runs ten times a second, and a click is a
        # press and a release: replacing the buttons in between means the release lands
        # on a widget that no longer exists and the click is silently lost.
        if view.fields != self._fields_shown:
            self._fields_shown = view.fields
            self._clear_fields()
            for label, value in view.fields:
                label_widget = QtWidgets.QLabel(label)
                label_widget.setObjectName("fieldLabel")
                value_widget = QtWidgets.QLabel(str(value))
                value_widget.setObjectName("fieldValue")
                self.fields.addRow(label_widget, value_widget)

        self.countdown.setText("" if view.countdown_s is None
                               else "Tự huỷ sau {} giây".format(int(view.countdown_s)))

        if view.buttons != self._buttons_shown:
            self._buttons_shown = view.buttons
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
        self._rows_shown = None
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
        # Same hazard as the button row: rebuilding the list on every redraw destroys the
        # row under the nurse's finger before the tap completes.
        if view.fields == self._rows_shown:
            return
        self._rows_shown = view.fields
        self.results.clear()
        for code, name in view.fields:
            item = QtWidgets.QListWidgetItem("{}  —  {}".format(code, name))
            item.setData(QtCore.Qt.UserRole, code)
            self.results.addItem(item)


class PatientListPage(Page):
    """Today's patients, one per row, selectable so that Revoke has a target.

    A QFormLayout cannot be tapped, which is why the admin screen could list patients but
    never act on one.
    """

    patient_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super(PatientListPage, self).__init__(parent)
        self.selected = None
        self._shown = None
        self.rows = QtWidgets.QListWidget()
        self.rows.itemClicked.connect(self._selected)
        self.rows.itemActivated.connect(self._selected)
        self.layout().insertWidget(3, self.rows, 1)

    def _selected(self, item):
        self.selected = item.data(QtCore.Qt.UserRole)
        self.patient_selected.emit(self.selected)

    def render(self, view):
        super(PatientListPage, self).render(view)
        rows = tuple(view.fields)
        # Rebuild only when the list really changed. Clearing it on every refresh would
        # delete the very item Qt is still delivering itemClicked for — which crashes the
        # process the first time a nurse taps a patient — and would drop the highlight
        # ten times a second.
        if rows != self._shown:
            self._shown = rows
            self.rows.clear()
            for code, name in rows:
                item = QtWidgets.QListWidgetItem("{}  —  {}".format(code, name))
                item.setData(QtCore.Qt.UserRole, code)
                self.rows.addItem(item)
        if self.selected not in [code for code, _name in rows]:
            self.selected = None
            self.rows.clearSelection()


class DuplicatePage(Page):
    """The face-already-enrolled warning: one row per similar patient.

    A face and a masked code, never a name. The nurse only has to answer "is this the
    same person", and the picture answers it; the other patient's name would identify
    somebody who is not here and did not agree to appear on this screen.
    """

    THUMB = 96

    def __init__(self, parent=None):
        super(DuplicatePage, self).__init__(parent)
        self.faces = []                 # [jpeg or None], row order, set by the window
        self._shown = None
        self.rows = QtWidgets.QWidget()
        self._rows_layout = QtWidgets.QVBoxLayout(self.rows)
        self._rows_layout.setSpacing(12)
        self.layout().insertWidget(3, self.rows, 1)

    def _row(self, masked_code, score, jpeg):
        line = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(line)
        box.setSpacing(16)

        thumb = QtWidgets.QLabel()
        thumb.setObjectName("duplicateFace")
        thumb.setFixedSize(self.THUMB, self.THUMB)
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        pixmap = QtGui.QPixmap()
        if jpeg and pixmap.loadFromData(jpeg, "JPG"):
            thumb.setPixmap(pixmap.scaled(self.THUMB, self.THUMB, QtCore.Qt.KeepAspectRatio,
                                          QtCore.Qt.SmoothTransformation))
        else:
            # Patients pulled from the server arrive as embeddings only (C-24 covers the
            # kiosk side). An empty frame is honest; a missing row would not be.
            thumb.setText(strings.DUPLICATE_NO_PHOTO)
            thumb.setWordWrap(True)
        box.addWidget(thumb)

        text = QtWidgets.QLabel("{}\n{}\n{}".format(masked_code,
                                                     strings.DUPLICATE_MASKED_NAME,
                                                     score))
        text.setObjectName("fieldValue")
        box.addWidget(text, 1)
        return line

    def render(self, view):
        super(DuplicatePage, self).render(view)
        key = (tuple(view.fields), tuple(f is not None for f in self.faces))
        if key == self._shown:
            return                       # same as last redraw; see the button-rebuild note
        self._shown = key
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, (masked_code, score) in enumerate(view.fields):
            # self.faces is a list in the same order as the rows, with None where a
            # patient has no picture, so row and face always belong together.
            jpeg = self.faces[index] if index < len(self.faces) else None
            self._rows_layout.addWidget(self._row(masked_code, score, jpeg))


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
            vm.CANDIDATE: Page(with_preview=True, roi=roi),
            vm.ALERT: Page(),
            vm.ERROR: Page(),
            vm.SEARCH: SearchPage(),
            vm.PIN: PinPage(pin_length=(cfg.get("auth") or {}).get("pin_length", 6)),
            vm.ADMIN: Page(),
            vm.PATIENTS: PatientListPage(),
            vm.STATUS: Page(),
            vm.CHANGE_PIN: PinPage(pin_length=(cfg.get("auth") or {}).get("pin_length", 6)),
            vm.DUPLICATE: DuplicatePage(),
            vm.ENROLL: Page(with_preview=True, roi=roi),
        }
        for page in self.pages.values():
            page.button_clicked.connect(self._on_button)
            self.stack.addWidget(page)
        self.enroll_form = EnrollFormPage()
        self.enroll_form.submitted.connect(self._on_enroll_form)
        self.enroll_form.cancelled.connect(self._close_enroll_form)
        # Filling in four fields can take longer than the idle lock, and typing is not a
        # button press, so it has to postpone the lock explicitly.
        for line in self.enroll_form.inputs.values():
            line.textEdited.connect(lambda _text: self.controller.touch())
        self.stack.addWidget(self.enroll_form)

        self.pages[vm.SEARCH].query_changed.connect(self._on_query)
        self.pages[vm.SEARCH].patient_chosen.connect(self._on_patient_chosen)
        self.pages[vm.PIN].submitted.connect(self._on_pin)
        self.pages[vm.CHANGE_PIN].submitted.connect(self._on_change_pin)
        self.pages[vm.PATIENTS].patient_selected.connect(self._on_patient_selected)
        self.setCentralWidget(self.stack)

        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self.refresh)
        self._poll.start(POLL_MS)
        # One setting drives both ends: the engine writes at kiosk.preview_fps and the
        # kiosk reads at the same rate. It used to be hardcoded here, so changing the
        # config moved the writer and left the reader behind.
        preview_fps = float((cfg.get("kiosk") or {}).get("preview_fps")
                            or PREVIEW_FPS_DEFAULT)
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start(max(20, int(round(1000.0 / preview_fps))))

        # Hidden way into the admin screen: long-press the bottom-left corner.
        self._gesture = QtCore.QTimer(self)
        self._gesture.setSingleShot(True)
        self._gesture.timeout.connect(self._open_admin)

        if fullscreen:
            self.showFullScreen()
            # A touchscreen has no pointer, so the arrow is hidden by default. Set
            # kiosk.hide_cursor to false when driving the kiosk with a mouse.
            if (cfg.get("kiosk") or {}).get("hide_cursor", True):
                self.setCursor(QtCore.Qt.BlankCursor)
        self.refresh()

    # ------------------------------------------------------------------ events
    def refresh(self):
        self.controller.poll()
        view = self.controller.view()
        page = self.pages.get(view.screen, self.pages[vm.IDLE])
        if view.screen == vm.ADMIN and self.stack.currentWidget() is self.enroll_form:
            return                                   # the nurse is filling in the form
        if view.screen == vm.DUPLICATE:
            page.faces = self.controller.duplicate_faces()
        page.render(view)
        self.stack.setCurrentWidget(page)

    def _refresh_preview(self):
        page = self.stack.currentWidget()
        preview = getattr(page, "preview", None)
        if preview is None or not preview.isVisible():
            return
        if not self.controller.preview_changed():
            return                            # same picture as last tick; nothing to do
        preview.show_jpeg(self.controller.preview_bytes())

    def _on_button(self, button):
        if button.kind == "cancel" and self.controller.local_screen == vm.ADMIN:
            self.controller.logout()
        elif button.kind == "enroll":
            # The only menu entry the controller cannot serve: the form is a widget.
            self.controller.touch()
            self.open_enroll_form()
            return
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

    def _on_change_pin(self, pin):
        self.controller.touch()
        self.controller.submit_change_pin(pin)
        self.refresh()

    def _on_patient_selected(self, code):
        self.controller.select_patient(code)
        self.controller.touch()
        self.refresh()

    def open_enroll_form(self):
        self.enroll_form.clear()
        self.enroll_form.render(vm.View(screen=vm.ENROLL, title=strings.ENROLL_TITLE,
                                        message="", severity=vm.OK))
        self.stack.setCurrentWidget(self.enroll_form)

    def _close_enroll_form(self):
        # refresh() refuses to redraw over the form (so a nurse typing is never
        # interrupted), so leaving it has to move off the form first.
        self.stack.setCurrentWidget(self.pages[vm.ADMIN])
        self.controller.touch()
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
