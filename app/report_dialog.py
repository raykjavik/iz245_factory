"""Generate reports in a worker while a modal busy dialog blocks app actions."""
from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout
from report import render_reports


class ReportWorker(QThread):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.path = None
        self.error = None

    def run(self):
        try:
            self.path = render_reports(self.project)
        except Exception as exc:
            self.error = exc


class ReportDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Generating report')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(440)
        self.setCursor(Qt.CursorShape.WaitCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = QLabel('Generating report…')
        font = title.font()
        font.setBold(True)
        font.setPointSize(12)
        title.setFont(font)
        layout.addWidget(title)
        message = QLabel('Preparing the document, charts and results.\n'
                         'This may take a while. Please wait until it finishes.')
        message.setWordWrap(True)
        layout.addWidget(message)
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(progress)
        self.worker = ReportWorker(project, self)
        self.worker.finished.connect(self.accept)

    def reject(self):
        # Esc must not dismiss the blocker while its worker is writing a report.
        pass

    def closeEvent(self, event):
        if self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)

    def generate(self):
        # Paint the notification before starting any report processing.
        self.show()
        self.repaint()
        QTimer.singleShot(0, self.worker.start)
        self.exec()
        self.worker.wait()
        if self.worker.error is not None:
            raise self.worker.error
        return self.worker.path
