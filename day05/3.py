import os
import time
import sqlite3
import cv2 as cv
import numpy as np
from datetime import datetime

from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton,
                             QMessageBox, QGraphicsDropShadowEffect,
                             QGridLayout, QVBoxLayout, QDialog, 
                             QLineEdit, QFormLayout, QDialogButtonBox)
from PySide6.QtGui import (QImage, QPixmap, QPainter, QColor, 
                           QPen, QBrush, QLinearGradient, QRadialGradient)
from PySide6.QtCore import Qt, QTimer

# 导入 UI 文件
try:
    from face import Ui_Form
except ImportError:
    print("❌ 错误：找不到 face.py 文件，请确保已通过 PySide6 工具生成该文件！")
    exit(1)


# ================= 🗄️ SQLite 数据库初始化与管理 =================
DB_PATH = "./attendance.db"

def init_db():
    """初始化数据库与表（已移除默认测试数据）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 创建员工表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            dept TEXT NOT NULL
        )
    """)
    
    # 2. 创建打卡记录表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            dept TEXT,
            check_type TEXT,
            check_time TEXT,
            status TEXT
        )
    """)
    
    conn.commit()
    conn.close()

def is_user_exists(user_id):
    """🌟 查重逻辑：检查该工号是否已存在于数据库中"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None  # 如果存在返回 True，否则返回 False

def get_user_info(user_id):
    """从数据库获取员工资料"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, dept FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        return {"name": row[0], "dept": row[1]}
    return {"name": f"员工_{user_id}", "dept": "未知部门"}

def save_user_to_db(user_id, name, dept):
    """新增/更新员工信息，同步修补历史记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, name, dept) VALUES (?, ?, ?)", (user_id, name, dept))
    
    # 同步把历史记录里该 ID 对应的临时名替换为正式姓名
    cursor.execute("""
        UPDATE attendance_records 
        SET name = ?, dept = ? 
        WHERE user_id = ? AND (name LIKE '员工_%' OR dept = '未知部门')
    """, (name, dept, user_id))
    
    conn.commit()
    conn.close()

def log_attendance_to_db(user_id, name, dept, check_type, check_time_str, status):
    """保存一条打卡记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO attendance_records (user_id, name, dept, check_type, check_time, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, name, dept, check_type, check_time_str, status))
    conn.commit()
    conn.close()


# 初始化数据库
init_db()


# ================= 全局变量声明 =================
ui = None
cap = None
timer = None
blink_counter = 0      
total_blinks = 0       
eye_closed = False     
liveness_passed = False 
current_mode = 'preview' 
path = './data'
model_path = './model/trainer.yml'

attendance_type = 'on_duty'

# 暂存识别到的员工信息
current_recognized_user = None

# 分类器初始化
facecascade = cv.CascadeClassifier('haar/haarcascade_frontalface_alt2.xml')
if facecascade.empty():
    facecascade = cv.CascadeClassifier(cv.data.haarcascades + "haarcascade_frontalface_alt2.xml")

eye_cascade = cv.CascadeClassifier('haar/haarcascade_eye_tree_eyeglasses.xml')
if eye_cascade.empty():
    eye_cascade = cv.CascadeClassifier(cv.data.haarcascades + "haarcascade_eye.xml")

recognizer = cv.face.LBPHFaceRecognizer.create()


# ================= 多字段输入弹窗 =================
class SaveUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("人脸录入 - 员工信息")
        self.resize(320, 200)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #F5FCF5;
            }
            QLabel {
                font-weight: bold;
                color: #2D4030;
                font-size: 13px;
            }
            QLineEdit {
                border: 1.5px solid #CDE6CD;
                border-radius: 8px;
                padding: 6px 10px;
                background-color: #FFFFFF;
                color: #1A2B1C;
                font-size: 13px;
                font-weight: bold;
            }
            QLineEdit::placeholder {
                color: #8D9B8F;
                font-weight: normal;
            }
            QLineEdit:focus {
                border: 2px solid #5CAF5C;
            }
        """)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        self.input_id = QLineEdit(self)
        self.input_id.setPlaceholderText("仅纯数字，如: 101")
        
        self.input_name = QLineEdit(self)
        self.input_name.setPlaceholderText("请输入真实姓名")
        
        self.input_dept = QLineEdit(self)
        self.input_dept.setPlaceholderText("请输入部门，如: 研发部")

        form_layout.addRow("员工编号:", self.input_id)
        form_layout.addRow("员工姓名:", self.input_name)
        form_layout.addRow("所属部门:", self.input_dept)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.Ok).setText("确认保存")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def validate_and_accept(self):
        user_id_str = self.input_id.text().strip()
        name = self.input_name.text().strip()
        dept = self.input_dept.text().strip()

        if not user_id_str.isdigit():
            QMessageBox.warning(self, "校验失败", "编号必须由纯数字组成！")
            return
            
        user_id = int(user_id_str)
        
        # 🌟 查重触发：判断库文件中是否已有此编号
        if is_user_exists(user_id):
            user_info = get_user_info(user_id)
            QMessageBox.warning(
                self, 
                "录入提示", 
                f"⚠️ 编号为【{user_id}】的员工已存在！\n\n已录入姓名：{user_info['name']}\n所属部门：{user_info['dept']}\n\n您的信息已经录入，无需重复保存！"
            )
            return

        if not name:
            QMessageBox.warning(self, "校验失败", "姓名不能为空！")
            return
        if not dept:
            QMessageBox.warning(self, "校验失败", "部门不能为空！")
            return

        self.accept()

    def get_data(self):
        return (
            int(self.input_id.text().strip()),
            self.input_name.text().strip(),
            self.input_dept.text().strip()
        )


