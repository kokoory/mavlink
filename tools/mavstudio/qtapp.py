"""Qt desktop front-end for mavstudio.

Same five layers, same files on disk, same validation as the CLI and the web
UI -- this module only draws them. Everything that changes state goes through
:mod:`.customdialect`, :mod:`.profile` and :mod:`.build`, so the three
front-ends can never drift apart.

    python3 -m mavstudio qt

Needs PySide6::

    python3 -m pip install PySide6
"""

from __future__ import annotations

import os
import sys

try:
    from PySide6.QtCore import Qt, QThread, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSplitter,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise SystemExit(
        "The Qt front-end needs PySide6:\n"
        "    python3 -m pip install PySide6\n"
        "Or use the browser UI instead:  python3 -m mavstudio web"
    ) from exc

from .bandwidth import compute_budget
from .build import MAVGEN_LANGUAGES, build_profile_dialect, generate_sources
from .customdialect import (
    DialectError,
    add_message,
    build_message,
    id_space_report,
    load_custom_dialect,
    load_metadata,
    remove_message,
    set_metadata,
    update_message,
    validate_message,
)
from .icd import write_icd
from .mosa import compatibility_matrix, load_interfaces, load_modules
from .parser import message_xml
from .profile import MessageOverride, list_profiles
from .upstream import compare as upstream_compare
from .validate import validate_all
from .workspace import open_studio

SCALAR_TYPES = [
    "uint8_t", "int8_t", "uint16_t", "int16_t", "uint32_t", "int32_t",
    "uint64_t", "int64_t", "float", "double", "char",
]

STATUS_COLOURS = {
    "standard": "#8b93a3",
    "custom": "#c084fc",
    "experimental": "#e0a94b",
    "superseded": "#c8a26a",
    "deprecated": "#a1783c",
    "conflict": "#ef6d6d",
}

SECTIONS = [
    "Dashboard", "Message Catalog", "Commands", "Capabilities",
    "UAV Profiles", "Interfaces / MOSA", "Network & Bandwidth",
    "Build & Validation",
]

STYLE = """
QWidget { background: #14171c; color: #dfe3ea;
          font-family: "Noto Sans", "Segoe UI", sans-serif; font-size: 12px; }
QMainWindow::separator { background: #2e343f; width: 1px; height: 1px; }
QLabel#title { font-size: 15px; font-weight: 600; }
QLabel#sub { color: #8b93a3; font-size: 10px; font-weight: 600; }
QLabel#big { font-size: 20px; font-weight: 600; }
QLabel#dim { color: #8b93a3; }
QLabel#ok { color: #4cc38a; }
QLabel#err { color: #ef6d6d; }
QLabel#warn { color: #e0a94b; }
QListWidget { background: #1b1f26; border: none; outline: none; }
QListWidget::item { padding: 7px 12px; }
QListWidget::item:selected { background: #21262f; color: #ffffff;
                             border-left: 2px solid #4da3ff; }
QTableWidget { background: #14171c; gridline-color: #23272f;
               selection-background-color: #253243; alternate-background-color: #171b21; }
QHeaderView::section { background: #1b1f26; color: #8b93a3; border: none;
                       border-bottom: 1px solid #2e343f; padding: 4px 6px;
                       font-size: 10px; font-weight: 600; }
QPushButton { background: #21262f; border: 1px solid #2e343f; border-radius: 4px;
              padding: 4px 12px; }
QPushButton:hover:!disabled { border-color: #2b6ba8; }
QPushButton:disabled { color: #565e6c; }
QPushButton#primary { background: #2b6ba8; border-color: #4da3ff; }
QPushButton#danger { border-color: #6b3030; }
QLineEdit, QComboBox, QPlainTextEdit, QDoubleSpinBox, QTextBrowser {
    background: #21262f; border: 1px solid #2e343f; border-radius: 4px;
    padding: 3px 6px; }
QLineEdit:read-only { color: #8b93a3; }
QPlainTextEdit#xml, QTextBrowser { font-family: "DejaVu Sans Mono", monospace;
                                   font-size: 11px; background: #0f1216; }
QGroupBox { border: 1px solid #2e343f; border-radius: 5px; margin-top: 14px;
            padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px;
                   color: #8b93a3; font-size: 10px; font-weight: 600; }
QProgressBar { background: #21262f; border: 1px solid #2e343f; border-radius: 4px;
               height: 12px; text-align: center; font-size: 10px; }
QProgressBar::chunk { background: #4cc38a; border-radius: 3px; }
QProgressBar#warn::chunk { background: #e0a94b; }
QProgressBar#err::chunk { background: #ef6d6d; }
QSplitter::handle { background: #2e343f; }
QScrollArea { border: none; }
"""


def mono() -> QFont:
    font = QFont("DejaVu Sans Mono")
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(9)
    return font


class GeneratorThread(QThread):
    """mavgen can take a few seconds; keep the window responsive."""

    finished_with = Signal(bool, str)

    def __init__(self, dialect_path: str, language: str, output_dir: str):
        super().__init__()
        self.dialect_path = dialect_path
        self.language = language
        self.output_dir = output_dir

    def run(self):
        ok, output = generate_sources(
            self.dialect_path, self.language, self.output_dir
        )
        self.finished_with.emit(ok, output)


