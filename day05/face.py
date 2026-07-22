# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'face.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QLabel, QPushButton, QSizePolicy,
    QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(643, 568)
        self.openButton = QPushButton(Form)
        self.openButton.setObjectName(u"openButton")
        self.openButton.setGeometry(QRect(530, 130, 111, 71))
        self.saveButton = QPushButton(Form)
        self.saveButton.setObjectName(u"saveButton")
        self.saveButton.setGeometry(QRect(530, 230, 111, 71))
        self.recogButton = QPushButton(Form)
        self.recogButton.setObjectName(u"recogButton")
        self.recogButton.setGeometry(QRect(530, 330, 111, 71))
        self.cam = QLabel(Form)
        self.cam.setObjectName(u"cam")
        self.cam.setGeometry(QRect(30, 90, 471, 381))
        self.cam.setStyleSheet(u"background-color: rgb(0, 85, 0);")
        self.label = QLabel(Form)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(190, 30, 321, 41))
        font = QFont()
        font.setPointSize(20)
        self.label.setFont(font)
        self.persionButton = QPushButton(Form)
        self.persionButton.setObjectName(u"persionButton")
        self.persionButton.setGeometry(QRect(530, 430, 111, 71))

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.openButton.setText(QCoreApplication.translate("Form", u"\u6253\u5f00", None))
        self.saveButton.setText(QCoreApplication.translate("Form", u"\u4fdd\u5b58", None))
        self.recogButton.setText(QCoreApplication.translate("Form", u"\u8bc6\u522b", None))
        self.cam.setText("")
        self.label.setText(QCoreApplication.translate("Form", u"\u4eba\u8138\u8bc6\u522b", None))
        self.persionButton.setText(QCoreApplication.translate("Form", u"\u6d3b\u4f53\u68c0\u6d4b", None))
    # retranslateUi

