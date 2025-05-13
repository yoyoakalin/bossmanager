import cv2
import pytesseract
import pyautogui
import time
import numpy as np
from PIL import Image, ImageGrab
import warnings
import re
import json
import os

# 抑制PIL警告
warnings.filterwarnings("ignore", category=UserWarning)

# 设置Tesseract OCR引擎路径
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 文字识别类
class TextRecognizer:
    def __init__(self):
        self.roi = None  # 感兴趣区域 (x, y, width, height)
        self.consecutive_count = 0
        self.last_positions = []
        self.last_check_time = 0
    
    def set_roi(self, x, y, width, height):
        """设置识别区域"""
        self.roi = (x, y, width, height)
    
    def capture_screen(self):
        """捕获屏幕截图"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if self.roi:
                x, y, w, h = self.roi
                screenshot = ImageGrab.grab(bbox=(x, y, x+w, y+h))
            else:
                screenshot = ImageGrab.grab()
        return np.array(screenshot)
    
    def check_position(self, x, y, text, tolerance=10):
        """检查位置是否稳定"""
        # 如果是第一次检测到这个位置
        if not hasattr(self, '_last_positions'):
            self._last_positions = {}
        
        position_key = text
        current_pos = (x, y)
        current_time = time.time()
        
        if position_key not in self._last_positions:
            self._last_positions[position_key] = {
                'pos': current_pos,
                'count': 1,
                'last_time': current_time
            }
            print(f"首次检测位置 '{text}': ({x}, {y})")
            return True  # 修改：首次检测就返回True
        
        last_record = self._last_positions[position_key]
        last_pos = last_record['pos']
        
        # 检查坐标是否在允许的误差范围内
        x_diff = abs(current_pos[0] - last_pos[0])
        y_diff = abs(current_pos[1] - last_pos[1])
        
        print(f"位置检查: '{text}' 当前:({x}, {y}) 上次:({last_pos[0]}, {last_pos[1]})")
        print(f"位置差异: X差异:{x_diff}像素, Y差异:{y_diff}像素 (允许误差:{tolerance}像素)")
        
        # 如果位置相近（考虑误差）
        if x_diff <= tolerance and y_diff <= tolerance:
            last_record['count'] += 1
            print(f"位置稳定性: 连续检测次数 {last_record['count']}")
            return True  # 修改：只要位置在误差范围内就返回True
        else:
            # 位置发生较大变化，重置计数
            print(f"位置不稳定，重置计数")
            last_record['count'] = 1
            last_record['pos'] = current_pos
            last_record['last_time'] = current_time
            return False
    
    def find_text_location(self, target_text, roi=None):
        if roi:
            self.set_roi(*roi)
        else:
            self.set_roi(None)
        screen = self.capture_screen()
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        custom_config = r'--oem 3 --psm 6'
        data = pytesseract.image_to_data(gray, lang='chi_sim', 
                                        output_type=pytesseract.Output.DICT,
                                        config=custom_config)

        # 新增：打印OCR原始输出
        print("OCR原始输出：", data['text'])

        # 收集所有文字及其位置
        text_blocks = []
        for i, text in enumerate(data['text']):
            if text.strip():
                x = data['left'][i]
                y = data['top'][i]
                w = data['width'][i]
                h = data['height'][i]
                conf = float(data['conf'][i])
                text_blocks.append((text, x, y, w, h, conf))

        # 横向合并：按y坐标分组（同一行），每行内按x排序
        lines = []
        line_threshold = 20  # 行高容忍像素
        text_blocks.sort(key=lambda x: (x[2], x[1]))  # 先按y再按x排序

        for block in text_blocks:
            text, x, y, w, h, conf = block
            # 尝试归入已有行
            found_line = False
            for line in lines:
                if abs(line['y'] - y) < line_threshold:
                    line['blocks'].append(block)
                    found_line = True
                    break
            if not found_line:
                lines.append({'y': y, 'blocks': [block]})

        # 在每一行内横向拼接字符串，并查找目标
        for line in lines:
            blocks = sorted(line['blocks'], key=lambda b: b[1])  # 按x排序
            line_text = ''.join([b[0] for b in blocks])
            print(f"行内容: {line_text}")
            idx = line_text.find(target_text)
            if idx != -1:
                # 找到目标字符串，定位起始字块
                char_count = 0
                for b in blocks:
                    if char_count == idx:
                        x, y, w, h, conf = b[1:6]
                        if self.roi:
                            roi_x, roi_y, _, _ = self.roi
                            global_x = roi_x + x
                            global_y = roi_y + y
                            center_x = global_x + w // 2
                            center_y = global_y + h // 2
                            print(f"找到目标 '{target_text}'，中心点({center_x}, {center_y})")
                            if self.check_position(center_x, center_y, target_text):
                                return [(center_x, center_y)]
                        break
                    char_count += len(b[0])
        print(f"未找到目标文字 '{target_text}'")
        return []

# 创建全局识别器实例
recognizer = TextRecognizer()

def set_recognition_area(x, y, width, height):
    """设置识别区域"""
    recognizer.set_roi(x, y, width, height)

def click_on_text(target_text, roi=None):
    """识别并点击指定文字"""
    locations = recognizer.find_text_location(target_text, roi)
    
    if locations:
        x, y = locations[0]
        print(f"找到文字 '{target_text}' 在位置 ({x}, {y})，正在点击...")
        pyautogui.click(x, y)
        return True, f"找到文字 '{target_text}' 在位置 ({x}, {y})，已点击"
    else:
        return False, f"未找到文字 '{target_text}'"


