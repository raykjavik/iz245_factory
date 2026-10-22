"""Project menu actions, dirty-state handling, and report commands."""
from pathlib import Path
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox
from project import FactoryProject, render_reports


class ProjectMenu(QObject):
    def __init__(self, window, project_tab, workflow_tabs):
        super().__init__(window)
        self.window = window
        self.project_tab = project_tab
        self.workflow_tabs = workflow_tabs
        self.project = None
        self.dirty = False
        project_menu = window.menuBar().addMenu("&Project")
        self._action(project_menu, "&New", self.new_project, QKeySequence.StandardKey.New)
        self._action(project_menu, "&Open", self.open_project, QKeySequence.StandardKey.Open)
        self.save_action = self._action(project_menu, "&Save", self.save_project, QKeySequence.StandardKey.Save)
        report_menu = window.menuBar().addMenu("&Report")
        self.regenerate_action = self._action(report_menu, "&Regenerate", self.regenerate_report)
        self.open_report_action = self._action(report_menu, "&Open", self.open_report)
        project_tab.changed.connect(self.mark_dirty)
        self._update()

    def _action(self, menu, label, callback, shortcut=None):
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _error(self, title, exc):
        QMessageBox.critical(self.window, title, str(exc))

    def _update(self):
        for action in (self.save_action, self.regenerate_action, self.open_report_action):
            action.setEnabled(self.project is not None)
        name = self.project.name if self.project else "No project"
        self.window.setWindowTitle(f"{'*' if self.dirty else ''}{name} — Receiver calibration")

    def mark_dirty(self):
        self.dirty = True
        self._update()

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self.window, "Unsaved changes", "Save project changes before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def _activate(self, project):
        self.project = project
        self.project_tab.load_project(project)
        for tab in self.workflow_tabs:
            tab.load_project(project)
        self.dirty = False
        self._update()

    def new_project(self):
        if not self.confirm_discard():
            return
        filename, _ = QFileDialog.getSaveFileName(self.window, "New project", "", "Projects (*.prj)")
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".prj":
            path = path.with_suffix(".prj")
        if path.exists():
            answer = QMessageBox.question(self.window, "Replace project", f"Replace {path.name}?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            project = FactoryProject.new_project(path)
            project.save()
            self._activate(project)
        except Exception as exc:
            self._error("Cannot create project", exc)

    def open_project(self):
        if not self.confirm_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(self.window, "Open project", "", "Projects (*.prj)")
        if not filename:
            return
        try:
            self._activate(FactoryProject.open_project(Path(filename)))
        except Exception as exc:
            self._error("Cannot open project", exc)

    def save_project(self):
        if self.project is None:
            return False
        try:
            self.project.save()
        except Exception as exc:
            self._error("Cannot save project", exc)
            return False
        self.dirty = False
        self._update()
        self.window.statusBar().showMessage("Project saved", 4000)
        return True

    def regenerate_report(self):
        if self.project is None or not self.save_project():
            return
        try:
            path = render_reports(self.project)
            self.window.statusBar().showMessage(f"Report generated: {path}", 6000)
        except Exception as exc:
            self._error("Cannot generate report", exc)

    def open_report(self):
        if self.project is None:
            return
        path = self.project.report_file
        if not path.is_file():
            QMessageBox.information(self.window, "Report unavailable", "Use Report → Regenerate first.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self._error("Cannot open report", "No application could open the .docx report.")
