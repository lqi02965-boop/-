import os
import sys
import time
import sqlite3
import cv2 as cv
import numpy as np
import pandas as pd
import mediapipe as mp

# 兼容各版本 MediaPipe 的导入方式
mp_face_detection = mp.solutions.face_detection
mp_face_mesh = mp.solutions.face_mesh

from insightface.app import FaceAnalysis
from datetime import datetime

from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton,
                             QMessageBox, QGraphicsDropShadowEffect,
                             QGridLayout, QVBoxLayout, QHBoxLayout, QDialog, 
                             QLineEdit, QFormLayout, QDialogButtonBox)
from PySide6.QtGui import (QImage, QPixmap, QPainter, QColor, 
                           QPen, QBrush, QRadialGradient)
from PySide6.QtCore import Qt, QTimer

# 导入 UI 文件
try:
    from face import Ui_Form
except ImportError:
    print("❌ 错误：找不到 face.py 文件，请确保已通过 PySide6 工具生成该文件！")
    exit(1)


# ================= 🗄️ SQLite 数据库初始化与管理 =================
DB_PATH = "./company_attendance.db"

def init_db():
    """初始化数据库表结构"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 员工档案表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            dept TEXT NOT NULL,
            encoding BLOB
        )
    """)
    
    # 2. 考勤流水表
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

    # 3. 管理员系统设置表 (存储管理员密码与人脸特征)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value_text TEXT,
            value_blob BLOB
        )
    """)

    # 设置默认初始密码 123456
    cursor.execute("SELECT value_text FROM system_config WHERE key = 'admin_password'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO system_config (key, value_text) VALUES ('admin_password', '123456')")

    conn.commit()
    conn.close()

# 管理员密码与人脸相关数据库操作
def get_admin_password():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value_text FROM system_config WHERE key = 'admin_password'")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "123456"

def set_admin_password(new_pwd):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO system_config (key, value_text) VALUES ('admin_password', ?)", (new_pwd,))
    conn.commit()
    conn.close()

def save_admin_face_encoding(encoding_bytes):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO system_config (key, value_blob) VALUES ('admin_face', ?)", (encoding_bytes,))
    conn.commit()
    conn.close()

def get_admin_face_encoding():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value_blob FROM system_config WHERE key = 'admin_face'")
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        return np.frombuffer(row[0], dtype=np.float32)
    return None

def is_user_exists(user_id):
    """判重：检查工号是否存在"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_user_info(user_id):
    """获取员工信息"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, dept FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        return {"name": row[0], "dept": row[1]}
    return {"name": f"员工_{user_id}", "dept": "未知部门"}

def save_user_to_db(user_id, name, dept, encoding_bytes):
    """保存新员工及 512 维特征向量"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, name, dept, encoding) VALUES (?, ?, ?, ?)", 
        (user_id, name, dept, encoding_bytes)
    )
    conn.commit()
    conn.close()

def load_all_known_faces():
    """加载已保存的人脸特征向量"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, dept, encoding FROM users WHERE encoding IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    
    known_ids = []
    known_encodings = []
    user_dict = {}
    
    for r in rows:
        uid, name, dept, enc_blob = r
        if enc_blob:
            enc = np.frombuffer(enc_blob, dtype=np.float32)
            known_ids.append(uid)
            known_encodings.append(enc)
            user_dict[uid] = {"name": name, "dept": dept}
            
    return known_ids, known_encodings, user_dict

def log_attendance_to_db(user_id, name, dept, check_type, check_time_str, status):
    """保存考勤打卡记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO attendance_records (user_id, name, dept, check_type, check_time, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, name, dept, check_type, check_time_str, status))
    conn.commit()
    conn.close()

init_db()


# ================= 📊 Excel 导出逻辑 =================
def export_users_to_excel():
    """导出员工档案库为 Excel"""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT user_id AS 员工编号, name AS 姓名, dept AS 所属部门 FROM users", conn)
        conn.close()
        
        if df.empty:
            QMessageBox.warning(None, "导出提示", "员工数据库中暂无任何员工数据！")
            return
            
        file_path = "员工档案表.xlsx"
        df.to_excel(file_path, index=False)
        
        QMessageBox.information(None, "导出成功", f"🎉 员工档案已成功导出至：\n{os.path.abspath(file_path)}")
        os.startfile(os.path.abspath(file_path))
    except Exception as e:
        QMessageBox.critical(None, "导出失败", f"导出员工档案表时发生错误：\n{str(e)}")