class MessageDialogPanel(QWidget):
    """Add / edit a custom message, with live XML and live validation."""

    saved = Signal(str)
    cancelled = Signal()

    def __init__(self, window: "StudioWindow"):
        super().__init__()
        self.window = window
        self.editing = ""
        self.rows: list[dict] = []

        outer = QVBoxLayout(self)
        self.heading = QLabel("New custom message", objectName="title")
        outer.addWidget(self.heading)
        self.target = QLabel(objectName="dim")
        self.target.setWordWrap(True)
        outer.addWidget(self.target)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.name = QLineEdit(placeholderText="UAV_MOTOR_VIBRATION")
        self.message_id = QLineEdit("auto", placeholderText="auto")
        self.id_range = QLineEdit(readOnly=True)
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(48)
        self.interface = QLineEdit(placeholderText="PROPULSION.MONITORING")
        self.requirements = QLineEdit(placeholderText="SRS-PROP-003, SRS-PROP-004")
        form.addRow("Name", self.name)
        form.addRow("Message ID", self.message_id)
        form.addRow("Reserved range", self.id_range)
        form.addRow("Description", self.description)
        form.addRow("MOSA interface", self.interface)
        form.addRow("Requirement ids", self.requirements)
        outer.addLayout(form)

        self.field_header = QLabel("Fields", objectName="sub")
        outer.addWidget(self.field_header)
        self.fields = QTableWidget(0, 8)
        self.fields.setHorizontalHeaderLabels(
            ["Name", "Type", "Len", "Units", "Enum", "Ext", "Description", ""]
        )
        self.fields.verticalHeader().setVisible(False)
        header = self.fields.horizontalHeader()
        for column, mode in enumerate([
            QHeaderView.Stretch, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.Stretch, QHeaderView.ResizeToContents,
        ]):
            header.setSectionResizeMode(column, mode)
        outer.addWidget(self.fields, 1)

        buttons = QHBoxLayout()
        add_field = QPushButton("+ Add field")
        add_field.clicked.connect(lambda: self.add_row())
        self.save_button = QPushButton("Add to dialect", objectName="primary")
        self.save_button.clicked.connect(self.save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancelled.emit)
        buttons.addWidget(add_field)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(cancel)
        outer.addLayout(buttons)

        for widget in (self.name, self.message_id):
            widget.textChanged.connect(self.refresh_preview)
        self.description.textChanged.connect(self.refresh_preview)

    # -- rows -------------------------------------------------------------

    def add_row(self, field: dict | None = None):
        field = field or {"name": "", "type": "float", "array": 1, "units": "",
                          "enum": "", "extension": False, "description": ""}
        row = self.fields.rowCount()
        self.fields.insertRow(row)

        name = QLineEdit(field["name"])
        type_box = QComboBox()
        type_box.addItems(SCALAR_TYPES)
        type_box.setCurrentText(field["type"] if field["type"] in SCALAR_TYPES
                                else "float")
        length = QLineEdit(str(field.get("array", 1)))
        length.setFixedWidth(46)
        units = QLineEdit(field.get("units", ""))
        units.setFixedWidth(74)
        enum = QLineEdit(field.get("enum", ""))
        enum.setFixedWidth(150)
        extension = QCheckBox()
        extension.setChecked(bool(field.get("extension")))
        extension_holder = QWidget()
        holder_layout = QHBoxLayout(extension_holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(extension, 0, Qt.AlignCenter)
        description = QLineEdit(field.get("description", ""))
        remove = QPushButton("x")
        remove.setFixedWidth(26)

        for column, widget in enumerate(
            [name, type_box, length, units, enum, extension_holder,
             description, remove]
        ):
            self.fields.setCellWidget(row, column, widget)

        entry = {"name": name, "type": type_box, "array": length, "units": units,
                 "enum": enum, "extension": extension,
                 "description": description}
        self.rows.append(entry)
        remove.clicked.connect(lambda: self.remove_row(entry))
        for widget in (name, length, units, enum, description):
            widget.textChanged.connect(self.refresh_preview)
        type_box.currentTextChanged.connect(self.refresh_preview)
        extension.stateChanged.connect(self.refresh_preview)
        self.refresh_preview()

    def remove_row(self, entry: dict):
        index = self.rows.index(entry)
        self.rows.pop(index)
        self.fields.removeRow(index)
        self.refresh_preview()

    def collect(self) -> list[dict]:
        fields = []
        for entry in self.rows:
            try:
                count = max(1, int(entry["array"].text() or 1))
            except ValueError:
                count = 1
            base = entry["type"].currentText()
            fields.append({
                "name": entry["name"].text().strip(),
                "type": f"{base}[{count}]" if count > 1 else base,
                "units": entry["units"].text().strip(),
                "enum": entry["enum"].text().strip(),
                "extension": entry["extension"].isChecked(),
                "description": entry["description"].text().strip(),
            })
        return fields

    # -- lifecycle --------------------------------------------------------

    def start(self, existing: str = ""):
        self.editing = existing
        self.rows.clear()
        self.fields.setRowCount(0)
        project = self.window.studio.project
        low, high = project.id_space.messages
        self.id_range.setText(f"{low} - {high}")
        self.target.setText(
            f"Written to {project.dialect.path}. Upstream definitions are "
            "never touched."
        )
        metadata = load_metadata(project)

        if existing:
            message = next(
                m for m in load_custom_dialect(project).messages
                if m.name == existing
            )
            self.heading.setText(f"Edit {existing}")
            self.save_button.setText("Save to dialect")
            self.name.setText(message.name)
            self.name.setReadOnly(True)
            self.message_id.setText(str(message.id))
            self.description.setPlainText(message.description)
            entry = metadata.get(existing, {})
            self.interface.setText(entry.get("interface", ""))
            self.requirements.setText(", ".join(entry.get("requirements", [])))
            for field in message.fields:
                base = field.base_type
                self.add_row({
                    "name": field.name, "type": base,
                    "array": field.array_length, "units": field.units,
                    "enum": field.enum, "extension": field.is_extension,
                    "description": field.description,
                })
        else:
            self.heading.setText("New custom message")
            self.save_button.setText("Add to dialect")
            self.name.setReadOnly(False)
            self.name.clear()
            self.message_id.setText("auto")
            self.description.clear()
            self.interface.clear()
            self.requirements.clear()
            self.add_row({
                "name": "time_usec", "type": "uint64_t", "array": 1,
                "units": "us", "enum": "", "extension": False,
                "description": "Timestamp (UNIX Epoch or time since system boot).",
            })
        self.refresh_preview()

    def proposed(self):
        studio = self.window.studio
        raw = self.message_id.text().strip()
        if raw in ("", "auto"):
            low, high = studio.project.id_space.messages
            message_id = studio.catalog.next_free_id(low, high) or low
        else:
            try:
                message_id = int(raw)
            except ValueError:
                return None, ["message id must be a number or 'auto'"]
        message = build_message(
            self.name.text().strip() or "NEW_MESSAGE", message_id,
            self.description.toPlainText().strip(), self.collect(),
        )
        errors = validate_message(studio.project, studio.catalog, message,
                                  replacing=self.editing)
        return message, errors

    def refresh_preview(self):
        message, errors = self.proposed()
        if message is None:
            self.window.set_preview("", errors)
            self.save_button.setEnabled(False)
            return
        self.field_header.setText(
            f"Fields - {message.payload_bytes} of 255 payload bytes"
        )
        self.window.set_preview("\n".join(message_xml(message, "")), errors,
                                message.id, message.payload_bytes)
        self.save_button.setEnabled(not errors)

    def save(self):
        message, errors = self.proposed()
        if message is None or errors:
            return
        studio = self.window.studio
        try:
            if self.editing:
                path = update_message(studio.project, message, studio.catalog)
            else:
                path = add_message(studio.project, message, studio.catalog)
        except DialectError as exc:
            QMessageBox.critical(self, "Cannot save", str(exc))
            return
        requirements = [
            r.strip() for r in self.requirements.text().split(",") if r.strip()
        ]
        if self.interface.text().strip() or requirements:
            set_metadata(
                studio.project, message.name,
                interface=self.interface.text().strip() or None,
                requirements=requirements or None,
            )
        self.window.status(f"Wrote {path} (id {message.id})")
        self.saved.emit(message.name)


class StudioWindow(QMainWindow):
    def __init__(self, project_root: str, vehicle: str = "", profile: str = ""):
        super().__init__()
        self.project_root = project_root
        self.vehicle = vehicle
        self.profile_name = profile
        self.selected = ""
        self.generator: GeneratorThread | None = None
        self.setWindowTitle("UAV MAVLink Studio")
        self.resize(1560, 940)
        self.setStyleSheet(STYLE)
        self._build_chrome()
        self.reload()

    # -- chrome -----------------------------------------------------------

    def _build_chrome(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setStyleSheet("background:#1b1f26; border-bottom:1px solid #2e343f;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 7, 12, 7)
        bar_layout.addWidget(QLabel("UAV MAVLink Studio", objectName="title"))
        bar_layout.addSpacing(16)
        bar_layout.addWidget(QLabel("Profile", objectName="dim"))
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(210)
        self.profile_box.currentIndexChanged.connect(self._profile_changed)
        bar_layout.addWidget(self.profile_box)
        self.link_label = QLabel(objectName="dim")
        bar_layout.addWidget(self.link_label)
        bar_layout.addStretch(1)
        for label, slot, name in [
            ("Validate", lambda: self.select_section(7), ""),
            ("Build", self.do_build, ""),
            ("ICD", self.do_icd, ""),
            ("Reload", self.reload, "primary"),
        ]:
            button = QPushButton(label)
            if name:
                button.setObjectName(name)
            button.clicked.connect(slot)
            bar_layout.addWidget(button)
        root.addWidget(bar)

        splitter = QSplitter(Qt.Horizontal)
        self.nav = QListWidget()
        self.nav.setFixedWidth(190)
        self.nav.addItems(SECTIONS)
        self.nav.currentRowChanged.connect(self._section_changed)
        splitter.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.pages = {}
        for index, _ in enumerate(SECTIONS):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(12, 10, 12, 10)
            self.pages[index] = layout
            self.stack.addWidget(page)
        self.message_form = MessageDialogPanel(self)
        self.message_form.saved.connect(self._form_saved)
        self.message_form.cancelled.connect(self._form_cancelled)
        self.stack.addWidget(self.message_form)
        splitter.addWidget(self.stack)

        self.inspector = QScrollArea()
        self.inspector.setWidgetResizable(True)
        self.inspector.setFixedWidth(380)
        self.inspector.setStyleSheet("background:#1b1f26;")
        splitter.addWidget(self.inspector)
        splitter.setSizes([190, 990, 380])
        root.addWidget(splitter, 1)

        self.statusBar().setStyleSheet(
            "background:#1b1f26; border-top:1px solid #2e343f; color:#8b93a3;"
        )
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)
        self.nav.setCurrentRow(0)

    def status(self, text: str):
        self.statusBar().showMessage(text, 12000)

    # -- data -------------------------------------------------------------

    def reload(self):
        self.studio = open_studio(self.project_root, self.vehicle,
                                  self.profile_name)
        self.vehicle = self.studio.profile.vehicle
        self.profile_name = self.studio.profile.name
        self.report = validate_all(self.studio.project, self.studio.catalog,
                                   self.studio.capability_set,
                                   self.studio.resolution)
        self.budget = compute_budget(self.studio.resolution)
        self.metadata = load_metadata(self.studio.project)
        self.custom_names = {
            m.name for m in load_custom_dialect(self.studio.project).messages
        }

        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profiles = list_profiles(self.studio.project) or [
            (self.vehicle, self.profile_name)
        ]
        for vehicle, profile in self.profiles:
            self.profile_box.addItem(f"{vehicle} / {profile}")
        current = (self.vehicle, self.profile_name)
        if current in self.profiles:
            self.profile_box.setCurrentIndex(self.profiles.index(current))
        self.profile_box.blockSignals(False)

        link = self.studio.profile.link
        self.link_label.setText(
            f"   MAVLink {link.mavlink_version}.0"
            f"{' signed' if link.signing else ''}   {link.bitrate} bit/s"
        )
        for index in range(len(SECTIONS)):
            self._render(index)
        self._update_nav_counts()
        if self.selected:
            self.show_message(self.selected)
        self.status(
            f"{len(self.studio.resolution.enabled_messages())} enabled, "
            f"{self.report.counts()['error']} errors, "
            f"{self.report.counts()['warn']} warnings"
        )

    def _update_nav_counts(self):
        counts = {
            1: len(self.studio.resolution.enabled_messages()),
            2: len(self.studio.resolution.enabled_commands()),
            3: sum(1 for v in self.studio.resolution.capability_states.values() if v),
            4: len(self.profiles),
            5: len(load_interfaces(self.studio.project)),
            7: self.report.counts()["error"] or "",
        }
        for index, label in enumerate(SECTIONS):
            value = counts.get(index, "")
            self.nav.item(index).setText(
                f"{label}    {value}" if value != "" else label
            )

    def _profile_changed(self, index: int):
        if 0 <= index < len(self.profiles):
            self.vehicle, self.profile_name = self.profiles[index]
            self.selected = ""
            self.reload()

    def _section_changed(self, row: int):
        if row >= 0:
            self.stack.setCurrentIndex(row)

    def select_section(self, row: int):
        self.nav.setCurrentRow(row)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                StudioWindow._clear(item.layout())

    @staticmethod
    def _table(headers: list[str], stretch: int = 0) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
        return table

    def _card(self, label: str, value, kind: str = "") -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(1)
        box.setStyleSheet(
            "background:#1b1f26; border:1px solid #2e343f; border-radius:5px;"
        )
        layout.addWidget(QLabel(label.upper(), objectName="sub"))
        value_label = QLabel(str(value), objectName="big")
        if kind == "bad":
            value_label.setStyleSheet("color:#ef6d6d;")
        elif kind == "good":
            value_label.setStyleSheet("color:#4cc38a;")
        layout.addWidget(value_label)
        return box

    def _meter(self) -> QProgressBar:
        bar = QProgressBar()
        utilisation = self.budget.utilisation
        bar.setValue(int(min(100, utilisation * 100)))
        bar.setFormat(f"{utilisation * 100:.1f}% of link")
        if utilisation > 1:
            bar.setObjectName("err")
        elif self.budget.total_bps > self.budget.budget_bps:
            bar.setObjectName("warn")
        bar.setStyleSheet(STYLE)
        return bar

    # -- pages ------------------------------------------------------------

    def _render(self, index: int):
        layout = self.pages[index]
        self._clear(layout)
        [self.page_dashboard, self.page_messages, self.page_commands,
         self.page_capabilities, self.page_profiles, self.page_mosa,
         self.page_network, self.page_build][index](layout)

    def page_dashboard(self, layout):
        studio = self.studio
        status = upstream_compare(studio.project, studio.catalog,
                                  studio.resolution)
        layout.addWidget(QLabel(studio.project.name, objectName="title"))

        cards = QHBoxLayout()
        modified = len(status.modified_standard)
        conflicts = len(status.conflicts)
        for label, value, kind in [
            ("Enabled messages", status.enabled_messages, ""),
            ("Disabled", status.disabled_messages, ""),
            ("Custom messages", len(status.added_messages), ""),
            ("Modified standard", modified, "bad" if modified else "good"),
            ("ID conflicts", conflicts, "bad" if conflicts else "good"),
            ("Validation errors", self.report.counts()["error"],
             "bad" if self.report.counts()["error"] else "good"),
        ]:
            cards.addWidget(self._card(label, value, kind))
        layout.addLayout(cards)

        upstream = QGroupBox("Upstream")
        form = QFormLayout(upstream)
        form.addRow("Commit", QLabel(f"{status.commit}  {status.commit_subject}"))
        form.addRow("Catalog", QLabel(
            f"{status.upstream_message_count} messages in "
            f"{status.upstream_dialects} dialects"))
        form.addRow("Base", QLabel(
            f"{status.base_dialect}.xml ({status.base_message_count} messages)"))
        form.addRow("Added", QLabel(
            f"{len(status.added_messages)} messages, "
            f"{len(status.added_commands)} commands, "
            f"{len(status.added_enums)} enums"))
        layout.addWidget(upstream)

        budget = QGroupBox("Telemetry budget")
        budget_layout = QVBoxLayout(budget)
        budget_layout.addWidget(QLabel(
            f"{self.budget.link_name} - {self.budget.bitrate} bit/s   "
            f"periodic {self.budget.total_bps / 1000:.1f} kbps of "
            f"{self.budget.budget_bps / 1000:.1f} kbps budget"))
        budget_layout.addWidget(self._meter())
        for warning in self.budget.warnings:
            label = QLabel(warning, objectName="warn")
            label.setWordWrap(True)
            budget_layout.addWidget(label)
        layout.addWidget(budget)

        errors = self.report.errors
        if errors:
            box = QGroupBox(f"Blocking issues ({len(errors)})")
            box_layout = QVBoxLayout(box)
            for issue in errors[:8]:
                label = QLabel(
                    f"[{issue.check}] {issue.subject}: {issue.message}",
                    objectName="err")
                label.setWordWrap(True)
                box_layout.addWidget(label)
            layout.addWidget(box)
        layout.addStretch(1)

    def page_messages(self, layout):
        controls = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search name or id...")
        self.search.textChanged.connect(self._filter_messages)
        controls.addWidget(self.search, 2)

        self.dialect_filter = QComboBox()
        self.dialect_filter.addItem("All sources")
        self.dialect_filter.addItems(sorted(self.studio.catalog.dialects))
        self.dialect_filter.currentTextChanged.connect(self._filter_messages)
        controls.addWidget(self.dialect_filter)

        self.capability_filter = QComboBox()
        self.capability_filter.addItem("All capabilities", "")
        for capability in self.studio.capability_set.capabilities:
            self.capability_filter.addItem(capability.title, capability.key)
        self.capability_filter.currentIndexChanged.connect(self._filter_messages)
        controls.addWidget(self.capability_filter)

        self.state_filter = QComboBox()
        self.state_filter.addItems(["All", "Enabled", "Disabled", "Custom",
                                    "Has rate", "Deprecated", "In a contract"])
        self.state_filter.currentTextChanged.connect(self._filter_messages)
        controls.addWidget(self.state_filter)

        new_button = QPushButton("+ New message", objectName="primary")
        new_button.clicked.connect(lambda: self._open_form(""))
        controls.addWidget(new_button)
        layout.addLayout(controls)

        self.message_table = self._table(
            ["ON", "ID", "Message", "Source", "TX", "RX", "Rate", "Bytes",
             "Category", "Interface"], stretch=2)
        self.message_table.itemSelectionChanged.connect(self._row_selected)
        layout.addWidget(self.message_table, 1)
        self.message_count = QLabel(objectName="dim")
        layout.addWidget(self.message_count)
        self._fill_messages()

    def _fill_messages(self):
        table = self.message_table
        table.blockSignals(True)
        table.setRowCount(0)
        states = sorted(self.studio.resolution.states.values(),
                        key=lambda s: s.id)
        self._rows = []
        for state in states:
            row = table.rowCount()
            table.insertRow(row)
            self._rows.append(state)

            box = QCheckBox()
            box.setChecked(state.enabled)
            box.setEnabled(not state.required)
            box.setToolTip("Required - cannot be disabled" if state.required
                           else state.reason)
            box.clicked.connect(
                lambda checked, name=state.name: self._toggle(name, checked)
            )
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addWidget(box, 0, Qt.AlignCenter)
            table.setCellWidget(row, 0, holder)

            meta = self.metadata.get(state.name, {})
            cells = [
                str(state.id), state.name, state.dialect,
                ",".join(state.tx) or "-", ",".join(state.rx) or "-",
                f"{state.rate_hz:g}" if state.rate_hz else "-",
                str(state.payload_bytes), state.category,
                meta.get("interface", "-"),
            ]
            for column, text in enumerate(cells, start=1):
                item = QTableWidgetItem(text)
                if column == 2:
                    item.setFont(mono())
                    item.setForeground(QColor(
                        STATUS_COLOURS.get(state.status, "#dfe3ea")
                        if state.status != "standard" else "#dfe3ea"))
                if not state.enabled:
                    item.setForeground(QColor("#6b7383"))
                table.setItem(row, column, item)
        table.blockSignals(False)
        self._filter_messages()

    def _filter_messages(self, *_):
        if not hasattr(self, "message_table"):
            return
        query = self.search.text().strip().lower()
        dialect = self.dialect_filter.currentText()
        capability = self.capability_filter.currentData() or ""
        mode = self.state_filter.currentText()
        shown = 0
        for row, state in enumerate(self._rows):
            visible = True
            if query and query not in state.name.lower() and query != str(state.id):
                visible = False
            if dialect != "All sources" and state.dialect != dialect:
                visible = False
            if capability and state.capability != capability:
                visible = False
            if mode == "Enabled" and not state.enabled:
                visible = False
            elif mode == "Disabled" and state.enabled:
                visible = False
            elif mode == "Custom" and state.origin != "custom":
                visible = False
            elif mode == "Has rate" and not state.rate_hz:
                visible = False
            elif mode == "Deprecated" and state.status != "deprecated":
                visible = False
            elif mode == "In a contract" and not self.metadata.get(
                    state.name, {}).get("interface"):
                visible = False
            self.message_table.setRowHidden(row, not visible)
            shown += visible
        self.message_count.setText(
            f"{shown} of {len(self._rows)} messages"
        )

    def _row_selected(self):
        rows = self.message_table.selectionModel().selectedRows()
        if rows:
            self.show_message(self._rows[rows[0].row()].name)

    def _toggle(self, name: str, enabled: bool):
        override = self.studio.profile.messages.setdefault(name, MessageOverride())
        override.enabled = enabled
        self.studio.profile.save(self.studio.project)
        self.selected = name
        self.reload()

    def page_commands(self, layout):
        commands = self.studio.resolution.command_states
        enabled = sum(1 for v in commands.values() if v)
        layout.addWidget(QLabel(
            f"{enabled} of {len(commands)} MAV_CMD entries enabled. Commands "
            "follow their capability; only enabled ones reach the built dialect.",
            objectName="dim"))
        table = self._table(["ON", "Value", "Command", "Description"], stretch=3)
        for name in sorted(commands):
            entry = self.studio.catalog.commands.get(name)
            if entry is None:
                continue
            row = table.rowCount()
            table.insertRow(row)
            on = commands[name]
            for column, text in enumerate(
                ["ON" if on else "", entry.value, name,
                 (entry.description or "")[:120]]
            ):
                item = QTableWidgetItem(str(text))
                if not on:
                    item.setForeground(QColor("#6b7383"))
                table.setItem(row, column, item)
        layout.addWidget(table, 1)

    def page_capabilities(self, layout):
        layout.addWidget(QLabel(
            "Turning a capability off disables every message it owns. Required "
            "capabilities keep MAVLink working and cannot be switched off.",
            objectName="dim"))
        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        for group, capabilities in self.studio.capability_set.groups().items():
            box = QGroupBox(group)
            box_layout = QVBoxLayout(box)
            for capability in capabilities:
                row = QHBoxLayout()
                check = QCheckBox(capability.title)
                check.setChecked(
                    self.studio.resolution.capability_states.get(
                        capability.key, False)
                )
                check.setEnabled(not capability.required)
                check.clicked.connect(
                    lambda checked, key=capability.key:
                    self._toggle_capability(key, checked)
                )
                row.addWidget(check, 1)
                owned = self.studio.capability_set.messages_for(
                    capability.key, self.studio.catalog)
                row.addWidget(QLabel(
                    f"{len(owned)} msgs" + ("  required" if capability.required
                                            else ""),
                    objectName="dim"))
                show = QPushButton("show")
                show.setFixedWidth(58)
                show.clicked.connect(
                    lambda _, key=capability.key: self._show_capability(key)
                )
                row.addWidget(show)
                box_layout.addLayout(row)
            inner_layout.addWidget(box)
        inner_layout.addStretch(1)
        area.setWidget(inner)
        layout.addWidget(area, 1)

    def _toggle_capability(self, key: str, enabled: bool):
        capability = self.studio.capability_set.get(key)
        if capability and capability.required and not enabled:
            QMessageBox.information(
                self, "Required capability",
                f"'{capability.title}' is required and stays on.")
            self.reload()
            return
        self.studio.profile.capabilities[key] = enabled
        self.studio.profile.save(self.studio.project)
        self.reload()

    def _show_capability(self, key: str):
        self.select_section(1)
        index = self.capability_filter.findData(key)
        if index >= 0:
            self.capability_filter.setCurrentIndex(index)
        self.state_filter.setCurrentText("All")

    def page_profiles(self, layout):
        layout.addWidget(QLabel(
            f"Profiles live in {self.studio.project.profiles_dir}. Same dialect, "
            "different feature set: flight, SITL, maintenance.", objectName="dim"))
        table = self._table(["Vehicle", "Profile", ""], stretch=2)
        for vehicle, profile in self.profiles:
            row = table.rowCount()
            table.insertRow(row)
            current = (vehicle, profile) == (self.vehicle, self.profile_name)
            for column, text in enumerate(
                [vehicle, profile, "current" if current else ""]
            ):
                table.setItem(row, column, QTableWidgetItem(text))
        table.setFixedHeight(min(220, 40 + 24 * len(self.profiles)))
        layout.addWidget(table)

        report = id_space_report(self.studio.project, self.studio.catalog)
        box = QGroupBox("Message ID space")
        form = QFormLayout(box)
        low, high = report["range"]
        form.addRow("Range", QLabel(f"{low} - {high}"))
        form.addRow("Used by project", QLabel(str(report["used_by_project"])))
        form.addRow("Used by others", QLabel(str(report["used_by_others"])))
        form.addRow("Available", QLabel(str(report["available"])))
        form.addRow("Next free", QLabel(str(report["next_free"])))
        layout.addWidget(box)

        assignments = self._table(["ID", "Message"], stretch=1)
        for name, message_id in report["assignments"].items():
            row = assignments.rowCount()
            assignments.insertRow(row)
            assignments.setItem(row, 0, QTableWidgetItem(str(message_id)))
            assignments.setItem(row, 1, QTableWidgetItem(name))
        layout.addWidget(assignments, 1)

    def page_mosa(self, layout):
        interfaces = load_interfaces(self.studio.project)
        modules = load_modules(self.studio.project)
        if not interfaces and not modules:
            hint = QLabel(
                "No interface contracts yet. Create one from the CLI:\n\n"
                "  python3 -m mavstudio interface add PROPULSION.MONITORING \\\n"
                "      --required UAV_MOTOR_STATUS --provider ESC --consumer FC",
                objectName="dim")
            hint.setFont(mono())
            layout.addWidget(hint)
            layout.addStretch(1)
            return

        table = self._table(
            ["Interface", "Version", "Providers", "Consumers", "Req", "Opt",
             "Cmds", "Transport"], stretch=0)
        for name in sorted(interfaces):
            contract = interfaces[name]
            row = table.rowCount()
            table.insertRow(row)
            for column, text in enumerate([
                name, contract.version, ", ".join(contract.providers) or "-",
                ", ".join(contract.consumers) or "-",
                len(contract.required_messages),
                len(contract.optional_messages), len(contract.commands),
                ", ".join(contract.transport),
            ]):
                table.setItem(row, column, QTableWidgetItem(str(text)))
        layout.addWidget(QLabel("INTERFACE CONTRACTS", objectName="sub"))
        layout.addWidget(table)

        if modules:
            matrix = compatibility_matrix(interfaces, modules)
            layout.addWidget(QLabel(
                "COMPATIBILITY MATRIX   P provider, C consumer, "
                "! claimed but not satisfied, ? role never declared, "
                "~ candidate part", objectName="sub"))
            grid = self._table(["Interface", "Ver", *matrix["modules"]], stretch=0)
            for entry in matrix["rows"]:
                row = grid.rowCount()
                grid.insertRow(row)
                grid.setItem(row, 0, QTableWidgetItem(entry["interface"]))
                grid.setItem(row, 1, QTableWidgetItem(entry["version"]))
                for column, cell in enumerate(entry["cells"], start=2):
                    item = QTableWidgetItem(cell)
                    if "!" in cell:
                        item.setForeground(QColor("#ef6d6d"))
                    elif "?" in cell or "~" in cell:
                        item.setForeground(QColor("#e0a94b"))
                    grid.setItem(row, column, item)
            layout.addWidget(grid)

            layout.addWidget(QLabel("MODULE MANIFESTS", objectName="sub"))
            module_table = self._table(
                ["Module", "Kind", "Vendor", "Version", "State", "Implements"],
                stretch=5)
            for name in sorted(modules):
                manifest = modules[name]
                row = module_table.rowCount()
                module_table.insertRow(row)
                for column, text in enumerate([
                    name, manifest.kind, manifest.vendor or "-", manifest.version,
                    "installed" if manifest.installed else "candidate",
                    ", ".join(f"{k} {v}" for k, v in manifest.interfaces.items())
                    or "-",
                ]):
                    module_table.setItem(row, column, QTableWidgetItem(str(text)))
            layout.addWidget(module_table, 1)

    def page_network(self, layout):
        budget = self.budget
        box = QGroupBox("Telemetry budget")
        form = QFormLayout(box)
        form.addRow("Link", QLabel(budget.link_name))
        form.addRow("Bitrate", QLabel(f"{budget.bitrate} bit/s"))
        form.addRow("Payload", QLabel(f"{budget.payload_bps / 1000:.1f} kbps"))
        form.addRow("Overhead", QLabel(f"{budget.overhead_bps / 1000:.1f} kbps"))
        form.addRow("Total", QLabel(f"{budget.total_bps / 1000:.1f} kbps"))
        form.addRow("Budget", QLabel(f"{budget.budget_bps / 1000:.1f} kbps"))
        form.addRow("Utilisation", self._meter())
        layout.addWidget(box)
        for warning in budget.warnings:
            label = QLabel(warning, objectName="warn")
            label.setWordWrap(True)
            layout.addWidget(label)

        table = self._table(
            ["Message", "Payload", "Frame", "Rate", "kbps", "Share"], stretch=0)
        for stream in budget.streams:
            row = table.rowCount()
            table.insertRow(row)
            for column, text in enumerate([
                stream.name, stream.payload_bytes, stream.frame_bytes,
                f"{stream.rate_hz:g}", f"{stream.bits_per_second / 1000:.1f}",
                f"{stream.share * 100:.1f}%",
            ]):
                table.setItem(row, column, QTableWidgetItem(str(text)))
        layout.addWidget(table, 1)
        layout.addWidget(QLabel(
            f"{len(budget.unrated)} enabled messages have no rate and are not "
            "costed (event-driven or on-demand traffic).", objectName="dim"))

    def page_build(self, layout):
        controls = QHBoxLayout()
        build_button = QPushButton("Build dialect XML", objectName="primary")
        build_button.clicked.connect(self.do_build)
        controls.addWidget(build_button)
        self.language_box = QComboBox()
        self.language_box.addItems(MAVGEN_LANGUAGES)
        controls.addWidget(self.language_box)
        generate = QPushButton("Build + mavgen")
        generate.clicked.connect(
            lambda: self.do_build(self.language_box.currentText())
        )
        controls.addWidget(generate)
        icd = QPushButton("Generate ICD")
        icd.clicked.connect(self.do_icd)
        controls.addWidget(icd)
        controls.addStretch(1)
        layout.addLayout(controls)

        counts = self.report.counts()
        cards = QHBoxLayout()
        cards.addWidget(self._card("Errors", counts["error"],
                                   "bad" if counts["error"] else "good"))
        cards.addWidget(self._card("Warnings", counts["warn"]))
        cards.addWidget(self._card("Notes", counts["info"]))
        cards.addStretch(1)
        layout.addLayout(cards)

        table = self._table(["Level", "Check", "Subject", "Detail"], stretch=3)
        for issue in self.report.issues:
            row = table.rowCount()
            table.insertRow(row)
            detail = issue.message + (f"  -> {issue.hint}" if issue.hint else "")
            for column, text in enumerate(
                [issue.level, issue.check, issue.subject, detail]
            ):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(
                    {"error": "#ef6d6d", "warn": "#e0a94b"}.get(
                        issue.level, "#8b93a3")))
                table.setItem(row, column, item)
        layout.addWidget(table, 1)

    # -- inspector --------------------------------------------------------

    def show_message(self, name: str):
        self.selected = name
        state = self.studio.resolution.states.get(name)
        if state is None:
            return
        custom = {m.name: m
                  for m in load_custom_dialect(self.studio.project).messages}
        message = custom.get(name) or self.studio.catalog.message(name)
        if message is None:
            return

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel(name, objectName="title")
        heading.setStyleSheet(
            f"color:{STATUS_COLOURS.get(state.status, '#dfe3ea')};")
        layout.addWidget(heading)

        facts = QFormLayout()
        facts.addRow("ID", QLabel(str(state.id)))
        facts.addRow("Origin", QLabel(f"{state.dialect}.xml ({state.origin})"))
        facts.addRow("Status", QLabel(state.status))
        facts.addRow("In profile", QLabel(
            ("ENABLED" if state.enabled else "disabled") + f"  -  {state.reason}"))
        facts.addRow("Capability", QLabel(state.capability_title or "-"))
        facts.addRow("Payload", QLabel(f"{message.payload_bytes} bytes"))
        layout.addLayout(facts)

        if message.description:
            description = QLabel(message.description, objectName="dim")
            description.setWordWrap(True)
            layout.addWidget(description)

        actions = QHBoxLayout()
        toggle = QPushButton(
            "Disable in this profile" if state.enabled
            else "Enable in this profile")
        toggle.setEnabled(not state.required)
        toggle.clicked.connect(
            lambda: self._toggle(name, not state.enabled)
        )
        actions.addWidget(toggle)
        if state.origin == "custom":
            edit = QPushButton("Edit")
            edit.clicked.connect(lambda: self._open_form(name))
            actions.addWidget(edit)
            delete = QPushButton("Delete", objectName="danger")
            delete.clicked.connect(lambda: self._delete(name))
            actions.addWidget(delete)
        layout.addLayout(actions)

        settings = QGroupBox("Profile settings")
        form = QFormLayout(settings)
        rate = QDoubleSpinBox()
        rate.setRange(0, 2000)
        rate.setDecimals(1)
        rate.setValue(state.rate_hz)
        tx = QLineEdit(",".join(state.tx))
        rx = QLineEdit(",".join(state.rx))
        priority = QComboBox()
        priority.addItems(["LOW", "NORMAL", "HIGH", "CRITICAL"])
        priority.setCurrentText(state.priority or "NORMAL")
        meta = self.metadata.get(name, {})
        interface = QLineEdit(meta.get("interface", ""))
        requirements = QLineEdit(", ".join(meta.get("requirements", [])))
        form.addRow("Rate (Hz)", rate)
        form.addRow("TX", tx)
        form.addRow("RX", rx)
        form.addRow("Priority", priority)
        form.addRow("MOSA interface", interface)
        form.addRow("Requirement ids", requirements)
        save = QPushButton("Save", objectName="primary")

        def do_save():
            override = self.studio.profile.messages.setdefault(
                name, MessageOverride())
            override.rate_hz = rate.value()
            override.tx = [t.strip() for t in tx.text().split(",") if t.strip()]
            override.rx = [r.strip() for r in rx.text().split(",") if r.strip()]
            override.priority = priority.currentText()
            self.studio.profile.save(self.studio.project)
            set_metadata(
                self.studio.project, name,
                interface=interface.text().strip() or None,
                requirements=[
                    r.strip() for r in requirements.text().split(",") if r.strip()
                ] or None,
            )
            self.status(f"Saved {name}")
            self.reload()

        save.clicked.connect(do_save)
        form.addRow("", save)
        layout.addWidget(settings)

        layout.addWidget(QLabel("FIELDS", objectName="sub"))
        fields = self._table(["#", "Field", "Type", "Units", "Enum"], stretch=1)
        for index, field in enumerate(message.fields, start=1):
            row = fields.rowCount()
            fields.insertRow(row)
            for column, text in enumerate([
                index, field.name + (" ext" if field.is_extension else ""),
                field.type, field.units or "-", field.enum or "-",
            ]):
                fields.setItem(row, column, QTableWidgetItem(str(text)))
        fields.setMinimumHeight(140)
        layout.addWidget(fields)

        layout.addWidget(QLabel("XML", objectName="sub"))
        xml = QPlainTextEdit("\n".join(message_xml(message, "")))
        xml.setObjectName("xml")
        xml.setReadOnly(True)
        xml.setMinimumHeight(160)
        layout.addWidget(xml)
        layout.addStretch(1)
        self.inspector.setWidget(panel)

    def set_preview(self, xml: str, errors: list[str], message_id: int = 0,
                    payload: int = 0):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel("Live check", objectName="title"))
        if errors:
            for error in errors:
                label = QLabel(f"- {error}", objectName="err")
                label.setWordWrap(True)
                layout.addWidget(label)
        else:
            layout.addWidget(QLabel(
                f"valid - id {message_id}, {payload} payload bytes",
                objectName="ok"))
        layout.addWidget(QLabel("XML PREVIEW", objectName="sub"))
        view = QPlainTextEdit(xml)
        view.setObjectName("xml")
        view.setReadOnly(True)
        layout.addWidget(view, 1)
        self.inspector.setWidget(panel)

    # -- form / actions ---------------------------------------------------

    def _open_form(self, existing: str):
        self.message_form.start(existing)
        self.stack.setCurrentWidget(self.message_form)

    def _form_saved(self, name: str):
        self.selected = name
        self.stack.setCurrentIndex(1)
        self.nav.setCurrentRow(1)
        self.reload()

    def _form_cancelled(self):
        self.stack.setCurrentIndex(self.nav.currentRow())
        if self.selected:
            self.show_message(self.selected)

    def _delete(self, name: str):
        answer = QMessageBox.question(
            self, "Delete custom message",
            f"Permanently delete {name} from "
            f"{self.studio.project.dialect.path}?\n\n"
            "Standard messages are never deleted - only custom ones.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            remove_message(self.studio.project, name)
        except DialectError as exc:
            QMessageBox.critical(self, "Cannot delete", str(exc))
            return
        self.selected = ""
        self.status(f"Removed {name}")
        self.reload()

    def do_build(self, language: str = ""):
        if self.report.errors:
            answer = QMessageBox.question(
                self, "Validation errors",
                f"{len(self.report.errors)} validation errors. Build anyway?")
            if answer != QMessageBox.Yes:
                self.select_section(7)
                return
        result = build_profile_dialect(self.studio.project, self.studio.catalog,
                                       self.studio.resolution)
        self.status(
            f"Wrote {result.dialect_path} - {result.message_count} messages, "
            f"{result.enum_count} enums, {result.command_count} commands")
        if not language:
            return
        output_dir = os.path.join(self.studio.project.build_dir, "generated",
                                  language.replace("+", "p"))
        self.status(f"Running mavgen ({language})...")
        self.generator = GeneratorThread(result.dialect_path, language, output_dir)
        self.generator.finished_with.connect(
            lambda ok, output: self._generated(ok, output, output_dir)
        )
        self.generator.start()

    def _generated(self, ok: bool, output: str, output_dir: str):
        if ok:
            self.status(f"mavgen OK -> {output_dir}")
        else:
            QMessageBox.critical(self, "mavgen failed", output[-2000:])

    def do_icd(self):
        written = write_icd(self.studio.project, self.studio.catalog,
                            self.studio.capability_set, self.studio.resolution)
        self.status("Wrote " + ", ".join(written))


def run(project_root: str = "uav", vehicle: str = "", profile: str = "",
        argv: list[str] | None = None) -> int:
    application = QApplication(argv if argv is not None else sys.argv[:1])
    application.setApplicationName("UAV MAVLink Studio")
    window = StudioWindow(project_root, vehicle, profile)
    window.show()
    return application.exec()