# ================= 🎨 纯代码水彩风水果 =================
def generate_fresh_fruit_pixmap(width=140, height=140):
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # 1. 底部阴影
    shadow_grad = QRadialGradient(70, 115, 45)
    shadow_grad.setColorAt(0, QColor(180, 210, 190, 80))
    shadow_grad.setColorAt(1, QColor(0, 0, 0, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(shadow_grad))
    painter.drawEllipse(15, 105, 110, 20)

    # 2. 青柚子
    pomelo_grad = QRadialGradient(45, 55, 40)
    pomelo_grad.setColorAt(0, QColor(200, 235, 140))
    pomelo_grad.setColorAt(0.8, QColor(135, 195, 90))
    pomelo_grad.setColorAt(1, QColor(105, 165, 65))
    painter.setBrush(QBrush(pomelo_grad))
    painter.drawEllipse(10, 20, 80, 80)

    # 3. 切片黄柠檬
    painter.save()
    painter.translate(88, 80)
    painter.rotate(-18)

    lemon_skin_grad = QRadialGradient(0, 0, 30)
    lemon_skin_grad.setColorAt(0.75, QColor(255, 225, 50))
    lemon_skin_grad.setColorAt(1, QColor(230, 185, 20))
    painter.setBrush(QBrush(lemon_skin_grad))
    painter.drawEllipse(-30, -30, 60, 60)

    painter.setBrush(QBrush(QColor(255, 255, 242)))
    painter.drawEllipse(-26, -26, 52, 52)

    painter.setBrush(QBrush(QColor(255, 210, 30)))
    painter.drawEllipse(-23, -23, 46, 46)

    painter.setPen(QPen(QColor(255, 255, 245), 2))
    painter.setBrush(QBrush(QColor(255, 225, 60)))
    for _ in range(8):
        painter.drawPie(-21, -21, 42, 42, 5 * 16, 35 * 16)
        painter.rotate(45)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 242)))
    painter.drawEllipse(-3, -3, 6, 6)
    painter.restore()

    painter.end()
    return pixmap