def export_attendance_to_excel():
    """导出考勤流水记录为 Excel"""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("""
            SELECT id AS 记录序号, user_id AS 员工编号, name AS 姓名, 
                   dept AS 部门, check_type AS 打卡类型, check_time AS 打卡时间, status AS 考勤状态 
            FROM attendance_records ORDER BY id DESC
        """, conn)
        conn.close()
        
        if df.empty:
            QMessageBox.warning(None, "导出提示", "考勤打卡记录库中暂无任何打卡数据！")
            return
            
        file_path = "考勤打卡记录表.xlsx"
        df.to_excel(file_path, index=False)
        
        QMessageBox.information(None, "导出成功", f"🎉 考勤记录已成功导出至：\n{os.path.abspath(file_path)}")
        os.startfile(os.path.abspath(file_path))
    except Exception as e:
        QMessageBox.critical(None, "导出失败", f"导出考勤记录表时发生错误：\n{str(e)}")


# ================= 🚀 AI 引擎初始化 =================
face_detector = mp_face_detection.FaceDetection(min_detection_confidence=0.6)
face_mesh_detector = mp_face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True)

insight_app = FaceAnalysis(name='buffalo_sc', providers=['CPUExecutionProvider'])
insight_app.prepare(ctx_id=0, det_size=(320, 320))


# ================= 全局变量与流程状态锁 =================
ui = None
cap = None
timer = None
current_mode = 'preview' 
attendance_type = 'on_duty'
is_admin_mode = False  # 管理员模式标志

# 流程控制锁（必须按顺序执行：1.人脸识别 -> 2.活体检测 -> 3.确认打卡）
is_face_recognized = False    
is_liveness_verified = False  

# 活体眨眼参数
blink_counter = 0      
total_blinks = 0       
eye_closed = False     

# 识别与缓存数据
current_recognized_user = None
known_user_ids = []
known_user_encodings = []
known_user_dict = {}

def refresh_known_faces_cache():
    global known_user_ids, known_user_encodings, known_user_dict
    known_user_ids, known_user_encodings, known_user_dict = load_all_known_faces()

refresh_known_faces_cache()


# ================= 弹窗对话框类 =================

