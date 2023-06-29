import sys
import time
import math

import click

import asyncio
from aiohttp_xmlrpc.client import ServerProxy

import numpy as np
from numpy.lib import format as npf

from matplotlib.backends.qt_compat import QtWidgets, QtCore
from matplotlib.backends.backend_qtagg import (
    FigureCanvas, NavigationToolbar2QT as NavigationToolbar)
from matplotlib.figure import Figure
from multiprocessing import Process, Queue

import qasync

#from xmlrpc.client import ServerProxy

from .sine_dialog import SineDialog
from .samples import SampleBuffer, UpdateWorker, TaskGroup

Freq = float

                
class GraphPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QtWidgets.QGridLayout()

        self.canvases = []
        self.axes = []
        
        for row in range(2):
            for col in range(4):
                canvas = FigureCanvas(Figure(figsize=(5, 3)))
                self.canvases.append(canvas)

                self.axes.append(canvas.figure.subplots())
                
                self.layout.addWidget(canvas, row, col)
                
        self.setLayout(self.layout)
        
    def update(self):
        self.plot_data()
        
        for c in self.canvases:
            c.draw()

        
class ScopePanel(GraphPanel):
    def __init__(self, buffers, parent=None):
        super().__init__(parent)

        self.buffers = buffers
        
        self.reals = []
        self.imags = []

        
        for ax in self.axes:
            ax.set_ylim([-1, 1])
            ax.set_xlim([0, 1e-9])
            ax.grid(True)

            replt, = ax.plot([0, 1], [0, 0])
            implt, = ax.plot([0, 1], [0, 0])

            self.reals.append(replt)
            self.imags.append(implt)
        
    def plot_data(self):
        for ax, re, im, buf in zip(self.axes, self.reals, self.imags, self.buffers):
            ax.set_xlim(0, buf.t[-1])
            ax.set_xbound(0, buf.t[-1])
        
            re.set_data(buf.t, np.real(buf.samples))
            im.set_data(buf.t, np.imag(buf.samples))
        
class SpectrumPanel(GraphPanel):
    def __init__(self, buffers, parent=None):
        super().__init__(parent)

        self.buffers = buffers

        self.plots = []
        
        for ax in self.axes:
            ax.set_ylim([-60, 0])
            ax.grid(True)
            p, = ax.plot([0, 1], [-60, -60])
            self.plots.append(p)

    def plot_data(self):
        for ax, p, buf in zip(self.axes, self.plots, self.buffers):
            ax.set_xlim((buf.f[0], buf.f[-1]))
            p.set_data(buf.f, buf.dB)

            
class IQPanel(GraphPanel):
    def __init__(self, buffers, parent=None):
        super().__init__(parent)

        self.buffers = buffers

        self.plots = []

        for ax in self.axes:
            ax.set_xlim([-1, 1])
            ax.set_ylim([-1, 1])
            ax.grid(True)
            
            p, = ax.plot([0, 0], [0, 0], marker='.', ls='')
            self.plots.append(p)

    def plot_data(self):
        for plot, buf in zip(self.plots, self.buffers):
            plot.set_data(np.real(buf.samples), np.imag(buf.samples))        

class MonitorTabs(QtWidgets.QTabWidget):
    def __init__(self, parent, worker):
        super().__init__(parent)
        self.worker = worker
        
        self.setup_panels()

        self.currentChanged.connect(self.onPageChange)


    def onPageChange(self, x):
        self.currentWidget().update()
    
    def setup_panels(self):
        self.tabs = QtWidgets.QTabWidget()

        self.scope = ScopePanel(self.worker.input_samples)
        self.spectrum = SpectrumPanel(self.worker.input_samples)
        self.IQ = IQPanel(self.worker.input_samples)
        self.output_scope = ScopePanel(self.worker.output_samples)
            
        self.addTab(self.spectrum, "Spectrum")
        self.addTab(self.scope, "Scope")
        self.addTab(self.IQ, "IQ")
        self.addTab(self.output_scope, "Output Scope")

    def update_panels(self):
        self.currentWidget().update()
        
    def send_sine(self):
        dlg = SineDialog(self)
        
        if dlg.exec():
            print("Changing sine parameters")
            
            async def update_sine():
                tasks = [ buf.fill_sine(dlg.get_frequency(), dlg.get_phase()) for buf in self.worker.output_samples ]
                asyncio.gather(*tasks)

            asyncio.create_task(update_sine())

    def send_dc(self):
        async def update_dc():
            tasks = [ buf.fill_dc(1.0) for buf in self.worker.output_samples ]
            asyncio.gather(*tasks)
            
        asyncio.create_task(update_dc())


    def send_id(self):
        async def update_id():
            tasks = [ buf.fill_sine(30.0e6 * (i + 1), 0) for i, buf in enumerate(self.worker.output_samples) ]
            asyncio.gather(*tasks)

        asyncio.create_task(update_id())
        
                
class ApplicationWindow(QtWidgets.QMainWindow):
    def __init__(self, worker):
        super().__init__()

        self.worker = worker
        
        self.monitor_tabs = MonitorTabs(self, worker)
        
        self._main = QtWidgets.QWidget()
        self.setCentralWidget(self.monitor_tabs)

        self.setup_menu()
            
        self.worker.data_ready.connect(self.monitor_tabs.update_panels)

    def setup_menu(self):
        self.sineAction = QtWidgets.QAction("&Sine", self)
        self.dcAction = QtWidgets.QAction("&DC", self)
        self.idAction = QtWidgets.QAction("&ID", self)
                
        menu_bar = self.menuBar()
        self.setMenuBar(menu_bar)

        self.signal_menu = menu_bar.addMenu("Signal")

        self.signal_menu.addAction(self.sineAction)
        self.signal_menu.addAction(self.dcAction)
        self.signal_menu.addAction(self.idAction)

        self.sineAction.triggered.connect(self.monitor_tabs.send_sine)
        self.dcAction.triggered.connect(self.monitor_tabs.send_dc)
        self.idAction.triggered.connect(self.monitor_tabs.send_id)

async def pirpy_main(server_uri):
    qapp = QtWidgets.QApplication.instance()

    worker = UpdateWorker(qapp, server_uri)

    task = worker.start()
    
    loop = asyncio.get_event_loop()
    future = asyncio.Future()
    
    app = ApplicationWindow(worker)

    def close_application():
        worker.stop()
        future.cancel()
    
    qapp.aboutToQuit.connect(close_application)
    
    app.show()
    app.activateWindow()
    app.raise_()

    await future

    return True

    
@click.command()
@click.argument('server_uri', type=str)
def pirpy(server_uri):
    try:
        qasync.run(pirpy_main(server_uri))
    except asyncio.exceptions.CancelledError:
        sys.exit(0)