# ================= 训练与保存算法 =================
def getImagesAndLabels(path_dir):
    sample, ids = [], []
    if not os.path.exists(path_dir):
        return sample, ids

    valid_exts = ('.jpg', '.png', '.jpeg')
    filenames = [os.path.join(path_dir, f) for f in os.listdir(path_dir) 
                 if os.path.isfile(os.path.join(path_dir, f)) and f.lower().endswith(valid_exts)]
    
    for filename in filenames:
        try:
            base_name = os.path.basename(filename)
            id_num = int(base_name.split('.')[0].split('_')[0])
            img = cv.imread(filename)
            if img is None: continue
            gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
            faces = facecascade.detectMultiScale(gray)
            for (x, y, w, h) in faces:
                sample.append(gray[y:y+h, x:x+w])
                ids.append(id_num)
        except ValueError:
            continue
    return sample, ids

def faceTrain(path_dir):
    images, labels = getImagesAndLabels(path_dir)
    if len(images) == 0:
        return False
    recognizer.train(images, np.array(labels))
    os.makedirs("./model", exist_ok=True)
    recognizer.write(model_path)
    return True


# ================= 实时面板更新 =================
def update_user_info_panel(user_id):
    global current_recognized_user
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    
    user_info = get_user_info(user_id)

    work_start_time = now.replace(hour=9, minute=30, second=0, microsecond=0)  # 上班 09:30
    work_end_time   = now.replace(hour=17, minute=30, second=0, microsecond=0) # 下班 17:30

    if attendance_type == 'on_duty':
        check_type_name = "上班"
        if now <= work_start_time:
            status_text = "✨ 早上好，签到成功！"
            status_color = "#3CB371"
        else:
            diff_sec = int((now - work_start_time).total_seconds())
            hrs = diff_sec // 3600
            mins = (diff_sec % 3600) // 60
            late_str = f"{hrs}小时{mins}分钟" if hrs > 0 else f"{max(1, mins)}分钟"
            status_text = f"⚠️ 您迟到了 {late_str}"
            status_color = "#D9534F"
    else:
        check_type_name = "下班"
        if now < work_end_time:
            diff_sec = int((work_end_time - now).total_seconds())
            hrs = diff_sec // 3600
            mins = (diff_sec % 3600) // 60
            early_str = f"{hrs}小时{mins}分钟" if hrs > 0 else f"{max(1, mins)}分钟"
            status_text = f"⚠️ 早退 {early_str}！下班快乐，明天再见，祝您好梦~"
            status_color = "#E67E22"
        else:
            diff_sec = int((now - work_end_time).total_seconds())
            hrs = diff_sec // 3600
            mins = (diff_sec % 3600) // 60
            
            if diff_sec < 60:
                status_text = "🌙 准时下班！下班快乐，明天再见，祝您好梦~"
            else:
                ot_str = f"{hrs}小时{mins}分钟" if hrs > 0 else f"{mins}分钟"
                status_text = f"🌙 已加班 {ot_str}！下班快乐，明天再见，祝您好梦~"
            status_color = "#2E8B57"

    ui.lbl_id.setText(f"编 号：{user_id}")
    ui.lbl_name.setText(f"姓 名：{user_info['name']}")
    ui.lbl_dept.setText(f"部 门：{user_info['dept']}")
    ui.lbl_time.setText(f"打卡时间：{time_str} ({check_type_name})")
    ui.lbl_status.setText(status_text)
    ui.lbl_status.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 12px;")

    current_recognized_user = {
        "user_id": user_id,
        "name": user_info['name'],
        "dept": user_info['dept'],
        "check_type": check_type_name,
        "status": status_text
    }


# ================= 点击【确认打卡】写入数据库 =================
def on_confirm_checkin_click():
    global current_recognized_user
    
    if current_recognized_user is None:
        QMessageBox.warning(None, "打卡失败", "当前未识别到人员，请面向摄像头识别成功后再按打卡！")
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    u = current_recognized_user

    log_attendance_to_db(
        u["user_id"], 
        u["name"], 
        u["dept"], 
        u["check_type"], 
        now_str, 
        u["status"]
    )

    QMessageBox.information(
        None, 
        "打卡成功", 
        f"🎉 考勤数据已成功记录！\n\n"
        f"编号：{u['user_id']}\n"
        f"姓名：{u['name']}\n"
        f"部门：{u['dept']}\n"
        f"类型：{u['check_type']}打卡\n"
        f"时间：{now_str}\n"
        f"状态：{u['status']}"
    )
    update_status_tip(f"✅ {u['name']} ({u['dept']}) 打卡记录已成功写入数据库！")