class AdminLoginDialog(QDialog):
    """管理员登录选框"""
    def __init__(self, has_face=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理员身份验证")
        self.resize(300, 160)
        self.choice = None
        self.setStyleSheet("""
            QDialog { background-color: #F5FCF5; }
            QPushButton {
                background-color: #FFFFFF; border: 1.5px solid #CDE6CD;
                border-radius: 12px; padding: 10px; font-weight: bold; color: #2E7D32; font-size: 13px;
            }
            QPushButton:hover { background-color: #E8F5E9; border-color: #81C784; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        lbl = QLabel("🔐 请选择管理员登录验证方式：", self)
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)

        btn_pwd = QPushButton("🔑 密码登录", self)
        btn_pwd.clicked.connect(self.select_pwd)
        layout.addWidget(btn_pwd)

        if has_face:
            btn_face = QPushButton("👤 管理员人脸识别登录", self)
            btn_face.clicked.connect(self.select_face)
            layout.addWidget(btn_face)

    def select_pwd(self):
        self.choice = 'password'
        self.accept()

    def select_face(self):
        self.choice = 'face'
        self.accept()


class PasswordInputDialog(QDialog):
    """输入密码弹窗"""
    def __init__(self, title="管理员密码验证", label_text="请输入管理员密码：", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(300, 140)
        self.setStyleSheet("""
            QDialog { background-color: #F5FCF5; }
            QLineEdit { border: 1.5px solid #CDE6CD; border-radius: 8px; padding: 6px; }
            QLineEdit:focus { border: 2px solid #5CAF5C; }
        """)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label_text, self))

        self.input_pwd = QLineEdit(self)
        self.input_pwd.setEchoMode(QLineEdit.Password)
        self.input_pwd.setPlaceholderText("初始密码为 123456")
        layout.addWidget(self.input_pwd)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_password(self):
        return self.input_pwd.text().strip()


class SaveUserDialog(QDialog):
    """员工录入多字段输入弹窗"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高精度人脸录入 - 员工档案")
        self.resize(320, 200)
        self.setStyleSheet("""
            QDialog { background-color: #F5FCF5; }
            QLabel { font-weight: bold; color: #2D4030; font-size: 13px; }
            QLineEdit {
                border: 1.5px solid #CDE6CD; border-radius: 8px;
                padding: 6px 10px; background-color: #FFFFFF;
                color: #1A2B1C; font-size: 13px; font-weight: bold;
            }
            QLineEdit:focus { border: 2px solid #5CAF5C; }
        """)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        self.input_id = QLineEdit(self)
        self.input_id.setPlaceholderText("工号纯数字，如: 101")
        self.input_name = QLineEdit(self)
        self.input_name.setPlaceholderText("请输入真实姓名")
        self.input_dept = QLineEdit(self)
        self.input_dept.setPlaceholderText("请输入所属部门")

        form_layout.addRow("员工编号:", self.input_id)
        form_layout.addRow("员工姓名:", self.input_name)
        form_layout.addRow("所属部门:", self.input_dept)
        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
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
        if is_user_exists(user_id):
            u_info = get_user_info(user_id)
            QMessageBox.warning(
                self, "录入提示", 
                f"⚠️ 编号为【{user_id}】的员工已存在！\n\n姓名：{u_info['name']}\n部门：{u_info['dept']}\n\n信息已存在，无需重复保存！"
            )
            return

        if not name or not dept:
            QMessageBox.warning(self, "校验失败", "姓名与部门均不能为空！")
            return

        self.accept()

    def get_data(self):
        return (int(self.input_id.text().strip()), self.input_name.text().strip(), self.input_dept.text().strip())


# ================= 水彩水果装饰图案绘制 =================
def generate_fresh_fruit_pixmap(width=140, height=140):
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    shadow_grad = QRadialGradient(70, 115, 45)
    shadow_grad.setColorAt(0, QColor(180, 210, 190, 80))
    shadow_grad.setColorAt(1, QColor(0, 0, 0, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(shadow_grad))
    painter.drawEllipse(15, 105, 110, 20)

    pomelo_grad = QRadialGradient(45, 55, 40)
    pomelo_grad.setColorAt(0, QColor(200, 235, 140))
    pomelo_grad.setColorAt(0.8, QColor(135, 195, 90))
    pomelo_grad.setColorAt(1, QColor(105, 165, 65))
    painter.setBrush(QBrush(pomelo_grad))
    painter.drawEllipse(10, 20, 80, 80)

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


# ================= 👁️ EAR 眨眼算法与余弦相似度算法 =================
def calculate_ear(landmarks, eye_indices, img_w, img_h):
    points = [np.array([landmarks[i].x * img_w, landmarks[i].y * img_h]) for i in eye_indices]
    v1 = np.linalg.norm(points[1] - points[5])
    v2 = np.linalg.norm(points[2] - points[4])
    h = np.linalg.norm(points[0] - points[3])
    return (v1 + v2) / (2.0 * h)

def compute_sim(feat1, feat2):
    return np.dot(feat1, feat2) / (np.linalg.norm(feat1) * np.linalg.norm(feat2))


# ================= 📇 信息更新与考勤状态判定 =================
def update_user_info_panel(user_id):
    global current_recognized_user
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    
    u_info = known_user_dict.get(user_id, get_user_info(user_id))

    work_start_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    work_end_time   = now.replace(hour=17, minute=30, second=0, microsecond=0)

    if attendance_type == 'on_duty':
        check_type_name = "上班"
        if now <= work_start_time:
            status_text = "✨ 早上好，签到成功！"
            status_color = "#3CB371"
        else:
            diff_sec = int((now - work_start_time).total_seconds())
            hrs, mins = diff_sec // 3600, (diff_sec % 3600) // 60
            late_str = f"{hrs}小时{mins}分钟" if hrs > 0 else f"{max(1, mins)}分钟"
            status_text = f"⚠️ 您迟到了 {late_str}"
            status_color = "#D9534F"
    else:
        check_type_name = "下班"
        if now < work_end_time:
            diff_sec = int((work_end_time - now).total_seconds())
            hrs, mins = diff_sec // 3600, (diff_sec % 3600) // 60
            early_str = f"{hrs}小时{mins}分钟" if hrs > 0 else f"{max(1, mins)}分钟"
            status_text = f"⚠️ 早退 {early_str}！下班快乐~"
            status_color = "#E67E22"
        else:
            diff_sec = int((now - work_end_time).total_seconds())
            hrs, mins = diff_sec // 3600, (diff_sec % 3600) // 60
            ot_str = f"{hrs}小时{mins}分钟" if hrs > 0 else f"{mins}分钟"
            status_text = f"🌙 已加班 {ot_str}！下班快乐~" if diff_sec >= 60 else "🌙 准时下班！下班快乐~"
            status_color = "#2E8B57"

    ui.lbl_id.setText(f"编 号：{user_id}")
    ui.lbl_name.setText(f"姓 名：{u_info['name']}")
    ui.lbl_dept.setText(f"部 门：{u_info['dept']}")
    ui.lbl_time.setText(f"打卡时间：{time_str} ({check_type_name})")
    ui.lbl_status.setText(status_text)
    ui.lbl_status.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 12px;")

    current_recognized_user = {
        "user_id": user_id, "name": u_info['name'], "dept": u_info['dept'],
        "check_type": check_type_name, "status": status_text
    }


# ================= 🎥 核心视频帧渲染逻辑 =================
def process_frame():
    global cap, ui, current_mode, blink_counter, total_blinks, eye_closed
    global is_face_recognized, is_liveness_verified, current_recognized_user

    if cap is None or not cap.isOpened():
        return

    res, frame = cap.read()
    if not res: return

    frame = cv.flip(frame, 1)  
    rgb_frame = cv.cvtColor(frame, cv.COLOR_BGR2RGB)
    h, w, c = frame.shape

    # 1. 预览模式
    if current_mode == 'preview':
        results = face_detector.process(rgb_frame)
        if results.detections:
            for detection in results.detections:
                bboxC = detection.location_data.relative_bounding_box
                xmin, ymin = int(bboxC.xmin * w), int(bboxC.ymin * h)
                box_w, box_h = int(bboxC.width * w), int(bboxC.height * h)
                cv.rectangle(frame, (xmin, ymin), (xmin + box_w, ymin + box_h), (144, 238, 144), 2)

    # 2. 步骤一：人脸识别模式
    elif current_mode == 'recog':
        faces = insight_app.get(frame)
        if len(faces) == 0:
            current_recognized_user = None
            is_face_recognized = False
        else:
            for face in faces:
                bbox = face.bbox.astype(int)
                xmin, ymin, xmax, ymax = bbox[0], bbox[1], bbox[2], bbox[3]
                embedding = face.embedding
                
                matched_id = None
                best_sim = 0.0
                if len(known_user_encodings) > 0:
                    sims = [compute_sim(embedding, target) for target in known_user_encodings]
                    best_idx = np.argmax(sims)
                    best_sim = sims[best_idx]
                    if best_sim > 0.45:
                        matched_id = known_user_ids[best_idx]

                if matched_id is not None:
                    u_name = known_user_dict[matched_id]['name']
                    color = (100, 200, 100)
                    sim_percent = best_sim * 100
                    text = f"{u_name} (ID:{matched_id}) {sim_percent:.1f}%"
                    
                    cv.putText(frame, text, (xmin, ymin - 10), cv.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    update_user_info_panel(matched_id)
                    
                    if not is_face_recognized:
                        is_face_recognized = True
                        update_status_tip(f"✅ 身份识别成功 ({u_name} - {sim_percent:.1f}%)！请点击【活体检测】按钮进行防伪验证。")
                else:
                    cv.putText(frame, "Unknown Person", (xmin, ymin - 10), cv.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 255), 2)
                    color = (100, 100, 255)
                    current_recognized_user = None
                    is_face_recognized = False

                cv.rectangle(frame, (xmin, ymin), (xmax, ymax), color, 2)

    # 3. 步骤二：活体眨眼检测模式
    elif current_mode == 'liveness':
        mesh_results = face_mesh_detector.process(rgb_frame)
        if mesh_results.multi_face_landmarks:
            for face_landmarks in mesh_results.multi_face_landmarks:
                left_eye_idx = [33, 160, 158, 133, 153, 144]
                right_eye_idx = [362, 385, 387, 263, 373, 380]

                left_ear = calculate_ear(face_landmarks.landmark, left_eye_idx, w, h)
                right_ear = calculate_ear(face_landmarks.landmark, right_eye_idx, w, h)
                avg_ear = (left_ear + right_ear) / 2.0

                if not is_liveness_verified:
                    if avg_ear < 0.21:
                        blink_counter += 1
                        if blink_counter >= 2: eye_closed = True
                    else:
                        if eye_closed:
                            total_blinks += 1
                            eye_closed = False
                            blink_counter = 0

                    cv.putText(frame, f"Blinks: {total_blinks}/2", (20, 40), cv.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 255), 2)
                    cv.putText(frame, "Liveness: Blink twice", (20, 80), cv.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 255), 2)

                    if total_blinks >= 2:
                        is_liveness_verified = True
                        update_status_tip("✨ 活体检测通过！身份与活体核验完毕，请点击【确认打卡】完成签到。")
                else:
                    cv.putText(frame, "Liveness: PASSED", (20, 40), cv.FONT_HERSHEY_SIMPLEX, 0.8, (100, 200, 100), 2)

    # Qt 画布渲染
    bytesperline = 3 * w
    qimg = QImage(frame.data, w, h, bytesperline, QImage.Format_RGB888).rgbSwapped().copy()
    ui.cam.setAlignment(Qt.AlignCenter)
    ui.cam.setPixmap(QPixmap.fromImage(qimg))


# ================= 🔐 管理员模式与权限切换 =================

def toggle_admin_mode():
    """切换管理员模式（密码/人脸解锁逻辑）"""
    global is_admin_mode
    if is_admin_mode:
        # 切回普通员工模式
        is_admin_mode = False
        ui.btn_admin_toggle.setText("🔑 管理员模式")
        ui.btn_admin_toggle.setStyleSheet("""
            QPushButton#btn_admin_toggle {
                background-color: #E8EAF6; border: 1.5px solid #C5CAE9;
                color: #3F51B5; border-radius: 10px; font-size: 12px; font-weight: bold;
            }
            QPushButton#btn_admin_toggle:hover { background-color: #C5CAE9; }
        """)
        ui.export_widget.hide()
        ui.admin_tools_widget.hide()
        update_status_tip("🍃 已退出管理员模式，当前为员工打卡状态")
        return

    admin_face = get_admin_face_encoding()
    has_admin_face = admin_face is not None

    # 弹窗询问登录方式
    login_dlg = AdminLoginDialog(has_face=has_admin_face)
    if login_dlg.exec() != QDialog.Accepted:
        return

    # 1. 密码验证逻辑
    if login_dlg.choice == 'password':
        pwd_dlg = PasswordInputDialog()
        if pwd_dlg.exec() == QDialog.Accepted:
            if pwd_dlg.get_password() == get_admin_password():
                unlock_admin_success()
            else:
                QMessageBox.critical(None, "验证失败", "❌ 密码错误，无法进入管理员模式！")

    # 2. 人脸识别验证逻辑
    elif login_dlg.choice == 'face':
        if cap is None or not cap.isOpened():
            start_camera()
            time.sleep(0.3)
        
        # 抓取当前帧验证人脸
        ret, frame = cap.read()
        if ret:
            faces = insight_app.get(frame)
            if len(faces) > 0:
                current_feat = faces[0].embedding
                sim = compute_sim(current_feat, admin_face)
                if sim > 0.45:
                    unlock_admin_success(f" (人脸匹配度: {sim*100:.1f}%)")
                else:
                    QMessageBox.warning(None, "识别失败", f"❌ 人脸不匹配 (相似度仅 {sim*100:.1f}%)，无法解锁！")
            else:
                QMessageBox.warning(None, "识别失败", "未检测到清晰面部，请面向摄像头重试！")

def unlock_admin_success(msg=""):
    """管理员验证成功通用触发逻辑"""
    global is_admin_mode
    is_admin_mode = True
    ui.btn_admin_toggle.setText("🔓 退出管理")
    ui.btn_admin_toggle.setStyleSheet("""
        QPushButton#btn_admin_toggle {
            background-color: #FFEBEE; border: 1.5px solid #EF9A9A;
            color: #C62828; border-radius: 10px; font-size: 12px; font-weight: bold;
        }
        QPushButton#btn_admin_toggle:hover { background-color: #FFCDD2; }
    """)
    ui.export_widget.show()
    ui.admin_tools_widget.show()
    update_status_tip(f"🎉 成功登录管理员模式{msg}！功能已完全解锁。")

def record_admin_face():
    """录入/更新管理员人脸特征"""
    global cap
    if cap is None or not cap.isOpened():
        start_camera()
        time.sleep(0.3)
        
    ret, frame = cap.read()
    if ret:
        faces = insight_app.get(frame)
        if len(faces) > 0:
            feat_bytes = faces[0].embedding.astype(np.float32).tobytes()
            save_admin_face_encoding(feat_bytes)
            QMessageBox.information(None, "录入成功", "🎉 管理员人脸特征已成功录入/更新！下次可直接通过人脸登录。")
        else:
            QMessageBox.warning(None, "录入失败", "未检测到面部，请面向摄像头！")

def change_admin_password():
    """修改管理员密码"""
    dlg = PasswordInputDialog(title="修改管理员密码", label_text="请输入新的管理员密码：")
    if dlg.exec() == QDialog.Accepted:
        new_pwd = dlg.get_password()
        if new_pwd:
            set_admin_password(new_pwd)
            QMessageBox.information(None, "修改成功", "🎉 管理员密码修改成功！新密码已保存生效。")
        else:
            QMessageBox.warning(None, "错误", "密码不能为空！")


# ================= 按钮交互逻辑与步骤顺序拦截 =================
def on_confirm_checkin_click():
    """步骤三：确认打卡"""
    global is_face_recognized, is_liveness_verified, current_recognized_user
    
    if not is_face_recognized or current_recognized_user is None:
        QMessageBox.warning(
            None, "打卡顺序错误", 
            "⚠️ 步骤错误！请先点击左侧【识别】按钮，面向摄像头确认您的员工身份！"
        )
        return

    if not is_liveness_verified:
        QMessageBox.warning(
            None, "打卡顺序错误", 
            f"⚠️ 步骤错误！已识别您为【{current_recognized_user['name']}】，但尚未进行活体验证！\n\n请点击【活体检测】按钮，自然眨眼 2 次完成防伪验证后再打卡。"
        )
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    u = current_recognized_user

    log_attendance_to_db(u["user_id"], u["name"], u["dept"], u["check_type"], now_str, u["status"])

    QMessageBox.information(
        None, "打卡成功", 
        f"🎉 考勤打卡成功！\n\n工号：{u['user_id']}\n姓名：{u['name']}\n部门：{u['dept']}\n类型：{u['check_type']}打卡\n时间：{now_str}\n状态：{u['status']}"
    )
    update_status_tip(f"✅ {u['name']} ({u['dept']}) 打卡记录已成功写入数据库！")
    
    is_face_recognized = False
    is_liveness_verified = False

def update_status_tip(text):
    if hasattr(ui, 'statusLabel'): ui.statusLabel.setText(text)

def toggle_attendance_mode():
    global attendance_type
    if attendance_type == 'on_duty':
        attendance_type = 'off_duty'
        ui.btn_type_toggle.setText("🌙 当前模式：下班签退 (点击切换)")
        ui.btn_type_toggle.setStyleSheet("QPushButton#btn_type_toggle { background-color: #FFF3E0; border: 1.5px solid #FFB74D; color: #E65100; border-radius: 12px; font-size: 12px; font-weight: bold; }")
        update_status_tip("🌙 考勤模式已切换为：下班签退")
    else:
        attendance_type = 'on_duty'
        ui.btn_type_toggle.setText("🌞 当前模式：上班签到 (点击切换)")
        ui.btn_type_toggle.setStyleSheet("QPushButton#btn_type_toggle { background-color: #E8F5E9; border: 1.5px solid #81C784; color: #2E7D32; border-radius: 12px; font-size: 12px; font-weight: bold; }")
        update_status_tip("🌞 考勤模式已切换为：上班签到")

def start_camera():
    global cap, timer
    if cap is None: cap = cv.VideoCapture(0)
    if timer is None:
        timer = QTimer()
        timer.timeout.connect(process_frame)
    if not timer.isActive(): timer.start(30)

def stop_camera():
    global cap, timer, ui, current_recognized_user
    current_recognized_user = None
    if timer is not None and timer.isActive(): timer.stop()
    if cap is not None:
        cap.release()
        cap = None
    if ui is not None:
        ui.cam.clear()
        ui.cam.setText("🍃 摄像头已关闭")

def on_open_click():
    global current_mode, cap, is_face_recognized, is_liveness_verified
    if cap is None:
        current_mode = 'preview'
        is_face_recognized = False
        is_liveness_verified = False
        start_camera()
        ui.openButton.setText("关闭摄像头")
        update_status_tip("🍃 模式：MediaPipe 实时预览中，请点击【识别】开始打卡...")
    else:
        stop_camera()
        ui.openButton.setText("打开摄像头")
        update_status_tip("✨ 系统就绪，请选择功能操作")

def on_save_click():
    """保存新员工档案与人脸向量"""
    global cap, current_mode
    if cap is not None and cap.isOpened():
        ret, frame = cap.read()
        if ret:
            faces = insight_app.get(frame)
            if len(faces) > 0:
                face_encoding = faces[0].embedding
                dialog = SaveUserDialog()
                if dialog.exec() == QDialog.Accepted:
                    user_id, name, dept = dialog.get_data()
                    
                    encoding_bytes = face_encoding.astype(np.float32).tobytes()
                    save_user_to_db(user_id, name, dept, encoding_bytes)
                    refresh_known_faces_cache()
                    
                    QMessageBox.information(
                        None, "录入成功", 
                        f"🎉 高精度人脸特征录入成功！\n\n工号：{user_id}\n姓名：{name}\n部门：{dept}\n\n特征向量已保存！"
                    )
                    update_status_tip(f"成功录入：{name} ({dept})")
                    current_mode = 'recog'
            else:
                QMessageBox.warning(None, "检测失败", "未识别到面部，请面向摄像头！")

def on_recog_click():
    """步骤一：人脸识别"""
    global current_mode, is_face_recognized, is_liveness_verified
    if len(known_user_ids) == 0:
        QMessageBox.warning(None, "提示", "数据库中尚无已保存的员工特征，请先保存录入人脸！")
        return
    
    is_face_recognized = False
    is_liveness_verified = False
    current_mode = 'recog'
    start_camera()
    update_status_tip("🔍 步骤 1/2：正在进行人脸识别，请面向摄像头...")

def on_persion_click():
    """步骤二：活体检测"""
    global current_mode, blink_counter, total_blinks, eye_closed
    global is_face_recognized, is_liveness_verified

    if not is_face_recognized or current_recognized_user is None:
        QMessageBox.warning(
            None, "活体检测受阻", 
            "⚠️ 步骤错误！请先点击【识别】按钮完成人脸身份识别后，再进行活体检测！"
        )
        return

    blink_counter, total_blinks = 0, 0
    eye_closed = False
    is_liveness_verified = False
    current_mode = 'liveness'
    
    start_camera()
    update_status_tip("👁️ 步骤 2/2：请面向摄像头自然眨眼 2 次完成活体验证")


# ================= QSS 视觉样式表 =================
SUPER_FRESH_QSS = """
QWidget#win {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F2FAF2, stop:0.5 #E8F7E8, stop:1 #F5FCF5);
    font-family: "Microsoft YaHei", sans-serif; color: #2D4030;
}
QLabel#statusLabel {
    background-color: rgba(255, 255, 255, 0.85); border: 1px solid #D6EBD6;
    border-radius: 12px; padding: 6px 15px; font-size: 13px; font-weight: bold; color: #3B7A57;
}
QWidget#infoCard {
    background-color: rgba(255, 255, 255, 0.88); border: 1.5px solid #D1E8D1; border-radius: 18px;
}
QWidget#infoCard QLabel { font-size: 13px; color: #2E4030; font-weight: 500; }
QPushButton {
    background-color: #FFFFFF; border: 1.5px solid #CDE6CD; border-radius: 18px;
    padding: 10px 16px; font-size: 14px; font-weight: bold; color: #3B7A57; min-width: 85px; min-height: 20px;
}
QPushButton:hover { background-color: #E2F5E2; border-color: #8FD88F; color: #1E5631; }
QPushButton:pressed { background-color: #C8ECC8; }
"""


# ================= 程序主入口 =================
def showUi():
    global ui
    app = QApplication([])
    win = QWidget()
    win.setObjectName("win")
    ui = Ui_Form()
    ui.setupUi(win)
    
    win.setWindowTitle("公司智能人脸识别考勤系统")
    win.resize(820, 580)
    app.setStyleSheet(SUPER_FRESH_QSS)

    for widget in win.findChildren(QLabel):
        if widget.text() == "人脸识别": widget.hide()

    ui.cam.setStyleSheet("background-color: #EAF7EA; border: 2.5px solid #C5E5C5; border-radius: 20px; color: #3B7A57; font-size: 15px; font-weight: bold;")
    
    ui.statusLabel = QLabel("✨ 系统初始化完成，请遵循规范顺序打卡...", win)
    ui.statusLabel.setObjectName("statusLabel")
    ui.statusLabel.setAlignment(Qt.AlignCenter)
    ui.statusLabel.setGeometry(30, 15, 460, 32)

    ui.decLabel = QLabel(win)
    ui.decLabel.setObjectName("decLabel")
    ui.decLabel.setPixmap(generate_fresh_fruit_pixmap(140, 140))
    ui.decLabel.setGeometry(820 - 145, 580 - 140, 140, 140)
    ui.decLabel.lower()

    cam_shadow = QGraphicsDropShadowEffect()
    cam_shadow.setBlurRadius(20)
    cam_shadow.setColor(QColor(80, 150, 100, 30))
    cam_shadow.setOffset(0, 4)
    ui.cam.setGraphicsEffect(cam_shadow)

    # 1. 右上 4 功能按钮组
    btn_panel = QWidget(win)
    grid_layout = QGridLayout(btn_panel)
    grid_layout.setSpacing(10)
    grid_layout.addWidget(ui.openButton, 0, 0)
    grid_layout.addWidget(ui.saveButton, 0, 1)
    grid_layout.addWidget(ui.recogButton, 1, 0)
    grid_layout.addWidget(ui.persionButton, 1, 1)
    btn_panel.setGeometry(525, 28, 275, 110)

    # 2. 员工信息卡片
    infoCard = QWidget(win)
    infoCard.setObjectName("infoCard")
    info_layout = QVBoxLayout(infoCard)
    info_layout.setContentsMargins(16, 8, 16, 8)
    info_layout.setSpacing(3)

    ui.lbl_id = QLabel("编 号：--")
    ui.lbl_name = QLabel("姓 名：未识别")
    ui.lbl_dept = QLabel("部 门：--")
    ui.lbl_time = QLabel("打卡时间：--:--:--")
    ui.lbl_status = QLabel("状态：等待识别打卡...")
    ui.lbl_status.setWordWrap(True)
    ui.lbl_status.setStyleSheet("color: #888; font-style: italic;")

    info_layout.addWidget(ui.lbl_id)
    info_layout.addWidget(ui.lbl_name)
    info_layout.addWidget(ui.lbl_dept)
    info_layout.addWidget(ui.lbl_time)
    info_layout.addWidget(ui.lbl_status)
    infoCard.setGeometry(525, 148, 275, 160)

    # 3. 考勤模式切换按钮
    ui.btn_type_toggle = QPushButton("🌞 当前模式：上班签到 (点击切换)", win)
    ui.btn_type_toggle.setObjectName("btn_type_toggle")
    ui.btn_type_toggle.setGeometry(525, 320, 275, 36)
    ui.btn_type_toggle.setStyleSheet("QPushButton#btn_type_toggle { background-color: #E8F5E9; border: 1.5px solid #81C784; color: #2E7D32; border-radius: 12px; font-size: 12px; font-weight: bold; }")
    ui.btn_type_toggle.clicked.connect(toggle_attendance_mode)

    # 4. 确认打卡按钮
    ui.btn_confirm_checkin = QPushButton("✅ 确认打卡", win)
    ui.btn_confirm_checkin.setObjectName("btn_confirm_checkin")
    ui.btn_confirm_checkin.setGeometry(525, 370, 275, 42)
    ui.btn_confirm_checkin.setStyleSheet("""
        QPushButton#btn_confirm_checkin {
            background-color: #4CAF50; border: 1.5px solid #388E3C;
            color: #FFFFFF; border-radius: 14px; font-size: 15px; font-weight: bold;
        }
        QPushButton#btn_confirm_checkin:hover { background-color: #43A047; }
    """)
    ui.btn_confirm_checkin.clicked.connect(on_confirm_checkin_click)

    # 5. 🔑 左下角管理员模式切换按钮
    ui.btn_admin_toggle = QPushButton("🔑 管理员模式", win)
    ui.btn_admin_toggle.setObjectName("btn_admin_toggle")
    ui.btn_admin_toggle.setGeometry(30, 525, 120, 36)
    ui.btn_admin_toggle.setStyleSheet("""
        QPushButton#btn_admin_toggle {
            background-color: #E8EAF6; border: 1.5px solid #C5CAE9;
            color: #3F51B5; border-radius: 10px; font-size: 12px; font-weight: bold;
        }
        QPushButton#btn_admin_toggle:hover { background-color: #C5CAE9; }
    """)
    ui.btn_admin_toggle.clicked.connect(toggle_admin_mode)

    # 6. 📊 导出 Excel 按钮组（管理员专属，默认隐藏）
    ui.export_widget = QWidget(win)
    export_layout = QHBoxLayout(ui.export_widget)
    export_layout.setContentsMargins(0, 0, 0, 0)
    export_layout.setSpacing(12)

    btn_export_users = QPushButton("📊 导出员工表", ui.export_widget)
    btn_export_attendance = QPushButton("📊 导出考勤表", ui.export_widget)

    btn_export_users.setStyleSheet("""
        QPushButton {
            background-color: #EBF3FA; border: 1.5px solid #ADCBE3;
            color: #2B5B84; font-size: 12px; border-radius: 10px; padding: 6px;
        }
        QPushButton:hover { background-color: #D6E6F2; }
    """)
    btn_export_attendance.setStyleSheet("""
        QPushButton {
            background-color: #EBF3FA; border: 1.5px solid #ADCBE3;
            color: #2B5B84; font-size: 12px; border-radius: 10px; padding: 6px;
        }
        QPushButton:hover { background-color: #D6E6F2; }
    """)

    btn_export_users.clicked.connect(export_users_to_excel)
    btn_export_attendance.clicked.connect(export_attendance_to_excel)

    export_layout.addWidget(btn_export_users)
    export_layout.addWidget(btn_export_attendance)
    ui.export_widget.setGeometry(525, 426, 275, 36)
    ui.export_widget.hide()  # 默认隐藏

    # 7. 🛠️ 管理员管理工具组 (录入人脸/修改密码)
    ui.admin_tools_widget = QWidget(win)
    admin_tools_layout = QHBoxLayout(ui.admin_tools_widget)
    admin_tools_layout.setContentsMargins(0, 0, 0, 0)
    admin_tools_layout.setSpacing(10)

    btn_rec_admin_face = QPushButton("👤 录入管理员人脸", ui.admin_tools_widget)
    btn_change_pwd = QPushButton("🔑 修改密码", ui.admin_tools_widget)

    btn_rec_admin_face.setStyleSheet("QPushButton { background-color: #FFF3E0; border: 1px solid #FFE0B2; color: #E65100; font-size: 11px; border-radius: 8px; padding: 5px; }")
    btn_change_pwd.setStyleSheet("QPushButton { background-color: #FFF3E0; border: 1px solid #FFE0B2; color: #E65100; font-size: 11px; border-radius: 8px; padding: 5px; }")

    btn_rec_admin_face.clicked.connect(record_admin_face)
    btn_change_pwd.clicked.connect(change_admin_password)

    admin_tools_layout.addWidget(btn_rec_admin_face)
    admin_tools_layout.addWidget(btn_change_pwd)
    ui.admin_tools_widget.setGeometry(160, 525, 240, 36)
    ui.admin_tools_widget.hide()  # 默认隐藏

    ui.openButton.clicked.connect(on_open_click)
    ui.saveButton.clicked.connect(on_save_click)
    ui.recogButton.clicked.connect(on_recog_click)
    ui.persionButton.clicked.connect(on_persion_click)

    ui.cam.setText("🍃 请点击右上角按钮开启功能")
    ui.cam.setAlignment(Qt.AlignCenter)

    win.show()
    app.exec()

if __name__ == "__main__":
    showUi()