#!/usr/bin/env python3
import sys
import time
import math

from matplotlib.backends.qt_compat import QtWidgets, QtCore, QtGui


class SineDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowTitle("Sine Wave")

        btns = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        
        
        self.buttonBox = QtWidgets.QDialogButtonBox(btns)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.layout = QtWidgets.QFormLayout()
        message = QtWidgets.QLabel("Parameters for Sine Wave")

        self.frequency_edit = QtWidgets.QLineEdit()
        self.phase_edit = QtWidgets.QLineEdit()

        self.frequency_edit.setValidator(QtGui.QDoubleValidator(0, 2e9, 5))
        self.frequency_edit.setText(f"128e6")
        
        self.phase_edit.setValidator(QtGui.QDoubleValidator(-360, 360, 5))
        self.phase_edit.setText("0.0")
        
        self.layout.addRow("Frequency", self.frequency_edit)
        self.layout.addRow("Phase", self.phase_edit)
        
        self.layout.addWidget(message)
        self.layout.addWidget(self.buttonBox)

        self.setLayout(self.layout)

    def get_frequency(self):
        return float(self.frequency_edit.text())
        
    def get_phase(self):
        return float(self.phase_edit.text())
