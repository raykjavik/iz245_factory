"""Reusable sweep plot with SI frequency ticks, hover and scope-style A/B cursors.

Raw arrays and CSV files are never modified by display-unit conversion.
"""

from PySide6.QtGui import QFontMetricsF
from PySide6.QtGui import QColor
from dataclasses import dataclass
from html import escape
import os
os.environ.setdefault('PYQTGRAPH_QT_LIB','PySide6')
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from helpers import CollapsibleSection
from chart_style import APP_CURVE_COLORS, LIMIT_COLOR
from chart_ranges import data_x_range, clipped_x_range, visible_y_range, Y_MARGIN


def si_frequency(value):
    value=float(value)
    for scale,suffix in ((1e9,'G'),(1e6,'M'),(1e3,'k')):
        if abs(value)>=scale:
            return f'{value/scale:.5g}{suffix}'
    return f'{value:.5g}'


class LimitedLabelAxis(pg.AxisItem):
    """Keep minor grid ticks, but bound text count and pixel separation."""
    def __init__(self,*args,max_labels=7,min_label_spacing=80,**kwargs):
        super().__init__(*args,**kwargs)
        self.max_labels=max_labels
        self.min_label_spacing=min_label_spacing
        self.labelled_ticks=[]
        self.setStyle(hideOverlappingLabels=True)

    def format_value(self,value):
        return f'{value:.5g}'

    def tickValues(self,minVal,maxVal,size):
        generated=super().tickValues(minVal,maxVal,size)
        # Log-axis minor levels may repeat decade ticks from the major level.
        levels=[]
        seen=set()
        for spacing,values in generated:
            unique=[]
            for value in values:
                if value not in seen:
                    seen.add(value)
                    unique.append(value)
            levels.append((spacing,unique))
        self.labelled_ticks=[]
        if maxVal<=minVal or size<=0:
            return levels
        limit=max(1,min(self.max_labels,int(size/self.min_label_spacing)))
        font=self.style.get('tickFont') or QtWidgets.QApplication.font()
        metrics=QFontMetricsF(font)
        horizontal=self.orientation in ('top','bottom')
        chosen=[]
        for _,values in levels:
            candidates=list(values)
            # Prefer an even spread of major ticks when there are too many.
            if len(candidates)>limit:
                candidates=[candidates[i] for i in np.linspace(0,len(candidates)-1,limit,dtype=int)]
            for value in candidates:
                pixel=(value-minVal)/(maxVal-minVal)*size
                text=self.format_value(value)
                extent=metrics.horizontalAdvance(text) if horizontal else metrics.height()
                half=(max(extent,self.min_label_spacing-16)+16)/2
                if len(chosen)<limit:
                    # Explicit pairwise spacing also handles unequal label widths.
                    if all(abs(pixel-position)>=half+other_half for position,other_half in chosen):
                        chosen.append((pixel,half))
                        self.labelled_ticks.append(value)
        return levels

    def tickStrings(self,values,scale,spacing):
        allowed=set(self.labelled_ticks)
        return [self.format_value(value) if value in allowed else '' for value in values]


class FrequencyAxis(LimitedLabelAxis):
    def format_value(self,value):
        return si_frequency(10**value if self.logMode else value)


@dataclass
class Trace:
    x: np.ndarray
    y: np.ndarray
    unit: str
    reference_dbm: float | None
    live: bool = False
    display_unit: str | None = None
    display_offset_db: float | None = None
    color: str | None = None  # Optional explicit GUI color; otherwise assigned by curve identity.
    passed: bool | None = None
    color_key: str | None = None
    is_reference: bool = False


@dataclass
class FreeCursor:
    frequency_hz: float
    value: float
    unit: str
    reference_dbm: float