# ================= 视频渲染逻辑 =================
def process_frame():
    global cap, ui, current_mode, blink_counter, total_blinks, eye_closed, liveness_passed, current_recognized_user

    if cap is None or not cap.isOpened():
        return

    res, frame = cap.read()
    if not res: return

    frame = cv.flip(frame, 1)  
    gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
    faces = facecascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5)

    if current_mode == 'preview':
        current_recognized_user = None
        for (x, y, w, h) in faces:
            cv.rectangle(frame, (x, y), (x + w, y + h), (144, 238, 144), 2)

    elif current_mode == 'recog':
        if len(faces) == 0:
            current_recognized_user = None

        for (x, y, w, h) in faces:
            roi_gray = gray[y:y+h, x:x+w]
            try:
                id_num, conf = recognizer.predict(roi_gray)
                if conf < 110:
                    confidence_percent = round(max(0, 100 - (conf / 1.1)), 1)
                    text = f"ID:{id_num} ({confidence_percent}%)"
                    color = (100, 200, 100)
                    update_user_info_panel(id_num)
                else:
                    text = "Unknown"
                    color = (100, 100, 255)
                    current_recognized_user = None
                cv.putText(frame, text, (x, y - 10), cv.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            except Exception:
                cv.putText(frame, "Model Error", (x, y - 10), cv.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 255), 2)
                color = (100, 100, 255)
                current_recognized_user = None

            cv.rectangle(frame, (x, y), (x + w, y + h), color, 2)

    elif current_mode == 'liveness':
        for (x, y, w, h) in faces:
            cv.rectangle(frame, (x, y), (x + w, y + h), (255, 182, 193), 2)
            roi_gray = gray[y:y+h, x:x+w]
            roi_color = frame[y:y+h, x:x+w]

            if not liveness_passed:
                current_recognized_user = None
                eyes = eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=8, minSize=(30, 30))
                for (ex, ey, ew, eh) in eyes:
                    cv.rectangle(roi_color, (ex, ey), (ex + ew, ey + eh), (100, 200, 100), 1)

                if len(eyes) < 1:
                    blink_counter += 1
                    if blink_counter >= 2: eye_closed = True
                else:
                    if eye_closed:
                        total_blinks += 1
                        eye_closed = False
                        blink_counter = 0

                cv.putText(frame, f"Blinks: {total_blinks}/2", (20, 40), cv.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 255), 2)
                cv.putText(frame, "Liveness: Testing...", (20, 80), cv.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 255), 2)

                if total_blinks >= 2:
                    liveness_passed = True
                    update_status_tip("✨ 活体检测通过！已解锁人脸识别")

            else:
                try:
                    id_num, conf = recognizer.predict(roi_gray)
                    if conf < 110:
                        text = f"ID: {id_num} (True)"
                        color = (100, 200, 100)
                        update_user_info_panel(id_num)
                    else:
                        text = "Unknown Person"
                        color = (100, 100, 255)
                        current_recognized_user = None
                except Exception:
                    text, color = "Model Error", (100, 100, 255)
                    current_recognized_user = None

                cv.putText(frame, text, (x, y - 10), cv.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                cv.putText(frame, "Liveness: PASSED", (20, 40), cv.FONT_HERSHEY_SIMPLEX, 0.8, (100, 200, 100), 2)

    height, width, channel = frame.shape
    bytesperline = 3 * width
    qimg = QImage(frame.data, width, height, bytesperline, QImage.Format_RGB888).rgbSwapped().copy()
    
    pixmap = QPixmap.fromImage(qimg)
    ui.cam.setAlignment(Qt.AlignCenter)
    ui.cam.setPixmap(pixmap)


# ================= 交互控制 =================
def update_status_tip(text):
    if hasattr(ui, 'statusLabel'):
        ui.statusLabel.setText(text)

def toggle_attendance_mode():
    global attendance_type
    if attendance_type == 'on_duty':
        attendance_type = 'off_duty'
        ui.btn_type_toggle.setText("🌙 当前模式：下班签退 (点击切换)")
        ui.btn_type_toggle.setStyleSheet("""
            QPushButton#btn_type_toggle {
                background-color: #FFF3E0;
                border: 1.5px solid #FFB74D;
                color: #E65100;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#btn_type_toggle:hover {
                background-color: #FFE0B2;
            }
        """)
        update_status_tip("🌙 考勤模式已切换为：下班签退")
    else:
        attendance_type = 'on_duty'
        ui.btn_type_toggle.setText("🌞 当前模式：上班签到 (点击切换)")
        ui.btn_type_toggle.setStyleSheet("""
            QPushButton#btn_type_toggle {
                background-color: #E8F5E9;
                border: 1.5px solid #81C784;
                color: #2E7D32;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#btn_type_toggle:hover {
                background-color: #C8E6C9;
            }
        """)
        update_status_tip("🌞 考勤模式已切换为：上班签到")

def start_camera():
    global cap, timer
    if cap is None:
        cap = cv.VideoCapture(0)
    if timer is None:
        timer = QTimer()
        timer.timeout.connect(process_frame)
    if not timer.isActive():
        timer.start(30)

def stop_camera():
    global cap, timer, ui, current_recognized_user
    current_recognized_user = None
    if timer is not None and timer.isActive():
        timer.stop()
    if cap is not None:
        cap.release()
        cap = None
    if ui is not None:
        ui.cam.clear()
        ui.cam.setText("🍃 摄像头已关闭")

def on_open_click():
    global current_mode, cap
    if cap is None:
        current_mode = 'preview'
        start_camera()
        ui.openButton.setText("关闭摄像头")
        update_status_tip("🍃 模式：实时人脸预览中...")
    else:
        stop_camera()
        ui.openButton.setText("打开摄像头")
        update_status_tip("✨ 系统就绪，请选择功能操作")

def on_save_click():
    global cap, timer, current_mode
    if cap is not None and cap.isOpened():
        ret, frame = cap.read()
        if ret:
            gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
            faces = facecascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30))
            if len(faces) > 0:
                (x, y, w, h) = faces[0]
                roi_gray = gray[y:y+h, x:x+w]
                
                dialog = SaveUserDialog()
                if dialog.exec() == QDialog.Accepted:
                    user_id, name, dept = dialog.get_data()
                    
                    # 保存新员工
                    save_user_to_db(user_id, name, dept)
                    
                    save_dir = './data/'
                    os.makedirs(save_dir, exist_ok=True)
                    filename = f"{user_id}_{int(time.time())}.jpg"
                    file_path = os.path.join(save_dir, filename)

                    try:
                        cv.imwrite(file_path, roi_gray)
                        
                        update_status_tip("🔄 正在保存人脸并训练模型中...")
                        if faceTrain(path):
                            recognizer.read(model_path)
                            QMessageBox.information(
                                None, 
                                "录入成功", 
                                f"🎉 员工信息录入成功！\n\n编号：{user_id}\n姓名：{name}\n部门：{dept}\n\n基本信息及脸部特征已成功保存在系统中！"
                            )
                            update_status_tip(f"成功录入：{name} ({dept})，已写入数据库")
                            current_mode = 'recog'
                        else:
                            QMessageBox.warning(None, "警告", "图片保存成功，但模型训练失败。")
                    except Exception as e:
                        QMessageBox.critical(None, "保存失败", f"保存过程发生错误: {e}")
            else:
                QMessageBox.warning(None, "检测失败", "未识别到面部，请面向摄像头！")

