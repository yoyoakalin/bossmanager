import sys
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QLabel, QTextEdit, QComboBox,
                            QSpinBox, QGroupBox, QMessageBox, QRubberBand)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QRect, QPoint
from PyQt5.QtGui import QPainter, QColor, QPen
from text_recognition import click_on_text, set_recognition_area
import pyautogui
from pynput import mouse
import json
import os
from PIL import Image
import warnings
import numpy as np

class RecognitionThread(QThread):
    update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, boss_text, interval, down_coordinate, area_change_reward, area_boss, area_open):
        super().__init__()
        self.boss_text = boss_text
        self.interval = interval
        self.down_coordinate = down_coordinate
        self.area_change_reward = area_change_reward
        self.area_boss = area_boss
        self.area_open = area_open
        self.running = True

    def run(self):
        while self.running:
            # 1. 识别"更改奖励"
            found, msg = click_on_text("更改奖励", self.area_change_reward)
            self.update_signal.emit(msg)
            if not found:
                time.sleep(self.interval)
                continue

            # 2. 点击后等待0.5秒，识别boss
            time.sleep(0.5)
            retry = 0
            boss_found = False
            while retry < 3 and self.running:
                found, msg = click_on_text(self.boss_text, self.area_boss)
                self.update_signal.emit(msg)
                if found:
                    boss_found = True
                    break
                else:
                    if self.down_coordinate:
                        pyautogui.click(self.down_coordinate[0], self.down_coordinate[1])
                        self.update_signal.emit("未识别到boss，点击下滑重试")
                    else:
                        self.update_signal.emit("未设置下滑坐标，无法下滑")
                        break
                    time.sleep(0.5)
                    retry += 1
            if not boss_found:
                self.update_signal.emit("多次未识别到boss，停止识别")
                break

            # 3. 等待1秒，识别"打开"
            time.sleep(1)
            found, msg = click_on_text("打开", self.area_open)
            self.update_signal.emit(msg)
            if not found:
                self.update_signal.emit("未识别到'打开'，停止识别")
                break

            time.sleep(self.interval)
        self.finished_signal.emit()

    def stop(self):
        self.running = False

class SelectionOverlay(QWidget):
    area_selected = pyqtSignal(QRect)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.rubberBand = None
        self.origin = QPoint()
    def showFullScreen(self):
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        super().showFullScreen()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 128))
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.pos()
            if not self.rubberBand:
                self.rubberBand = QRubberBand(QRubberBand.Rectangle, self)
            self.rubberBand.setGeometry(QRect(self.origin, QPoint()))
            self.rubberBand.show()
        elif event.button() == Qt.RightButton:
            # 右键取消
            self.close()
            if self.parent():
                self.parent().show()
    def mouseMoveEvent(self, event):
        if self.rubberBand:
            self.rubberBand.setGeometry(QRect(self.origin, event.pos()).normalized())
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rubberBand:
            rect = self.rubberBand.geometry()
            self.rubberBand.hide()
            global_rect = QRect(self.mapToGlobal(rect.topLeft()), self.mapToGlobal(rect.bottomRight()))
            self.area_selected.emit(global_rect)
            self.close()

class AreaSelector:
    @staticmethod
    def select_area(parent=None):
        try:
            overlay = SelectionOverlay(parent)
            if parent:
                overlay.area_selected.connect(parent.on_area_selected)
            overlay.showFullScreen()
            return overlay
        except Exception as e:
            print(f"选择区域时出错: {e}")
            return None

class CoordinateOverlay(QWidget):
    coordinate_selected = pyqtSignal(int, int)
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.cursor_pos = QPoint(-1, -1)

    def showFullScreen(self):
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        super().showFullScreen()

    def paintEvent(self, event):
        painter = QPainter(self)
        # 半透明遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        # 画十字线
        if self.cursor_pos.x() >= 0 and self.cursor_pos.y() >= 0:
            pen = QPen(QColor(255, 0, 0, 180), 1, Qt.SolidLine)
            painter.setPen(pen)
            painter.drawLine(self.cursor_pos.x(), 0, self.cursor_pos.x(), self.height())
            painter.drawLine(0, self.cursor_pos.y(), self.width(), self.cursor_pos.y())

    def mouseMoveEvent(self, event):
        self.cursor_pos = event.pos()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x, y = event.globalX(), event.globalY()
            self.coordinate_selected.emit(x, y)
            self.close()
        elif event.button() == Qt.RightButton:
            self.cancelled.emit()
            self.close()

class ImageTextRecognitionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.recognition_thread = None
        self.target_texts = ["瓦尔申", "督瑞尔", "格里戈利", "冰中野兽"]
        self.area_change_reward = None
        self.area_boss = None
        self.area_open = None
        self.down_coordinate = None
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('图像文字识别与自动点击程序')
        self.setGeometry(100, 100, 420, 500)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        click_group = QGroupBox("自动点击")
        click_layout = QVBoxLayout()
        # boss选择
        target_layout = QHBoxLayout()
        self.target_combo = QComboBox()
        self.target_combo.addItems(self.target_texts)
        target_layout.addWidget(QLabel("选择boss:"))
        target_layout.addWidget(self.target_combo)
        target_layout.addStretch()
        click_layout.addLayout(target_layout)
        # 区域选择
        area_layout = QVBoxLayout()
        self.btn_select_area_change = QPushButton("选择更改奖励区域")
        self.btn_select_area_change.clicked.connect(lambda: self.select_area("change"))
        self.label_area_change = QLabel("未选择")
        area_layout.addWidget(self.btn_select_area_change)
        area_layout.addWidget(self.label_area_change)

        self.btn_select_area_boss = QPushButton("选择boss区域")
        self.btn_select_area_boss.clicked.connect(lambda: self.select_area("boss"))
        self.label_area_boss = QLabel("未选择")
        area_layout.addWidget(self.btn_select_area_boss)
        area_layout.addWidget(self.label_area_boss)

        self.btn_select_area_open = QPushButton("选择打开区域")
        self.btn_select_area_open.clicked.connect(lambda: self.select_area("open"))
        self.label_area_open = QLabel("未选择")
        area_layout.addWidget(self.btn_select_area_open)
        area_layout.addWidget(self.label_area_open)

        click_layout.addLayout(area_layout)
        # 间隔设置
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("识别间隔(秒):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 60)
        self.spin_interval.setValue(15)
        interval_layout.addWidget(self.spin_interval)
        interval_layout.addStretch()
        click_layout.addLayout(interval_layout)
        # 下滑坐标
        self.btn_get_down = QPushButton("获取下滑坐标")
        self.btn_get_down.clicked.connect(self.get_down_coordinate)
        self.label_down = QLabel("未设置")
        down_layout = QHBoxLayout()
        down_layout.addWidget(QLabel("下滑坐标:"))
        down_layout.addWidget(self.label_down)
        down_layout.addWidget(self.btn_get_down)
        down_layout.addStretch()
        click_layout.addLayout(down_layout)
        # 控制按钮
        control_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始识别")
        self.btn_start.clicked.connect(self.start_recognition)
        self.btn_stop = QPushButton("停止识别")
        self.btn_stop.clicked.connect(self.stop_recognition)
        self.btn_stop.setEnabled(False)
        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        click_layout.addLayout(control_layout)
        # 日志
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        click_layout.addWidget(QLabel("操作日志:"))
        click_layout.addWidget(self.text_log)
        # 保存配置按钮
        self.btn_save_config = QPushButton("保存配置")
        self.btn_save_config.clicked.connect(self.save_config)
        config_layout = QHBoxLayout()
        config_layout.addWidget(self.btn_save_config)
        config_layout.addStretch()
        click_layout.addLayout(config_layout)
        click_group.setLayout(click_layout)
        main_layout.addWidget(click_group)
        self.load_config()

    def start_recognition(self):
        if not self.area_change_reward or not self.area_boss or not self.area_open:
            QMessageBox.warning(self, "警告", "请先选择所有识别区域！")
            return
        if not self.down_coordinate:
            QMessageBox.warning(self, "警告", "请先获取下滑坐标！")
            return
        boss_text = self.target_combo.currentText()
        interval = self.spin_interval.value()
        self.recognition_thread = RecognitionThread(
            boss_text, interval, self.down_coordinate,
            self.area_change_reward, self.area_boss, self.area_open
        )
        self.recognition_thread.update_signal.connect(self.log_message)
        self.recognition_thread.finished_signal.connect(self.on_recognition_finished)
        self.recognition_thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_message(f"开始识别流程，boss: {boss_text}，间隔: {interval}秒")

    def select_area(self, area_type):
        self.hide()
        self.overlay = AreaSelector.select_area(self)
        self.overlay.area_type = area_type
        self.log_message(f"请选择{self.get_area_name(area_type)}区域...")

    def get_area_name(self, area_type):
        return {
            "change": "“更改奖励”",
            "boss": "boss",
            "open": "“打开”"
        }.get(area_type, "")

    def on_area_selected(self, rect):
        area_type = getattr(self.overlay, "area_type", None)
        x = rect.x()
        y = rect.y()
        width = rect.width()
        height = rect.height()
        area_str = f"({x}, {y}, {width}, {height})"
        if area_type == "change":
            self.area_change_reward = (x, y, width, height)
            self.label_area_change.setText(f"已选择区域: {area_str}")
        elif area_type == "boss":
            self.area_boss = (x, y, width, height)
            self.label_area_boss.setText(f"已选择区域: {area_str}")
        elif area_type == "open":
            self.area_open = (x, y, width, height)
            self.label_area_open.setText(f"已选择区域: {area_str}")
        self.log_message(f"已选择{self.get_area_name(area_type)}区域: {area_str}")
        self.show()

    def stop_recognition(self):
        if self.recognition_thread and self.recognition_thread.isRunning():
            self.recognition_thread.stop()
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.log_message("正在停止识别...")

    def on_recognition_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.log_message("已停止识别")

    def log_message(self, message):
        current_time = time.strftime("%H:%M:%S")
        log_entry = f"[{current_time}] {message}"
        print(log_entry)
        self.text_log.append(log_entry)
        self.text_log.verticalScrollBar().setValue(self.text_log.verticalScrollBar().maximum())

    def closeEvent(self, event):
        if self.recognition_thread and self.recognition_thread.isRunning():
            self.recognition_thread.stop()
        event.accept()

    def get_down_coordinate(self):
        self.log_message("请点击下滑目标位置...")
        self.hide()
        self.overlay = CoordinateOverlay()
        self.overlay.coordinate_selected.connect(self.on_down_coordinate_selected)
        self.overlay.cancelled.connect(self.on_down_coordinate_cancelled)
        self.overlay.showFullScreen()

    def on_down_coordinate_selected(self, x, y):
        self.down_coordinate = (x, y)
        self.label_down.setText(f"{x}, {y}")
        self.log_message(f"已获取下滑坐标: ({x}, {y})")
        self.show()

    def on_down_coordinate_cancelled(self):
        self.log_message("已取消下滑坐标获取")
        self.show()

    def save_config(self):
        config = {
            "area_change_reward": self.area_change_reward,
            "area_boss": self.area_boss,
            "area_open": self.area_open,
            "down_coordinate": self.down_coordinate,
            "interval": self.spin_interval.value(),
            "boss_index": self.target_combo.currentIndex()
        }
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        self.log_message("配置已保存到 config.json")

    def load_config(self):
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
            if config.get("area_change_reward"):
                self.area_change_reward = tuple(config["area_change_reward"])
                self.label_area_change.setText(f"已选择区域: {self.area_change_reward}")
            if config.get("area_boss"):
                self.area_boss = tuple(config["area_boss"])
                self.label_area_boss.setText(f"已选择区域: {self.area_boss}")
            if config.get("area_open"):
                self.area_open = tuple(config["area_open"])
                self.label_area_open.setText(f"已选择区域: {self.area_open}")
            if config.get("down_coordinate"):
                self.down_coordinate = tuple(config["down_coordinate"])
                self.label_down.setText(f"{self.down_coordinate[0]}, {self.down_coordinate[1]}")
            if config.get("interval"):
                self.spin_interval.setValue(config["interval"])
            if config.get("boss_index") is not None:
                self.target_combo.setCurrentIndex(config["boss_index"])
            self.log_message("已加载本地配置")

    def capture_screen(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                if self.roi:
                    x, y, w, h = self.roi
                    if w <= 0 or h <= 0:
                        print("区域宽高非法！")
                        return None
                    screenshot = ImageGrab.grab(bbox=(x, y, x+w, y+h))
                else:
                    screenshot = ImageGrab.grab()
                # 保存截图到本地，便于人工检查
                screenshot.save("debug_capture.png")
                return np.array(screenshot)
            except Exception as e:
                print("截图异常：", e)
                return None

def main():
    app = QApplication(sys.argv)
    window = ImageTextRecognitionApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()