# -*- coding: utf-8 -*-
"""The kiosk window: one page per screen id, driven entirely by the controller.

This file draws and forwards taps. Every decision about WHAT to draw was already made in
view_model.py and controller.py, which is why there is no logic here beyond layout.

Two rules shape every page. Nothing is rebuilt on a redraw - render() runs ten times a
second, and replacing a widget between a finger going down and coming up loses the tap.
And the screens that show a camera are laid out in two columns, because a nurse compares
the face in front of her with the record beside it, and a patient reads the instruction
that sits on the picture rather than one at the top of the screen.
"""
import io
import os
import re

from PyQt5 import QtCore, QtGui, QtWidgets

from edgeface.common.log import get_logger
from edgeface.kiosk import strings, theme, view_model as vm
from edgeface.kiosk.widgets import components as ui
from edgeface.kiosk.widgets import (icons, keyboard, overlay, rail, ring,
                                    rows as row_widgets, stepper)
from edgeface.kiosk.widgets.numpad import NumPad
from edgeface.kiosk.widgets.preview import PreviewWidget

LOG = get_logger("kiosk.window")

STYLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
POLL_MS = 100
PREVIEW_FPS_DEFAULT = 15
ADMIN_GESTURE_MS = 3000       # long-press the corner to reach the admin screen

# Which button carries the weight of the screen. The View keeps the buttons in the order
# the logic thinks of them; where they land is a question of what the finger should hit
# first, so it is answered here.
DANGER_KINDS = ("reject", "revoke")
TITLE_ICONS = {
    vm.IDLE: "hospital", vm.GUIDANCE: "person", vm.CANDIDATE: "shield_check",
    vm.ALERT: "warning", vm.ERROR: "error", vm.SEARCH: "search", vm.PIN: "lock",
    vm.ADMIN: "tune", vm.PATIENTS: "group", vm.STATUS: "pulse",
    vm.CHANGE_PIN: "key", vm.DUPLICATE: "person_search", vm.ENROLL: "person_add",
}


def load_stylesheet():
    """The stylesheet with its colour placeholders filled in from theme.py."""
    with io.open(STYLE_PATH, encoding="utf-8") as f:
        qss = theme.apply_tokens(f.read())
    leftover = set(re.findall(r"@[a-z_]+", qss))
    if leftover:
        LOG.warning("stylesheet has unknown colour names: %s", ", ".join(sorted(leftover)))
    return qss


class AppBar(QtWidgets.QWidget):
    """Title, one supporting word, and the chips that say how the machine is doing."""

    def __init__(self, parent=None):
        super(AppBar, self).__init__(parent)
        self.setObjectName("appBar")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setFixedHeight(84)
        self._severity = None
        self._chips_shown = None
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(theme.GUTTER, 0, theme.GUTTER, 0)
        row.setSpacing(16)
        self.icon = QtWidgets.QLabel()
        self.icon.setFixedSize(30, 30)
        row.addWidget(self.icon)
        self.title = QtWidgets.QLabel("")
        self.title.setObjectName("appBarTitle")
        row.addWidget(self.title)
        self.subtitle = QtWidgets.QLabel("")
        self.subtitle.setObjectName("appBarSub")
        row.addWidget(self.subtitle)
        row.addStretch(1)
        self.chips = QtWidgets.QHBoxLayout()
        self.chips.setSpacing(10)
        row.addLayout(self.chips)
        self._icon_name = None
        self._widgets = []

    def render(self, title, severity, chips=(), icon_name=None, subtitle=""):
        if self.title.text() != title:
            self.title.setText(title)
        if self.subtitle.text() != subtitle:
            self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))

        # An alarm colours the whole bar, not just the banner: that is what makes it
        # readable from the other side of the room.
        name = {vm.ALARM: "appBarAlarm", vm.ATTENTION: "appBarWarn"}.get(
            severity, "appBar")
        if name != self.objectName():
            self.setObjectName(name)
            self.style().unpolish(self)
            self.style().polish(self)
        if (icon_name, name) != self._icon_name:
            self._icon_name = (icon_name, name)
            accent = {"appBarAlarm": "error", "appBarWarn": "warn"}.get(
                name, "on_surface_var")
            self.icon.setPixmap(icons.pixmap(icon_name or "person", 30,
                                             theme.colour(accent), 2.2))

        chips = tuple(chips)
        if chips == self._chips_shown:
            return
        self._chips_shown = chips
        ui.clear_layout(self.chips)
        for text, tone in chips:
            self.chips.addWidget(ui.Chip(text, tone=_tone(tone)), 0,
                                 QtCore.Qt.AlignVCenter)


def _tone(severity):
    """View severities and chip tones are the same three words plus a neutral."""
    return severity if severity in ("ok", "attention", "alarm", "primary") else "neutral"