def on_recog_click():
    global current_mode
    if not faceTrain(path):
        if not os.path.exists(model_path):
            QMessageBox.warning(None, "提示", "数据库中尚无录入数据，请先采集人脸！")
            return
            
    recognizer.read(model_path)
    current_mode = 'recog'
    start_camera()
    update_status_tip("🔍 模式：智能人脸识别比对中...")

def on_persion_click():
    global current_mode, blink_counter, total_blinks, eye_closed, liveness_passed
    if not os.path.exists(model_path):
        if not faceTrain(path):
            QMessageBox.warning(None, "提示", "模型文件缺失且无训练数据，请先录入！")
            return

    recognizer.read(model_path)
    blink_counter = 0
    total_blinks = 0
    eye_closed = False
    liveness_passed = False
    current_mode = 'liveness'
    
    start_camera()
    update_status_tip("👁️ 活体检测：请面向摄像头自然眨眼 2 次")


# ================= 🎨 QSS 调色表 =================
SUPER_FRESH_QSS = """
QWidget#win {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #F2FAF2, stop:0.5 #E8F7E8, stop:1 #F5FCF5);
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    color: #2D4030;
}

QLabel#statusLabel {
    background-color: rgba(255, 255, 255, 0.85);
    border: 1px solid #D6EBD6;
    border-radius: 12px;
    padding: 6px 15px;
    font-size: 13px;
    font-weight: bold;
    color: #3B7A57;
}

QWidget#infoCard {
    background-color: rgba(255, 255, 255, 0.88);
    border: 1.5px solid #D1E8D1;
    border-radius: 18px;
}

QWidget#infoCard QLabel {
    font-size: 13px;
    color: #2E4030;
    font-weight: 500;
}

QPushButton {
    background-color: #FFFFFF;
    border: 1.5px solid #CDE6CD;
    border-radius: 18px;
    padding: 10px 16px;
    font-size: 14px;
    font-weight: bold;
    color: #3B7A57;
    min-width: 85px;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #E2F5E2;
    border-color: #8FD88F;
    color: #1E5631;
}

QPushButton:pressed {
    background-color: #C8ECC8;
}

QPushButton#saveButton:hover, QPushButton#recogButton:hover {
    background-color: #FFFDE6;
    border-color: #FCE883;
    color: #B8860B;
}

QPushButton#persionButton:hover {
    background-color: #E6F3FF;
    border-color: #A3C2EE;
    color: #2B547E;
}

QLabel#decLabel {
    background: transparent;
}
"""


