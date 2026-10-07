#image_drop_list.py
# GUI for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
#
import os
# PyQt6 imports
from PyQt6.QtGui     import QIcon 
from PyQt6.QtWidgets import QListWidget, QListWidgetItem
from PyQt6.QtCore    import pyqtSignal, QSize, Qt

class DropWidget(QListWidget):
    images_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(100, 100))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSpacing(10)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.images_dropped.emit(paths)
        event.acceptProposedAction()

    def add_images(self, paths):
        for path in paths:
            item = QListWidgetItem(QIcon(path), os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.addItem(item)