class CameraPanel(QtWidgets.QWidget):
    """The preview with the instruction written on it.

    The guidance line belongs here rather than at the top of the screen: the patient is
    looking at the camera, which is behind the picture of their own face.
    """

    def __init__(self, roi=None, parent=None):
        super(CameraPanel, self).__init__(parent)
        self.setObjectName("cameraPanel")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.preview = PreviewWidget(roi=roi)
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview, 0, 0)

        self.left_tag = QtWidgets.QLabel("")
        self.left_tag.setObjectName("camTag")
        layout.addWidget(self.left_tag, 0, 0,
                         QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self.right_tag = QtWidgets.QLabel("")
        self.right_tag.setObjectName("camTag")
        layout.addWidget(self.right_tag, 0, 0,
                         QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
        self.cue = QtWidgets.QLabel("")
        self.cue.setObjectName("cue")
        self.cue.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.cue, 0, 0,
                         QtCore.Qt.AlignBottom | QtCore.Qt.AlignHCenter)
        layout.setContentsMargins(14, 14, 14, 18)

    def render(self, cue="", tags=()):
        if self.cue.text() != cue:
            self.cue.setText(cue)
        self.cue.setVisible(bool(cue))
        left, right = (tags + ("", ""))[:2] if tags else ("", "")
        for label, text in ((self.left_tag, left), (self.right_tag, right)):
            if label.text() != text:
                label.setText(text)
            label.setVisible(bool(text))


class ActionBar(QtWidgets.QWidget):
    """The row a decision is made on: quiet ways out on the left, the answer on the right."""

    button_clicked = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super(ActionBar, self).__init__(parent)
        self._shown = None
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(theme.GUTTER, 18, theme.GUTTER, 18)
        row.setSpacing(14)
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("body")
        row.addWidget(self.note)
        row.addStretch(1)
        self.ring = ring.CountdownRing()
        self.ring.setVisible(False)
        row.addWidget(self.ring)
        self.buttons = QtWidgets.QHBoxLayout()
        self.buttons.setSpacing(14)
        row.addLayout(self.buttons)

    def render(self, buttons, note=""):
        if self.note.text() != note:
            self.note.setText(note)
        self.note.setVisible(bool(note))
        key = tuple((b.kind, b.label, b.primary) for b in buttons)
        if key == self._shown:
            return
        self._shown = key
        ui.clear_layout(self.buttons)
        # Text buttons first, then the one that says no, then the one that says yes.
        ordered = ([b for b in buttons if not b.primary and b.kind not in DANGER_KINDS]
                   + [b for b in buttons if b.kind in DANGER_KINDS]
                   + [b for b in buttons if b.primary])
        for button in ordered:
            self.buttons.addWidget(self._button(button))

    def _button(self, button):
        widget = QtWidgets.QPushButton(button.label)
        if button.primary:
            widget.setObjectName("primary")
        elif button.kind in DANGER_KINDS:
            widget.setObjectName("danger")
        else:
            widget.setObjectName("text")
        widget.clicked.connect(
            lambda _checked=False, b=button: self.button_clicked.emit(b))
        return widget


class Page(QtWidgets.QWidget):
    """App bar, a body the subclass fills, and the action row."""

    button_clicked = QtCore.pyqtSignal(object)

    def __init__(self, parent=None, with_preview=False, roi=None, cfg=None, screen=None):
        super(Page, self).__init__(parent)
        self.cfg = cfg or {}
        self.screen_id = screen
        self._fields_shown = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.bar = AppBar()
        root.addWidget(self.bar)

        self.middle = QtWidgets.QHBoxLayout()
        self.middle.setContentsMargins(0, 0, 0, 0)
        self.middle.setSpacing(0)
        root.addLayout(self.middle, 1)

        self.content = QtWidgets.QVBoxLayout()
        self.content.setContentsMargins(theme.GUTTER, 24, theme.GUTTER, 10)
        self.content.setSpacing(18)
        self.middle.addLayout(self.content, 1)

        self.banner = ui.Banner()
        self.content.addWidget(self.banner)

        self.camera = CameraPanel(roi=roi) if with_preview else None
        self.preview = self.camera.preview if self.camera else None

        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(18)
        self.content.addLayout(self.body, 1)

        self.fields = QtWidgets.QFormLayout()
        self.fields.setHorizontalSpacing(32)
        self.fields.setVerticalSpacing(12)
        self.content.addLayout(self.fields)

        self.actions = ActionBar()
        self.actions.button_clicked.connect(self._on_action)
        root.addWidget(self.actions)
        self.extras = {}                      # what the window hands over before a render
        self.build()

    def _on_action(self, button):
        """Every tap on the action row passes through here, so a page can intercept one."""
        self.button_clicked.emit(button)

    # Subclasses put their own widgets in self.body here.
    def build(self):
        pass

    def timeout_total(self):
        return (self.cfg.get("session") or {}).get("await_nurse_timeout_s", 30)

    def render(self, view):
        self.bar.render(view.title or "", view.severity, view.chips,
                        TITLE_ICONS.get(view.screen, "person"))
        self.banner.render(view.message or "", view.severity)
        self.render_fields(view)
        self.actions.ring.render(view.countdown_s, self.timeout_total())
        self.actions.render(view.buttons, self.action_note(view))
        if self.camera is not None:
            self.camera.setVisible(view.show_preview)
        self.render_body(view)

    def action_note(self, _view):
        return ""

    def render_body(self, view):
        pass

    def render_fields(self, view):
        """Generic label/value rows, for the screens that are a list of facts."""
        if view.fields == self._fields_shown:
            return
        self._fields_shown = view.fields
        ui.clear_layout(self.fields)
        for label, value in view.fields:
            left = QtWidgets.QLabel(label)
            left.setObjectName("fieldLabel")
            right = QtWidgets.QLabel(str(value))
            right.setObjectName("fieldValue")
            self.fields.addRow(left, right)


class IdlePage(Page):
    """Nothing to do, and it should look like an invitation rather than a blank screen."""

    def build(self):
        self.body.addStretch(1)
        circle = QtWidgets.QLabel()
        circle.setObjectName("avatarPrimary")
        circle.setFixedSize(150, 150)
        circle.setAlignment(QtCore.Qt.AlignCenter)
        circle.setPixmap(icons.pixmap("face", 92, theme.colour("on_primary_container"),
                                      2.4))
        circle.setStyleSheet("background: %s; border-radius: 75px;"
                             % theme.colour("primary_container"))
        self.body.addWidget(circle, 0, QtCore.Qt.AlignHCenter)
        self.headline = ui.label("", "display")
        self.headline.setAlignment(QtCore.Qt.AlignCenter)
        self.body.addWidget(self.headline)
        self.lead = ui.label(strings.IDLE_LEAD, "message", wrap=True)
        self.lead.setAlignment(QtCore.Qt.AlignCenter)
        self.body.addWidget(ui.measured(self.lead, 760), 0, QtCore.Qt.AlignHCenter)
        hints = ui.row(None, ui.Chip(strings.IDLE_CHIP_MASK, "face"),
                       ui.Chip(strings.IDLE_CHIP_LOOK, "eye"), None)
        self.body.addLayout(hints)
        self.body.addStretch(1)

    def render_body(self, view):
        if self.headline.text() != (view.title or ""):
            self.headline.setText(view.title or "")
        # The banner would repeat the lead line word for word on this screen.
        self.banner.setVisible(False)

    def action_note(self, _view):
        return strings.IDLE_FOOT


class GuidancePage(Page):
    """Camera on the left, what the pipeline is doing on the right."""

    def build(self):
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(24)
        split.addWidget(self.camera, 17)

        side = QtWidgets.QVBoxLayout()
        side.setSpacing(18)
        self.steps = stepper.VStepper(strings.STEP_LABELS)
        side.addWidget(self.steps)

        self.progress_card = ui.Card()
        head = ui.row(ui.SectionLabel(strings.COLLECTING_LABEL), None)
        self.progress_value = ui.label("", "fieldValue")
        head.addWidget(self.progress_value)
        self.progress_card.add_layout(head)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setObjectName("progress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_card.add(self.progress_bar)
        self.progress_card.add(ui.label(strings.HOLD_A_MOMENT, "body", wrap=True))
        side.addWidget(self.progress_card)
        side.addStretch(1)
        split.addLayout(side, 10)
        self.body.addLayout(split, 1)

    def render_body(self, view):
        self.banner.setVisible(False)          # the instruction lives on the picture
        self.camera.render(view.message or "", view.camera)
        self.steps.render(view.steps or vm.steps_for(None, {}))
        taken, wanted = view.progress or (None, None)
        self.progress_card.setVisible(view.progress is not None)
        if view.progress is None:
            return
        text = u"{} / {}".format(taken, wanted)
        if self.progress_value.text() != text:
            self.progress_value.setText(text)
        self.progress_bar.setMaximum(max(1, wanted))
        self.progress_bar.setValue(taken)


class CandidatePage(Page):
    """The frame that was chosen, beside the record it was matched to."""

    def build(self):
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(24)
        split.addWidget(self.camera, 10)

        side = QtWidgets.QVBoxLayout()
        side.setSpacing(16)
        self.identity = ui.Card()
        self.avatar = ui.Avatar("")
        self.name = ui.label("", "headline")
        self.code = ui.label("", "mono")
        who = QtWidgets.QVBoxLayout()
        who.setSpacing(2)
        who.addWidget(self.name)
        who.addWidget(self.code)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(self.avatar, 0, QtCore.Qt.AlignTop)
        head.addLayout(who, 1)
        self.identity.add_layout(head)
        self.confidence = ui.Chip("", "shield_check", "ok")
        self.appointment = ui.Chip("", "calendar")
        self.identity.add_layout(ui.row(self.confidence, self.appointment, None))
        side.addWidget(self.identity)

        self.detail = ui.Card(outlined=True)
        self.detail.add(ui.SectionLabel(strings.SCORE_DETAIL))
        self.detail_row = QtWidgets.QHBoxLayout()
        self.detail_row.setSpacing(26)
        self.detail.add_layout(self.detail_row)
        self._detail_shown = None
        side.addWidget(self.detail)
        side.addStretch(1)
        split.addLayout(side, 13)
        self.body.addLayout(split, 1)

    # The card is built from the same (label, value) rows the tests read, so there is
    # one description of a candidate rather than two that can disagree.
    IDENTITY_LABELS = (strings.LABEL_CODE, strings.LABEL_NAME, strings.LABEL_BIRTH_YEAR,
                       strings.LABEL_APPOINTMENT, strings.LABEL_CONFIDENCE)

    def render_fields(self, view):
        if view.fields == self._fields_shown:
            return
        self._fields_shown = view.fields
        rows = dict(view.fields)
        name = rows.get(strings.LABEL_NAME, "")
        self.name.setText(name or rows.get(strings.LABEL_CODE, ""))
        self.avatar.set_name(name)
        code = rows.get(strings.LABEL_CODE, "")
        year = rows.get(strings.LABEL_BIRTH_YEAR)
        self.code.setText(u"{} · sinh {}".format(code, year) if year else code)
        confidence = rows.get(strings.LABEL_CONFIDENCE, "")
        self.confidence.set_text(confidence)
        self.confidence.set_tone("ok" if confidence == strings.CONFIDENCE_HIGH
                                 else "attention")
        appointment = rows.get(strings.LABEL_APPOINTMENT)
        self.appointment.setVisible(bool(appointment))
        if appointment:
            self.appointment.set_text(u"Lịch {}".format(appointment))

        # Everything the nurse does not need in order to answer "is this them" goes in
        # the quiet card underneath, and disappears with kiosk.show_score.
        detail = [(strings.LABEL_SCORE, rows.get(strings.LABEL_SCORE)),
                  (strings.LABEL_MARGIN_SHORT, rows.get(strings.LABEL_MARGIN)),
                  (strings.LABEL_LOOKALIKE_SHORT, rows.get(strings.LABEL_LOOKALIKE))]
        detail = [(label, value) for label, value in detail if value is not None]
        self.detail.setVisible(bool(detail))
        if detail == self._detail_shown:
            return
        self._detail_shown = detail
        ui.clear_layout(self.detail_row)
        for label, value in detail:
            column = QtWidgets.QWidget()
            box = QtWidgets.QVBoxLayout(column)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            box.addWidget(ui.label(label, "fieldLabel"))
            box.addWidget(ui.label(str(value), "mono"))
            self.detail_row.addWidget(column)
        self.detail_row.addStretch(1)

    def render_body(self, view):
        self.camera.render("", view.camera)


class AlertPage(Page):
    """Spoof, poor quality, nobody found: three reasons, one screen.

    The patient's name is never on it. A spoof alert is about the person standing there,
    not about the record the system nearly picked.
    """

    def build(self):
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(24)
        split.addWidget(self.camera, 10)

        side = QtWidgets.QVBoxLayout()
        side.setSpacing(16)
        self.headline = ui.label("", "headline", wrap=True)
        side.addWidget(self.headline)

        self.todo = ui.Card(outlined=True)
        self.todo.add(ui.SectionLabel(strings.SPOOF_TODO))
        for line in strings.SPOOF_STEPS:
            self.todo.add(ui.label(line, "body", wrap=True))
        side.addWidget(self.todo)

        self.metrics = ui.Card(outlined=True)
        self.metrics.add(ui.SectionLabel(strings.REJECTED_BECAUSE))
        self.metric_rows = QtWidgets.QVBoxLayout()
        self.metric_rows.setSpacing(10)
        self.metrics.add_layout(self.metric_rows)
        self._metrics_shown = None
        side.addWidget(self.metrics)

        self.evidence = ui.Chip("", "folder")
        side.addWidget(self.evidence, 0, QtCore.Qt.AlignLeft)
        side.addStretch(1)
        split.addLayout(side, 13)
        self.body.addLayout(split, 1)

    def action_note(self, view):
        return strings.SPOOF_NO_DETAILS if view.severity == vm.ALARM else ""

    def render_body(self, view):
        spoof = view.severity == vm.ALARM
        self.headline.setText(strings.SPOOF_HEADLINE if spoof else "")
        self.headline.setVisible(spoof)
        self.todo.setVisible(spoof)
        self.evidence.setVisible(spoof)
        if spoof:
            self.evidence.set_text(strings.SPOOF_EVIDENCE)
        self.camera.render("", ())
        self.metrics.setVisible(bool(view.metrics))
        if view.metrics == self._metrics_shown:
            return
        self._metrics_shown = view.metrics
        ui.clear_layout(self.metric_rows)
        for label, value, tone in view.metrics or ():
            left = ui.label(label, "body")
            right = ui.label(str(value), "mono")
            colour = theme.colour("ok" if tone == vm.OK else "warn")
            right.setStyleSheet("color: %s;" % colour)
            self.metric_rows.addLayout(ui.row(left, None, right))


class ErrorPage(Page):
    """The machine is not working, and the person in front of it needs a way forward."""

    def build(self):
        self.body.addStretch(1)
        glyph = QtWidgets.QLabel()
        glyph.setPixmap(icons.pixmap("signal_off", 96, theme.colour("error"), 2.6))
        self.body.addWidget(glyph, 0, QtCore.Qt.AlignHCenter)
        self.headline = ui.label(strings.ERROR_HEADLINE, "display")
        self.headline.setAlignment(QtCore.Qt.AlignCenter)
        self.body.addWidget(self.headline)
        self.lead = ui.label("", "message", wrap=True)
        self.lead.setAlignment(QtCore.Qt.AlignCenter)
        self.body.addWidget(ui.measured(self.lead, 780), 0, QtCore.Qt.AlignHCenter)

        self.support = ui.Card(outlined=True)
        self.support_label = ui.SectionLabel("")
        self.support_label.setAlignment(QtCore.Qt.AlignCenter)
        self.support.add(self.support_label)
        self.support_number = ui.label("", "display")
        self.support_number.setAlignment(QtCore.Qt.AlignCenter)
        self.support.add(self.support_number)
        self.support.setMaximumWidth(560)
        self.body.addWidget(self.support, 0, QtCore.Qt.AlignHCenter)
        self.body.addStretch(1)

    def action_note(self, _view):
        return strings.ERROR_NO_DATA

    def render_body(self, view):
        self.banner.setVisible(False)
        self.lead.setText(strings.ERROR_LEAD if view.message == strings.STATUS_ENGINE_DOWN
                          else view.message or "")
        # No number in the config means no way to call anyone, and a card promising help
        # that cannot be asked for is worse than no card.
        number = (self.cfg.get("kiosk") or {}).get("support_phone")
        self.support.setVisible(bool(number))
        if number:
            device = (self.cfg.get("kiosk") or {}).get("device_name", "KIOSK")
            self.support_label.setText(
                strings.SUPPORT_CALL.format(code=u"{}".format(device)))
            self.support_number.setText(str(number))


class SearchPage(Page):
    """Manual lookup: type a code or a name, pick from the list."""

    query_changed = QtCore.pyqtSignal(str)
    patient_chosen = QtCore.pyqtSignal(str)

    def build(self):
        self._rows_shown = None
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(0)
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText(strings.LABEL_SEARCH)
        self.search_box.textChanged.connect(self.query_changed.emit)
        box.addWidget(self.search_box)
        self.body.addLayout(box)

        self.results = QtWidgets.QListWidget()
        row_widgets.apply(self.results)
        self.results.itemActivated.connect(self._chosen)
        self.results.itemClicked.connect(self._chosen)
        self.body.addWidget(self.results, 1)

        self.keyboard = keyboard.SoftKeyboard()
        self.keyboard.attach(self.search_box)
        self.body.addWidget(self.keyboard)

    def _chosen(self, item):
        self.patient_chosen.emit(item.data(QtCore.Qt.UserRole))

    def render_fields(self, view):
        if view.fields == self._rows_shown:
            return
        self._rows_shown = view.fields
        row_widgets.fill(self.results, [
            {"code": code, "name": name, "sub": code} for code, name in view.fields])

    def render_body(self, view):
        self.banner.setVisible(False)          # the placeholder already says this


class RailPage(Page):
    """An admin screen: the four destinations stay on screen while one is being used.

    The first version made each job end by walking back to a menu, so a nurse who wanted
    to register a patient and then check the sync had to go up and down twice.
    """

    RAIL = (("enroll", strings.BTN_MENU_ENROLL, "person_add"),
            ("patients", strings.BTN_MENU_PATIENTS, "group"),
            ("status", strings.BTN_MENU_STATUS, "pulse"),
            ("change_pin", strings.BTN_CHANGE_PIN, "key"))
    RAIL_LABELS = {"enroll": u"Đăng ký", "patients": u"BN hôm nay",
                   "status": u"Trạng thái", "change_pin": u"Đổi PIN"}
    ACTIVE = None

    def __init__(self, parent=None, cfg=None, screen=None, **kwargs):
        super(RailPage, self).__init__(parent, cfg=cfg, screen=screen, **kwargs)
        items = [(key, self.RAIL_LABELS[key], icon) for key, _label, icon in self.RAIL]
        self.rail = rail.NavRail(items, footer=("logout", u"Thoát", "logout"))
        self.rail.selected.connect(self._rail_tapped)
        self.rail.render(self.ACTIVE)
        self.middle.insertWidget(0, self.rail)

    def _rail_tapped(self, key):
        labels = dict((k, label) for k, label, _icon in self.RAIL)
        self.button_clicked.emit(
            vm.Button(key, labels.get(key, strings.BTN_LOGOUT), None))


class AdminPage(RailPage):
    """The landing screen: four cards, each already carrying its own number."""

    ACTIVE = None
    CARDS = (("enroll", strings.BTN_MENU_ENROLL, "person_add", True),
             ("patients", strings.BTN_MENU_PATIENTS, "group", False),
             ("status", strings.BTN_MENU_STATUS, "pulse", False),
             ("change_pin", strings.BTN_CHANGE_PIN, "key", False))

    def build(self):
        self.cards = {}
        self.captions = {}
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(16)
        for index, (kind, label, icon_name, primary) in enumerate(self.CARDS):
            holder = ui.Card()
            button = QtWidgets.QPushButton(label)
            button.setObjectName("tonal" if primary else "")
            button.setIcon(icons.icon(icon_name, 30,
                                      theme.colour("on_primary_container" if primary
                                                   else "on_surface_var")))
            button.setIconSize(QtCore.QSize(30, 30))
            button.setMinimumHeight(88)
            button.clicked.connect(
                lambda _c=False, k=kind, t=label: self.button_clicked.emit(
                    vm.Button(k, t, None)))
            caption = ui.label("", "body", wrap=True)
            holder.add(button)
            holder.add(caption)
            grid.addWidget(holder, index // 2, index % 2)
            self.cards[kind] = button
            self.captions[kind] = caption
        self.body.addLayout(grid)
        self.body.addStretch(1)

    def render(self, view):
        # The cards are the menu. Leaving the same four entries in the action row as
        # well would put two buttons with one label on the screen, and a tap would land
        # on whichever of them Qt happened to find first.
        menu = tuple(b for b in view.buttons if b.kind in self.captions)
        super(AdminPage, self).render(
            view._replace(buttons=tuple(b for b in view.buttons if b not in menu)))

    def render_body(self, view):
        for kind, caption in self.captions.items():
            text = self.extras.get(kind, "")
            if caption.text() != text:
                caption.setText(text)


class PatientListPage(RailPage):
    """Today's patients, one per row, selectable so that Revoke has a target."""

    patient_selected = QtCore.pyqtSignal(str)
    ACTIVE = "patients"

    def build(self):
        self.selected = None
        self._shown = None
        self.rows = QtWidgets.QListWidget()
        row_widgets.apply(self.rows, self._revoke_tapped)
        self.rows.itemClicked.connect(self._selected)
        self.rows.itemActivated.connect(self._selected)
        self.body.addWidget(self.rows, 1)
        self.dialog = overlay.ConfirmDialog(self)
        self.dialog.confirmed.connect(self._confirmed)
        self._pending = None

    def _selected(self, item):
        self.selected = item.data(QtCore.Qt.UserRole)
        self.patient_selected.emit(self.selected)

    def _revoke_tapped(self, code):
        """The bin on a row asks about that row, whichever row is highlighted."""
        self.selected = code
        self.patient_selected.emit(code)
        self._ask(code)

    def _on_action(self, button):
        if button.kind == "revoke" and self.selected:
            self._ask(self.selected)
            return
        self.button_clicked.emit(button)

    def _ask(self, code):
        name = dict(self._shown or {}).get(code, code)
        self._pending = vm.Button("revoke", strings.BTN_REVOKE, None)
        self.dialog.ask(strings.REVOKE_TITLE.format(code=code),
                        strings.REVOKE_BODY.format(name=name),
                        strings.BTN_REVOKE_CONFIRM, strings.BTN_CANCEL)

    def _confirmed(self):
        if self._pending is not None:
            self.button_clicked.emit(self._pending)
            self._pending = None

    def resizeEvent(self, event):
        super(PatientListPage, self).resizeEvent(event)
        self.dialog.follow()

    def render_fields(self, view):
        rows = tuple(view.fields)
        if rows != self._shown:
            self._shown = rows
            row_widgets.fill(self.rows, [
                dict({"code": code, "name": name}, **self.extras.get(code, {}))
                for code, name in rows])
        if self.selected not in [code for code, _name in rows]:
            self.selected = None
            self.rows.clearSelection()


class StatusPage(RailPage):
    """Six numbers and the word that says whether each one is good news."""

    ACTIVE = "status"
    COLUMNS = 3

    def build(self):
        self._shown = None
        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(14)
        self.tiles = []
        self.body.addLayout(self.grid)
        self.device = ui.Card(outlined=True)
        self.device.add(ui.SectionLabel(u"Thiết bị"))
        self.device_line = ui.label("", "mono", wrap=True)
        self.device.add(self.device_line)
        self.body.addWidget(self.device)
        self.body.addStretch(1)

    def render_fields(self, view):
        """The tiles are the status rows; the richer version comes from `extras`."""
        tiles = self.extras.get("tiles") or tuple(
            (label, value, "", None) for label, value in view.fields)
        while len(self.tiles) < len(tiles):
            tile = ui.MetricTile()
            self.grid.addWidget(tile, len(self.tiles) // self.COLUMNS,
                                len(self.tiles) % self.COLUMNS)
            self.tiles.append(tile)
        for index, tile in enumerate(self.tiles):
            visible = index < len(tiles)
            tile.setVisible(visible)
            if visible:
                label, value, foot, tone = tiles[index]
                tile.render(label, value, foot, tone)

    def render_body(self, view):
        line = self.extras.get("device_line", "")
        if self.device_line.text() != line:
            self.device_line.setText(line)
        self.device.setVisible(bool(line))


class ChangePinPage(RailPage):
    """Old, new, then new again, with the three steps drawn along the top."""

    ACTIVE = "change_pin"
    submitted = QtCore.pyqtSignal(str)
    STEPS = (u"Hiện tại", u"Mới", u"Nhập lại")

    def __init__(self, parent=None, pin_length=6, cfg=None, screen=None):
        self.pin_length = pin_length
        super(ChangePinPage, self).__init__(parent, cfg=cfg, screen=screen)

    def build(self):
        self._pin = ""
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(40)
        side = QtWidgets.QVBoxLayout()
        side.setSpacing(20)
        side.addStretch(1)
        self.steps = stepper.HStepper(self.STEPS)
        side.addWidget(self.steps)
        self.prompt = ui.label("", "headline", wrap=True)
        side.addWidget(self.prompt)
        self.dots = QtWidgets.QLabel("")
        self.dots.setObjectName("title")
        side.addWidget(self.dots)
        side.addStretch(1)
        split.addLayout(side, 1)

        pad = NumPad(accept_label=strings.BTN_OK)
        pad.digit_pressed.connect(self._append)
        pad.backspace_pressed.connect(self._backspace)
        pad.accepted.connect(self._submit)
        split.addWidget(pad)
        self.body.addLayout(split, 1)

    def _redraw(self):
        self.dots.setText(u"●" * len(self._pin)
                          + u"○" * (self.pin_length - len(self._pin)))

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

    def render_body(self, view):
        step = {strings.CHANGE_PIN_OLD: 0, strings.CHANGE_PIN_NEW: 1,
                strings.CHANGE_PIN_REPEAT: 2}.get(view.message)
        if step is not None:
            self.steps.render(step)
        wrong = view.severity != vm.OK
        self.prompt.setText("" if wrong else (view.message or ""))
        self.prompt.setVisible(not wrong)
        self.banner.setVisible(wrong)
        self._redraw()


class EnrollPage(Page):
    """Taking the five shots, and then signing them off.

    One page for both: the nurse is watching the patient rather than the screen, and a
    page that changes under them mid-capture is one more thing to re-read.
    """

    def build(self):
        self.steps = stepper.HStepper(strings.ENROLL_STEPS)
        self.body.addWidget(self.steps)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(24)
        split.addWidget(self.camera, 14)

        side = QtWidgets.QVBoxLayout()
        side.setSpacing(16)
        self.shots_card = ui.Card()
        self.shot_count = ui.label("", "fieldValue")
        self.shots_card.add_layout(ui.row(ui.SectionLabel(strings.ENROLL_SHOTS), None,
                                          self.shot_count))
        self.shots_row = QtWidgets.QHBoxLayout()
        self.shots_row.setSpacing(12)
        self.shots = []
        for _ in range(5):
            slot = QtWidgets.QLabel()
            slot.setObjectName("shotEmpty")
            slot.setFixedSize(76, 92)
            slot.setAlignment(QtCore.Qt.AlignCenter)
            self.shots_row.addWidget(slot)
            self.shots.append(slot)
        self.shots_row.addStretch(1)
        self.shots_card.add_layout(self.shots_row)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.shots_card.add(self.progress_bar)
        side.addWidget(self.shots_card)

        self.summary = ui.Card(outlined=True)
        self.summary_rows = QtWidgets.QVBoxLayout()
        self.summary_rows.setSpacing(10)
        self.summary.add_layout(self.summary_rows)
        self._summary_shown = None
        side.addWidget(self.summary)
        side.addStretch(1)
        split.addLayout(side, 11)
        self.body.addLayout(split, 1)
        self._filled = -1

    def action_note(self, view):
        return strings.ENROLL_NOT_STORED if view.show_preview else ""

    def render_fields(self, view):
        """The count belongs beside the slots it counts, not in a table of its own."""
        text = dict(view.fields).get("", "")
        if self.shot_count.text() != text:
            self.shot_count.setText(text)

    def render_body(self, view):
        self.steps.render(view.step if view.step is not None else 1)
        self.camera.render(view.message if view.show_preview else "", view.camera)
        self.banner.setVisible(bool(view.message) and not view.show_preview)

        taken, wanted = view.progress or (0, 5)
        self.progress_bar.setMaximum(max(1, wanted))
        self.progress_bar.setValue(taken)
        if taken != self._filled:
            self._filled = taken
            for index, slot in enumerate(self.shots):
                slot.setVisible(index < max(wanted, 1))
                done = index < taken
                name = "shotFilled" if done else "shotEmpty"
                if slot.objectName() != name:
                    slot.setObjectName(name)
                    slot.style().unpolish(slot)
                    slot.style().polish(slot)
                slot.setPixmap(icons.pixmap("face", 40,
                                            theme.colour("on_surface_var" if done
                                                         else "outline_var")))

        if view.metrics == self._summary_shown:
            return
        self._summary_shown = view.metrics
        ui.clear_layout(self.summary_rows)
        self.summary.setVisible(bool(view.metrics))
        for label, value, _tone in view.metrics or ():
            self.summary_rows.addLayout(
                ui.row(ui.label(label, "body"), None, ui.label(str(value), "mono")))


class DuplicatePage(Page):
    """The face-already-enrolled warning: one row per similar patient.

    A face and a masked code, never a name. The nurse only has to answer "is this the
    same person", and the picture answers it; the other patient's name would identify
    somebody who is not here and did not agree to appear on this screen.
    """

    THUMB = 260

    def build(self):
        self.faces = []                 # [jpeg or None], row order, set by the window
        self._shown = None
        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(20)

        # The face the nurse is comparing against is the one in front of the camera, and
        # the engine keeps writing the preview while the review screen is up. Nothing has
        # to be stored for this column to exist.
        mine = ui.Card()
        mine.add(ui.SectionLabel(strings.DUPLICATE_NEW))
        mine.add(self.camera, 1)
        mine.add_layout(ui.row(None, ui.Chip(strings.DUPLICATE_NEW_TAG, tone="primary"),
                               None))
        columns.addWidget(mine, 1)

        self.rows = QtWidgets.QWidget()
        self._rows_layout = QtWidgets.QHBoxLayout(self.rows)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(20)
        columns.addWidget(self.rows, 2)
        self.body.addLayout(columns, 1)

    def _row(self, masked_code, score, jpeg, title):
        """One candidate: the picture, then a masked code and a score. Never a name."""
        card = ui.Card()
        card.add(ui.SectionLabel(title))

        thumb = QtWidgets.QLabel()
        thumb.setObjectName("duplicateFace")
        thumb.setMinimumSize(self.THUMB, self.THUMB)
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        pixmap = QtGui.QPixmap()
        if jpeg and pixmap.loadFromData(jpeg, "JPG"):
            thumb.setPixmap(pixmap.scaled(self.THUMB, self.THUMB,
                                          QtCore.Qt.KeepAspectRatio,
                                          QtCore.Qt.SmoothTransformation))
        else:
            # Patients pulled from the server arrive as embeddings only (C-24 covers the
            # kiosk side). An empty frame is honest; a missing row would not be.
            thumb.setText(strings.DUPLICATE_NO_PHOTO)
            thumb.setWordWrap(True)
        card.add(thumb, 1)
        card.add_layout(ui.row(ui.Chip(masked_code), ui.Chip(score, tone="attention"),
                               ui.Chip(strings.DUPLICATE_MASKED_NAME), None))
        return card

    def render_body(self, view):
        self.camera.render("", ())

    def render_fields(self, view):
        key = (tuple(view.fields), tuple(f is not None for f in self.faces))
        if key == self._shown:
            return                       # same as last redraw; see the button-rebuild note
        self._shown = key
        ui.clear_layout(self._rows_layout)
        titles = (strings.DUPLICATE_NEAREST, strings.DUPLICATE_SECOND)
        for index, (masked_code, score) in enumerate(view.fields):
            # self.faces is a list in the same order as the rows, with None where a
            # patient has no picture, so row and face always belong together.
            jpeg = self.faces[index] if index < len(self.faces) else None
            title = titles[index] if index < len(titles) else strings.DUPLICATE_SECOND
            self._rows_layout.addWidget(self._row(masked_code, score, jpeg, title))


class PinPage(Page):
    """PIN entry with the on-screen number pad."""

    submitted = QtCore.pyqtSignal(str)

    def __init__(self, parent=None, pin_length=6, cfg=None, screen=None):
        self.pin_length = pin_length
        super(PinPage, self).__init__(parent, cfg=cfg, screen=screen)

    def build(self):
        self._pin = ""
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(48)
        split.addStretch(1)

        side = QtWidgets.QVBoxLayout()
        side.setSpacing(22)
        side.addStretch(1)
        self.prompt = ui.label("", "headline", wrap=True)
        side.addWidget(self.prompt)
        self.dots = QtWidgets.QLabel("")
        self.dots.setObjectName("title")
        side.addWidget(self.dots)
        side.addStretch(1)
        split.addLayout(side)

        pad = NumPad(accept_label=strings.BTN_OK)
        pad.digit_pressed.connect(self._append)
        pad.backspace_pressed.connect(self._backspace)
        pad.accepted.connect(self._submit)
        split.addWidget(pad)
        split.addStretch(1)
        self.body.addLayout(split, 1)

    def _redraw(self):
        self.dots.setText(u"●" * len(self._pin)
                          + u"○" * (self.pin_length - len(self._pin)))

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

    def render_body(self, view):
        # The prompt is the message; the banner only appears when something went wrong.
        wrong = view.severity != vm.OK
        self.prompt.setText("" if wrong else (view.message or ""))
        self.prompt.setVisible(not wrong)
        self.banner.setVisible(wrong)
        self._redraw()


class EnrollFormPage(Page):
    """The form a nurse fills in before the five shots are taken."""

    submitted = QtCore.pyqtSignal(dict)
    cancelled = QtCore.pyqtSignal()

    FIELDS = (("patient_code", strings.LABEL_CODE, True),
              ("full_name", strings.LABEL_NAME, True),
              ("birth_year", strings.LABEL_BIRTH_YEAR, False),
              ("appointment_code", strings.LABEL_APPOINTMENT, False))

    def build(self):
        self.inputs = {}
        self.steps = stepper.HStepper(strings.ENROLL_STEPS)
        self.steps.render(0)
        self.body.addWidget(self.steps)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)
        for index, (key, label, required) in enumerate(self.FIELDS):
            column = QtWidgets.QVBoxLayout()
            column.setSpacing(4)
            caption = ui.label(label + (" *" if required else ""), "fieldLabel")
            line = QtWidgets.QLineEdit()
            column.addWidget(caption)
            column.addWidget(line)
            grid.addLayout(column, index // 2, index % 2)
            self.inputs[key] = line
        self.body.addLayout(grid)
        self.body.addStretch(1)

        self.keyboard = keyboard.SoftKeyboard()
        self.keyboard.attach(*[self.inputs[key] for key, _l, _r in self.FIELDS])
        self.body.addWidget(self.keyboard)

        start = QtWidgets.QPushButton(strings.BTN_ENROLL_START)
        start.setObjectName("primary")
        start.clicked.connect(self._submit)
        cancel = QtWidgets.QPushButton(strings.BTN_CANCEL)
        cancel.setObjectName("text")
        cancel.clicked.connect(self.cancelled.emit)
        self.actions.buttons.addWidget(cancel)
        self.actions.buttons.addWidget(start)

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
        """Check the form here rather than letting the engine bounce it back.

        A missing code used to travel to the engine, come back as ENROLL_ERROR and be
        reported on the next screen, by which time the nurse has already turned to the
        patient and the form they have to fix is behind them.
        """
        values = self.values()
        bad = [key for key, _label, required in self.FIELDS
               if required and not values.get(key)]
        year = values.get("birth_year")
        if year is not None and not isinstance(year, int):
            bad.append("birth_year")
        self._mark(bad)
        if bad:
            self.banner.render(strings.ENROLL_ERRORS[self.REASONS[bad[0]]], vm.ATTENTION)
            self.inputs[bad[0]].setFocus()
            return
        self.submitted.emit(values)

    REASONS = {"patient_code": "missing_patient_code", "full_name": "missing_full_name",
               "birth_year": "bad_birth_year"}

    def _mark(self, bad):
        for key, line in self.inputs.items():
            name = "invalid" if key in bad else ""
            if line.objectName() != name:
                line.setObjectName(name)
                line.style().unpolish(line)
                line.style().polish(line)

    def render(self, view):
        # The action row is built once, in build(), so the generic render must not take
        # it over: this page's buttons are widgets, not a View.
        self.bar.render(view.title or "", view.severity, view.chips,
                        TITLE_ICONS.get(vm.ENROLL))
        self.banner.render(view.message or "", view.severity)


class KioskWindow(QtWidgets.QMainWindow):
    def __init__(self, controller, cfg, fullscreen=True):
        super(KioskWindow, self).__init__()
        self.controller = controller
        self.cfg = cfg
        self.setWindowTitle(strings.APP_TITLE)
        self.setStyleSheet(load_stylesheet())

        roi = (cfg.get("subject") or {}).get("roi")
        pin_length = (cfg.get("auth") or {}).get("pin_length", 6)
        self.stack = QtWidgets.QStackedWidget()
        self.pages = {
            vm.IDLE: IdlePage(cfg=cfg, screen=vm.IDLE),
            vm.GUIDANCE: GuidancePage(with_preview=True, roi=roi, cfg=cfg,
                                      screen=vm.GUIDANCE),
            vm.CANDIDATE: CandidatePage(with_preview=True, roi=roi, cfg=cfg,
                                        screen=vm.CANDIDATE),
            vm.ALERT: AlertPage(with_preview=True, roi=roi, cfg=cfg, screen=vm.ALERT),
            vm.ERROR: ErrorPage(cfg=cfg, screen=vm.ERROR),
            vm.SEARCH: SearchPage(cfg=cfg, screen=vm.SEARCH),
            vm.PIN: PinPage(pin_length=pin_length, cfg=cfg, screen=vm.PIN),
            vm.ADMIN: AdminPage(cfg=cfg, screen=vm.ADMIN),
            vm.PATIENTS: PatientListPage(cfg=cfg, screen=vm.PATIENTS),
            vm.STATUS: StatusPage(cfg=cfg, screen=vm.STATUS),
            vm.CHANGE_PIN: ChangePinPage(pin_length=pin_length, cfg=cfg,
                                         screen=vm.CHANGE_PIN),
            vm.DUPLICATE: DuplicatePage(with_preview=True, roi=roi, cfg=cfg,
                                        screen=vm.DUPLICATE),
            vm.ENROLL: EnrollPage(with_preview=True, roi=roi, cfg=cfg,
                                  screen=vm.ENROLL),
        }
        for page in self.pages.values():
            page.button_clicked.connect(self._on_button)
            self.stack.addWidget(page)
        self.enroll_form = EnrollFormPage(cfg=cfg, screen=vm.ENROLL)
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
        page.extras = self._extras_for(view.screen)
        if view.screen == vm.DUPLICATE:
            page.faces = self.controller.duplicate_faces()
        page.render(view)
        self.stack.setCurrentWidget(page)

    def _extras_for(self, screen):
        """Per-screen data that is not part of the View: rows, tiles, card captions.

        These are database reads rather than a reading of the engine state, which is
        what the View is for, and they would make every screen carry fields only one
        screen ever uses.
        """
        if screen == vm.PATIENTS:
            return self.controller.patient_rows()
        if screen == vm.STATUS:
            return {"tiles": self.controller.status_tiles(),
                    "device_line": self.controller.device_line()}
        if screen == vm.ADMIN:
            return self.controller.admin_summary()
        return {}

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

    def closeEvent(self, event):
        """Stop polling when the window goes away.

        The timers outlive close() otherwise, and go on calling a controller whose
        database connection has been closed - which in Qt means an exception inside a
        slot, which means the process aborts rather than raises.
        """
        self._poll.stop()
        self._preview_timer.stop()
        self._gesture.stop()
        super(KioskWindow, self).closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        elif event.key() == QtCore.Qt.Key_F2:      # keyboard shortcut for the admin screen
            self._open_admin()
        else:
            super(KioskWindow, self).keyPressEvent(event)