# ================= 启动 UI 与组件组装 =================
def showUi():
    global ui
    app = QApplication([])
    
    win = QWidget()
    win.setObjectName("win")
    ui = Ui_Form()
    ui.setupUi(win)
    win.setWindowTitle("柚子柠檬人脸识别考勤系统")

    win.resize(820, 580)
    app.setStyleSheet(SUPER_FRESH_QSS)

    # 1. 隐藏原 .ui 中的重复标题
    for widget in win.findChildren(QLabel):
        if widget.text() == "人脸识别":
            widget.hide()

    # 2. 设置 cam 淡奶绿背景
    ui.cam.setStyleSheet("""
        background-color: #EAF7EA;
        border: 2.5px solid #C5E5C5;
        border-radius: 20px;
        color: #3B7A57;
        font-size: 15px;
        font-weight: bold;
    """)

    # 3. 顶部提示栏
    ui.statusLabel = QLabel("✨ 系统初始化完成，数据库已加载...", win)
    ui.statusLabel.setObjectName("statusLabel")
    ui.statusLabel.setAlignment(Qt.AlignCenter)
    ui.statusLabel.setGeometry(30, 15, 360, 32)

    # 4. 右下角水彩柚子柠檬艺术图
    ui.decLabel = QLabel(win)
    ui.decLabel.setObjectName("decLabel")
    ui.decLabel.setPixmap(generate_fresh_fruit_pixmap(140, 140))
    ui.decLabel.setGeometry(820 - 145, 580 - 140, 140, 140)
    ui.decLabel.lower()

    # 5. 左侧摄像头阴影
    cam_shadow = QGraphicsDropShadowEffect()
    cam_shadow.setBlurRadius(20)
    cam_shadow.setColor(QColor(80, 150, 100, 30))
    cam_shadow.setOffset(0, 4)
    ui.cam.setGraphicsEffect(cam_shadow)

    # 6. 右上方 2x2 按钮面板
    btn_panel = QWidget(win)
    grid_layout = QGridLayout(btn_panel)
    grid_layout.setSpacing(12)

    grid_layout.addWidget(ui.openButton, 0, 0)
    grid_layout.addWidget(ui.saveButton, 0, 1)
    grid_layout.addWidget(ui.recogButton, 1, 0)
    grid_layout.addWidget(ui.persionButton, 1, 1)

    btn_panel.setGeometry(525, 50, 275, 125)
    btn_panel.raise_()

    # 7. 右中间个人信息面板
    infoCard = QWidget(win)
    infoCard.setObjectName("infoCard")
    info_layout = QVBoxLayout(infoCard)
    info_layout.setContentsMargins(16, 10, 16, 10)
    info_layout.setSpacing(4)

    ui.lbl_id = QLabel("编 号：--")
    ui.lbl_name = QLabel("姓 名：未识别")
    ui.lbl_dept = QLabel("部 门：--")
    ui.lbl_time = QLabel("打卡时间：--:--:--")
    
    ui.lbl_status = QLabel("状态：等待打卡中...")
    ui.lbl_status.setWordWrap(True)
    ui.lbl_status.setStyleSheet("color: #888; font-style: italic;")

    info_layout.addWidget(ui.lbl_id)
    info_layout.addWidget(ui.lbl_name)
    info_layout.addWidget(ui.lbl_dept)
    info_layout.addWidget(ui.lbl_time)
    info_layout.addWidget(ui.lbl_status)

    infoCard.setGeometry(525, 185, 275, 185)

    card_shadow = QGraphicsDropShadowEffect()
    card_shadow.setBlurRadius(15)
    card_shadow.setColor(QColor(80, 150, 100, 25))
    card_shadow.setOffset(0, 3)
    infoCard.setGraphicsEffect(card_shadow)

    # 8. 右下角：切换上班/下班模式按钮
    ui.btn_type_toggle = QPushButton("🌞 当前模式：上班签到 (点击切换)", win)
    ui.btn_type_toggle.setObjectName("btn_type_toggle")
    ui.btn_type_toggle.setGeometry(525, 382, 275, 36)
    ui.btn_type_toggle.setStyleSheet("""
        QPushButton#btn_type_toggle {
            background-color: #E8F5E9;
            border: 1.5px solid #81C784;
            color: #2E7D32;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        }
        QPushButton#btn_type_toggle:hover {
            background-color: #C8E6C9;
        }
    """)
    ui.btn_type_toggle.clicked.connect(toggle_attendance_mode)

    # 9. 右下角【确认打卡】按钮
    ui.btn_confirm_checkin = QPushButton("✅ 确认打卡", win)
    ui.btn_confirm_checkin.setObjectName("btn_confirm_checkin")
    ui.btn_confirm_checkin.setGeometry(525, 432, 170, 42)
    ui.btn_confirm_checkin.setStyleSheet("""
        QPushButton#btn_confirm_checkin {
            background-color: #4CAF50;
            border: 1.5px solid #388E3C;
            color: #FFFFFF;
            border-radius: 14px;
            font-size: 15px;
            font-weight: bold;
        }
        QPushButton#btn_confirm_checkin:hover {
            background-color: #43A047;
            border-color: #2E7D32;
        }
        QPushButton#btn_confirm_checkin:pressed {
            background-color: #388E3C;
        }
    """)
    ui.btn_confirm_checkin.clicked.connect(on_confirm_checkin_click)

    # 10. 绑定槽函数
    ui.openButton.clicked.connect(on_open_click)
    ui.saveButton.clicked.connect(on_save_click)
    ui.recogButton.clicked.connect(on_recog_click)
    ui.persionButton.clicked.connect(on_persion_click)

    # 初始视频框提示
    ui.cam.setText("🍃 请点击右上角按钮开启功能")
    ui.cam.setAlignment(Qt.AlignCenter)

    win.show()
    app.exec()

if __name__ == "__main__":
    showUi()