class SweepChart(QtWidgets.QWidget):
    def __init__(self,parent=None, *, title='Sweep measurements · 50 Ω',
                 frequency_label='Frequency', display_unit='dB', display_offset_db=0.0,
                 value_label=None, hover_enabled=True):
        super().__init__(parent)
        self.title=title
        self.hover_enabled=hover_enabled
        self.display_unit=display_unit
        self.display_offset_db=display_offset_db
        self.value_label=value_label
        self.traces={}
        self.items={}
        self._curve_colors={}
        self.markers={'A':None,'B':None}
        self.marker_items=[]
        self._marker_graphics={}
        self.armed=None
        self.user_navigated=False
        layout=QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        controls=QtWidgets.QHBoxLayout()
        self.scale=QtWidgets.QComboBox()
        self.scale.addItems(['Logarithmic','Linear'])
        controls.addWidget(self.scale)
        self.reset=QtWidgets.QPushButton('Reset view')
        controls.addWidget(self.reset)
        layout.addLayout(controls)
        self.cursor_section = CollapsibleSection('Cursors')
        marker_controls=QtWidgets.QHBoxLayout()
        self.cursor_mode = QtWidgets.QComboBox()
        self.cursor_mode.addItems(['Free position', 'Snap to measured point'])
        marker_controls.addWidget(self.cursor_mode)
        self.marker_buttons={}
        for name in ('A','B'):
            button=QtWidgets.QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda _,name=name:self.arm_marker(name))
            self.marker_buttons[name]=button
            marker_controls.addWidget(button)
        clear=QtWidgets.QPushButton('Clear cursors')
        clear.clicked.connect(self.clear_markers)
        marker_controls.addWidget(clear)
        marker_controls.addWidget(QtWidgets.QLabel('Arm A/B, then click the plot. Drag cursor lines to move.'))
        marker_controls.addStretch()
        self.cursor_section.content_layout.addLayout(marker_controls)
        self.plot=pg.PlotWidget(background='w',axisItems={'bottom':FrequencyAxis(orientation='bottom'),
                  'left':LimitedLabelAxis(orientation='left',max_labels=6,min_label_spacing=42)})
        self.plot.showGrid(x=True,y=True,alpha=.22)
        self.plot.setMenuEnabled(False)
        self.plot.getPlotItem().hideButtons()
        self.plot.setLabel('bottom',frequency_label,units='Hz')
        self.plot.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot.getAxis('left').enableAutoSIPrefix(False)
        for side in ('bottom','left'):
            self.plot.getAxis(side).setTextPen('#303030')
            self.plot.getAxis(side).setPen('#777777')
        self.legend=self.plot.addLegend(offset=(12,12))
        layout.addWidget(self.plot,1)
        self.hover_label=QtWidgets.QLabel('Hover over a curve for frequency and level.')
        self.hover_label.setWordWrap(True)
        self.hover_label.setVisible(hover_enabled)
        layout.addWidget(self.hover_label)
        self.cursor_table=QtWidgets.QTableWidget(3,3)
        self.cursor_table.setHorizontalHeaderLabels(['Cursor / curve','Frequency [Hz]','Value'])
        self.cursor_table.verticalHeader().hide()
        self.cursor_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.cursor_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cursor_table.setMaximumHeight(115)
        self.cursor_section.content_layout.addWidget(self.cursor_table)
        layout.addWidget(self.cursor_section)
        self.cross_x=pg.InfiniteLine(angle=90,pen=pg.mkPen('#888888',style=QtCore.Qt.PenStyle.DashLine))
        self.cross_y=pg.InfiniteLine(angle=0,pen=pg.mkPen('#888888',style=QtCore.Qt.PenStyle.DashLine))
        self.hover_point=pg.ScatterPlotItem(size=9,pen=pg.mkPen('#202020'),brush=pg.mkBrush('w'))
        self.tooltip=pg.TextItem(anchor=(0,1),fill=pg.mkBrush(255,255,255,235),border=pg.mkPen('#888888'))
        for item in (self.cross_x,self.cross_y,self.hover_point,self.tooltip):
            self._make_passive(item)
            item.setZValue(30)
            self.plot.addItem(item,ignoreBounds=True)
            item.hide()
        if self.hover_enabled:
            self.plot.scene().sigMouseMoved.connect(self._hover)
        self.plot.scene().sigMouseClicked.connect(self._click)
        self.plot.getViewBox().sigRangeChangedManually.connect(self._navigated)
        self.plot.getViewBox().sigXRangeChanged.connect(self._autoscale_visible_y)
        self.scale.currentIndexChanged.connect(self._scale_changed)
        self.reset.clicked.connect(self.reset_view)
        self.cursor_mode.currentIndexChanged.connect(self._update_interaction_mode)
        self.cursor_section.toggle_button.toggled.connect(self._cursor_section_toggled)
        self._scale_changed()
        self._update_table()

    @staticmethod
    def _make_passive(item):
        # Qt and pyqtgraph have separate event paths. Disabling decorations
        # also keeps GraphicsScene from dispatching custom click/drag events.
        item.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        item.setAcceptHoverEvents(False)
        item.setEnabled(False)
        for child in item.childItems():
            child.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            child.setAcceptHoverEvents(False)
            child.setEnabled(False)

    def _update_interaction_mode(self):
        armed=self.armed is not None
        self.plot.viewport().setCursor(QtCore.Qt.CursorShape.CrossCursor if armed
                                       else QtCore.Qt.CursorShape.ArrowCursor)
        if armed:
            self._hide_hover()
            action = 'place freely' if self.cursor_mode.currentIndex() == 0 else 'snap to a measured point'
            self.hover_label.setText(f'Cursor {self.armed}: click inside the plot to {action}.')
        for label,button in self.marker_buttons.items():
            button.setChecked(label==self.armed)
        for label, graphics in self._marker_graphics.items():
            graphics['line'].setMovable(not armed)
            graphics['line'].setEnabled(not armed)
            free = isinstance(self.markers[label], FreeCursor)
            graphics['hline'].setMovable(free and not armed)
            graphics['hline'].setEnabled(free and not armed)

    def _cursor_section_toggled(self, expanded):
        if not expanded:
            self.armed = None
            self._hide_hover()
        self._update_interaction_mode()

    @property
    def log_x(self):
        return self.scale.currentIndex()==0

    def _navigated(self,*_):
        self.user_navigated=True

    def _scale_changed(self,*_):
        self.plot.setLogMode(x=self.log_x,y=False)
        self._render()
        self.reset_view()

    def _trace_unit(self, trace):
        return trace.display_unit if trace.display_unit is not None else self.display_unit

    def _trace_offset(self, trace):
        return trace.display_offset_db if trace.display_offset_db is not None else self.display_offset_db

    def _axis_unit(self):
        units={self._trace_unit(trace) for trace in self.traces.values()}
        return next(iter(units)) if len(units)==1 else 'mixed units' if units else self.display_unit

    def converted(self,trace):
        """Apply only the view offset chosen by cfg_*. Never change raw arrays."""
        offset=self._trace_offset(trace)
        return np.asarray(trace.y)+offset if offset else np.asarray(trace.y)

    def set_traces(self,traces):
        """traces maps stable curve names to Trace objects in Hz/native units."""
        self.traces=dict(traces)
        for marker,state in self.markers.items():
            if state is not None and not isinstance(state, FreeCursor) and state[0] not in self.traces:
                self.markers[marker]=None
        self._render()

    def _render(self,*_):
        for name in set(self.items) - set(self.traces):
            item=self.items.pop(name)
            self.legend.removeItem(item)
            self.plot.removeItem(item)
        for index,(name,trace) in enumerate(self.traces.items()):
            y=self.converted(trace)
            style = (QtCore.Qt.PenStyle.DashDotLine if trace.is_reference else
                     QtCore.Qt.PenStyle.DashLine if trace.live else QtCore.Qt.PenStyle.SolidLine)
            pen=pg.mkPen(trace.color or self._curve_color(trace.color_key or name),width=2,style=style)
            if name in self.items:
                self.items[name].setData(trace.x,y)
                self.items[name].setPen(pen)
            else:
                self.items[name]=self.plot.plot(trace.x,y,pen=pen,name=escape(name),
                                                 connect='finite',antialias=True)
            self.items[name].setOpacity(.5 if trace.is_reference else 1.)
        self.plot.setLabel('left',self.value_label or 'Level',units=self._axis_unit())
        self.plot.setTitle(self.title,color='#303030')
        self._draw_markers()
        self._hide_hover()
        if not self.user_navigated:
            self._apply_x_limits()
        self._autoscale_visible_y()

    def _curve_color(self, name):
        # A saved result and its live preview represent the same measurement.
        key = name.replace(' (live)', '')
        if key not in self._curve_colors:
            index = len(self._curve_colors)
            if index < len(APP_CURVE_COLORS):
                color = APP_CURVE_COLORS[index]
            else:
                color = QColor.fromHsvF((index*.61803398875) % 1., .75, .65).name()
            self._curve_colors[key] = color
        return self._curve_colors[key]

    def _curves(self):
        return [(np.asarray(trace.x), self.converted(trace)) for trace in self.traces.values()]

    def _autoscale_visible_y(self, *_):
        """Fit visible curve values, including interpolated viewport edges.

        Curves contain ordered frequency arrays. Search their visible slice
        instead of scanning a full spectrum on every mouse movement.
        """
        view = self.plot.getViewBox()
        low, high = view.viewRange()[0]
        if self.log_x:
            low, high = 10**low, 10**high
        bounds = visible_y_range(self._curves(), low, high, log_x=self.log_x,
            limits=[line.value() for line in getattr(self, '_limit_items', [])])
        if bounds is not None:
            view.setYRange(*bounds, padding=Y_MARGIN)

    def set_limits(self, limits):
        """Named horizontal limits, already in display units. Excluded from hover."""
        for item in getattr(self, '_limit_items', []):
            self.plot.removeItem(item)
        self._limit_items = []
        for label, value in limits:
            line = pg.InfiniteLine(pos=value,angle=0,movable=False,
                pen=pg.mkPen(LIMIT_COLOR,width=1.2,style=QtCore.Qt.PenStyle.DashLine),
                label=label,labelOpts={'position':.98,'anchors':[(1,0),(1,1)],'color':LIMIT_COLOR})
            self.plot.addItem(line)
            self._limit_items.append(line)
        self._autoscale_visible_y()

    def set_vertical_limits(self, positions):
        """Filter edges in Hz. They are not data curves or cursor targets."""
        for line in getattr(self,'_vertical_limit_items',[]):
            self.plot.removeItem(line)
        self._vertical_limit_items = []
        for position in sorted(set(positions)):
            line = pg.InfiniteLine(pos=self._position(position),angle=90,movable=False,
                pen=pg.mkPen(LIMIT_COLOR,width=1.2,style=QtCore.Qt.PenStyle.DashLine))
            self.plot.addItem(line)
            self._vertical_limit_items.append(line)

    def set_x_limits(self, limits):
        limits = tuple(limits) if limits is not None else None
        changed = limits != getattr(self,'_configured_x_limits',None)
        self._configured_x_limits = limits
        if changed:
            self.user_navigated = False
        if not self.user_navigated:
            self._apply_x_limits()

    def _apply_x_limits(self):
        # Disable pyqtgraph's deferred auto-range: its item/label bounds and
        # padding can otherwise overwrite the visible-data y fit after painting.
        self.plot.disableAutoRange()
        limits = clipped_x_range(data_x_range(self._curves(), log_x=self.log_x),
                                 getattr(self,'_configured_x_limits',None))
        if limits is not None:
            low,high = (self._position(value) for value in limits)
            self.plot.setXRange(low,high,padding=0)
        self._autoscale_visible_y()

    def reset_view(self):
        self.user_navigated=False
        self._apply_x_limits()
        self._autoscale_visible_y()

    def _position(self,x):
        return np.log10(x) if self.log_x else x

    def nearest(self,scene_pos,curve_name=None,max_pixels=None):
        view=self.plot.getViewBox()
        mouse=view.mapSceneToView(scene_pos)
        candidates=[]
        for name,trace in self.traces.items():
            if curve_name is not None and name!=curve_name:
                continue
            xs=self._position(trace.x)
            ys=self.converted(trace)
            index=int(np.searchsorted(xs,mouse.x()))
            for i in set((max(0,index-1),min(len(xs)-1,index))):
                if i<0 or i>=len(xs) or not np.isfinite(xs[i]+ys[i]):
                    continue
                point=view.mapViewToScene(QtCore.QPointF(float(xs[i]),float(ys[i])))
                distance=(point.x()-scene_pos.x())**2+(point.y()-scene_pos.y())**2
                candidates.append((distance,name,i,float(xs[i]),float(ys[i])))
        if not candidates:
            return None
        best=min(candidates)
        if max_pixels is not None and best[0]>max_pixels**2:
            return None
        return best[1:]

    def _hide_hover(self):
        self.hover_label.setText('Hover over a curve for frequency and level.')
        for item in (self.cross_x,self.cross_y,self.hover_point,self.tooltip):
            item.hide()

    def _hover(self,pos):
        if not self.hover_enabled or self.armed is not None:
            return
        if not self.plot.getViewBox().sceneBoundingRect().contains(pos):
            self._hide_hover(); return
        point=self.nearest(pos,max_pixels=35)
        if point is None:
            self._hide_hover(); return
        name,index,x,y=point
        frequency=float(self.traces[name].x[index])
        label=f'{name} · {si_frequency(frequency)} Hz · {y:.5f} {self._trace_unit(self.traces[name])}'
        self.hover_label.setText(label)
        self.cross_x.setPos(x); self.cross_y.setPos(y)
        self.hover_point.setData([x],[y])
        self.tooltip.setHtml('<span style="color:#202020">'+escape(label)+'</span>')
        middle=sum(self.plot.getViewBox().viewRange()[0])/2
        self.tooltip.setAnchor((1,1) if x>middle else (0,1))
        self.tooltip.setPos(x,y)
        for item in (self.cross_x,self.cross_y,self.hover_point,self.tooltip):
            item.show()

    def arm_marker(self,name):
        if self.markers[name] is not None:
            self.markers[name]=None
            self.armed=None
            self._draw_markers()
        else:
            self.armed=None if self.armed==name else name
        self._update_interaction_mode()

    def _click(self,event):
        if self.armed is None or event.button()!=QtCore.Qt.MouseButton.LeftButton:
            return
        if not self.plot.getViewBox().sceneBoundingRect().contains(event.scenePos()):
            return
        if self.cursor_mode.currentIndex() == 0:
            position = self.plot.getViewBox().mapSceneToView(event.scenePos())
            frequency = 10**position.x() if self.log_x else position.x()
            self.markers[self.armed] = FreeCursor(float(frequency), float(position.y()),
                                                  self._axis_unit(), 0.0)
        else:
            # Snap mode still accepts clicks far from a measured point.
            point = self.nearest(event.scenePos())
            if point is None:
                return
            self.markers[self.armed] = (point[0], point[1])
        self.armed=None
        self._draw_markers()
        self._update_interaction_mode()
        event.accept()

    def place_marker(self,label,name,index):
        """Programmatic cursor placement for integrations/tests."""
        self.markers[label]=(name,index)
        self._draw_markers()

    def _drag_marker(self,label,line):
        state = self.markers[label]
        if isinstance(state, FreeCursor):
            state.frequency_hz = float(10**line.value() if self.log_x else line.value())
            self._draw_markers()
            return
        name,index=self.markers[label]
        trace=self.traces[name]
        x=self._position(trace.x)
        index=int(np.argmin(np.abs(x-line.value())))
        self.markers[label]=(name,index)
        self._draw_markers()

    def _drag_free_y(self, label, line):
        state = self.markers[label]
        if isinstance(state, FreeCursor):
            state.value = float(line.value())
            state.unit = self._axis_unit()
            self._draw_markers()

    def _marker_value(self, state):
        if isinstance(state, FreeCursor):
            return 'Free position', state.frequency_hz, state.value
        name, index = state
        trace = self.traces[name]
        return name, float(trace.x[index]), float(trace.y[index])+self._trace_offset(trace)

    def _draw_markers(self):
        # Retain graphics during live updates so an in-progress drag keeps its
        # mouse grab. Only remove them when a cursor or its curve disappears.
        for label,state in self.markers.items():
            if state is not None and not isinstance(state, FreeCursor):
                name,index=state
                trace=self.traces.get(name)
                if trace is None or index>=len(trace.x):
                    self.markers[label]=state=None
            if state is None:
                for item in self._marker_graphics.pop(label,{}).values():
                    self.plot.removeItem(item)
                continue
            name, frequency, y = self._marker_value(state)
            x = float(self._position(frequency))
            if label not in self._marker_graphics:
                color='#b88600' if label=='A' else '#c62828'
                line=pg.InfiniteLine(pos=x,angle=90,movable=True,pen=pg.mkPen(color,width=1.5))
                line.sigPositionChangeFinished.connect(lambda line,label=label:self._drag_marker(label,line))
                hline=pg.InfiniteLine(pos=y,angle=0,pen=pg.mkPen(color,style=QtCore.Qt.PenStyle.DotLine))
                hline.sigPositionChangeFinished.connect(lambda line,label=label:self._drag_free_y(label,line))
                text=pg.TextItem(label,color=color,anchor=(0,1))
                point=pg.ScatterPlotItem(symbol='+',size=14,pen=pg.mkPen(color,width=2))
                graphics=dict(line=line,hline=hline,text=text,point=point)
                for key,item in graphics.items():
                    if key not in ('line', 'hline'):
                        self._make_passive(item)
                    item.setZValue(20)
                    self.plot.addItem(item,ignoreBounds=True)
                self._marker_graphics[label]=graphics
            graphics=self._marker_graphics[label]
            if not graphics['line'].moving:
                graphics['line'].setPos(x)
            if not graphics['hline'].moving:
                graphics['hline'].setPos(y)
            graphics['text'].setPos(x,y)
            graphics['point'].setData([x],[y])
        self.marker_items=[item for graphics in self._marker_graphics.values() for item in graphics.values()]
        self._update_interaction_mode()
        self._update_table()

    def clear_markers(self):
        self.markers={'A':None,'B':None}; self.armed=None
        self._draw_markers()
        self._update_interaction_mode()

    def _update_table(self):
        values=[]
        units=[]
        for label in ('A','B'):
            state=self.markers[label]
            values.append(None if state is None else self._marker_value(state))
            units.append(state.unit if isinstance(state,FreeCursor) else
                         self._trace_unit(self.traces[state[0]]) if state is not None else '')
        for row,(label,value,unit) in enumerate(zip(('A','B'),values,units)):
            texts=[label+' · '+value[0],si_frequency(value[1]),f'{value[2]:.6g} {unit}'] if value else [label,'—','—']
            for col,text in enumerate(texts):self.cursor_table.setItem(row,col,QtWidgets.QTableWidgetItem(text))
        a,b=values
        delta=f'{b[2]-a[2]:.6g} dB' if a and b and units[0]==units[1] else '—'
        texts=['B − A',si_frequency(b[1]-a[1]),delta] if a and b else ['B − A','—','—']
        for col,text in enumerate(texts):self.cursor_table.setItem(2,col,QtWidgets.QTableWidgetItem(text))
