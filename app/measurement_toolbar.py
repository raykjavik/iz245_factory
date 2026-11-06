"""Run controls always target the active measurement, regardless of selected tab."""
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolBar, QLabel


class MeasurementToolbar(QToolBar):
    def __init__(self,pages,parent=None):
        super().__init__('Measurement controls',parent)
        self.setObjectName('measurementControls')
        self.pages=pages
        self.pause_action=QAction('Pause',self)
        self.resume_action=QAction('Resume',self)
        self.abort_action=QAction('Abort',self)
        for action,method in ((self.pause_action,'pause_measurement'),
                              (self.resume_action,'resume_measurement'),
                              (self.abort_action,'abort_measurement')):
            action.triggered.connect(lambda _,method=method:self._invoke(method))
            self.addAction(action)
        self.addSeparator()
        self.state=QLabel('No measurement running')
        self.addWidget(self.state)
        for page in pages:
            page.busy_changed.connect(self.refresh)
            page.control_state_changed.connect(self.refresh)
        self.refresh()

    def active(self):
        return next((p for p in self.pages if p.busy),None)

    def _invoke(self,method):
        page=self.active()
        if page:
            getattr(page,method)()
        self.refresh()

    def refresh(self,*_):
        page=self.active()
        running=page is not None
        thread=page._thread if running else None
        cancelled=running and thread.cancel.is_set()
        paused=running and thread.pause_event.is_set()
        can_pause=running and thread.job.pausable and not cancelled
        self.pause_action.setEnabled(bool(can_pause and not paused))
        self.resume_action.setEnabled(bool(can_pause and paused))
        self.abort_action.setEnabled(bool(running and not cancelled))
        self.state.setText(('Aborting' if cancelled else 'Paused / pause requested' if paused else
                            'Running: '+thread.action) if running else 'No measurement running')
