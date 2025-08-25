import sys
import socket
import struct
import threading
import time
import numpy as np
import cv2

try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QLabel, QPushButton, QLineEdit, QListWidget,
        QVBoxLayout, QHBoxLayout, QSizePolicy, QTabWidget,
        QGroupBox, QMessageBox, QFileDialog, QSlider, QCheckBox, QFormLayout, QFrame
    )
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QImage, QPixmap, QFont
except ModuleNotFoundError:
    print("Erro: PyQt5 não está instalado. Use 'pip install PyQt5'")
    sys.exit(1)

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

HOST = '127.0.0.1'
PORT = 65432

class VideoClient(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("I/O Eye Viewer (PyQt5)")
        self.dark_theme = True
        self.resize(1280, 720)

        self.client_socket = None
        self.running = False
        self.unidades = []
        self.timestamps = []
        self.total_produtos = 0
        self.last_update_time = None

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_video)

        self.init_ui()
        self.apply_theme()
        self.start_video()

    def apply_theme(self):
        if self.dark_theme:
            self.setStyleSheet("""
                QWidget { background-color: #000; color: #fff; }
                QLineEdit { background-color: #333; color: #fff; border: 1px solid #888; padding: 3px; }
                QListWidget { background-color: #222; color: #fff; border: 1px solid #555; }
                QGroupBox { border: 1px solid #555; margin-top: 6px; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
                QPushButton { background-color: #444; color: #fff; border: 1px solid #666; padding: 4px; }
                QPushButton:hover { background-color: #555; }
                QFrame#line { background-color: #666; max-width: 1px; }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background-color: #fff; color: #000; }
                QLineEdit { background-color: #fff; color: #000; border: 1px solid #aaa; padding: 3px; }
                QListWidget { background-color: #fafafa; color: #000; border: 1px solid #ccc; }
                QGroupBox { border: 1px solid #ccc; margin-top: 6px; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
                QPushButton { background-color: #eee; color: #000; border: 1px solid #aaa; padding: 4px; }
                QPushButton:hover { background-color: #ddd; }
                QFrame#line { background-color: #ccc; max-width: 1px; }
            """)

        self.update_graph_theme()

    def update_graph_theme(self):
        if not hasattr(self, "ax"):
            return

        if self.dark_theme:
            self.figure.patch.set_facecolor("#000")
            self.ax.set_facecolor("#111")
            self.ax.tick_params(colors="white")
            for spine in self.ax.spines.values():
                spine.set_color("white")
            self.ax.grid(color="#555")
            self.line.set_color("#00ffcc")
        else:
            self.figure.patch.set_facecolor("#fff")
            self.ax.set_facecolor("#fff")
            self.ax.tick_params(colors="black")
            for spine in self.ax.spines.values():
                spine.set_color("black")
            self.ax.grid(color="#ccc")
            self.line.set_color("#0077cc")

        self.canvas.draw_idle()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # --- Aba Viewer ---
        self.visual_tab = QWidget()
        visual_layout = QHBoxLayout(self.visual_tab)

        self.video_label = QLabel("Viewer")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        visual_layout.addWidget(self.video_label, stretch=3)

        # Linha divisória
        line = QFrame()
        line.setObjectName("line")
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        visual_layout.addWidget(line)

        # Config Panel
        config_box = QVBoxLayout()

        ip_layout = QHBoxLayout()
        ip_label = QLabel("Faixa IP:")
        ip_layout.addWidget(ip_label)
        self.ip_inputs = []
        for _ in range(3):
            box = QLineEdit()
            box.setMaxLength(3)
            box.setFixedWidth(50)
            self.ip_inputs.append(box)
            ip_layout.addWidget(box)
        config_box.addLayout(ip_layout)

        porta_layout = QHBoxLayout()
        porta_label = QLabel("Porta:")
        self.port_input = QLineEdit("65432")
        self.port_input.setFixedWidth(80)
        porta_layout.addWidget(porta_label)
        porta_layout.addWidget(self.port_input)
        config_box.addLayout(porta_layout)

        self.buscar_btn = QPushButton("BUSCAR IP")
        self.buscar_btn.clicked.connect(self.buscar_dispositivos)
        config_box.addWidget(self.buscar_btn)

        self.device_list = QListWidget()
        config_box.addWidget(self.device_list)

        self.connect_btn = QPushButton("CONECTAR")
        self.connect_btn.clicked.connect(self.conectar_socket)
        config_box.addWidget(self.connect_btn)

        total_layout = QHBoxLayout()
        self.total_label = QLabel("TOTAL:")
        self.total_value = QLabel("0")
        total_layout.addWidget(self.total_label)
        total_layout.addWidget(self.total_value)
        config_box.addLayout(total_layout)

        media_layout = QHBoxLayout()
        self.media_label = QLabel("MÉDIA/H:")
        self.media_value = QLabel("0")
        media_layout.addWidget(self.media_label)
        media_layout.addWidget(self.media_value)
        config_box.addLayout(media_layout)

        visual_layout.addLayout(config_box, stretch=1)
        self.tabs.addTab(self.visual_tab, "Viewer")

        # --- Aba Rendimento ---
        self.tema_tab = QWidget()
        tema_layout = QVBoxLayout(self.tema_tab)
        self.figure = Figure(figsize=(6, 3))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.line, = self.ax.plot([], [], marker='o')
        tema_layout.addWidget(self.canvas)
        self.tabs.addTab(self.tema_tab, "Rendimento")

        # --- Aba Ferramentas ---
        self.ferramentas_tab = QWidget()
        ferramentas_layout = QHBoxLayout(self.ferramentas_tab)

        layout_group = QGroupBox("Layout")
        layout_form = QFormLayout()

        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(8, 32)
        self.font_slider.setValue(12)
        self.font_slider.valueChanged.connect(self.ajustar_fonte)
        layout_form.addRow("Tamanho da Fonte", self.font_slider)

        self.theme_switch = QCheckBox("Tema Claro/Escuro")
        self.theme_switch.stateChanged.connect(self.trocar_tema)
        layout_form.addRow(self.theme_switch)

        layout_group.setLayout(layout_form)

        device_group = QGroupBox("Device")
        device_form = QFormLayout()

        file_layout = QHBoxLayout()
        self.model_input = QLineEdit()
        self.file_btn = QPushButton("Procurar")
        self.file_btn.clicked.connect(self.abrir_arquivo)
        file_layout.addWidget(self.model_input)
        file_layout.addWidget(self.file_btn)
        device_form.addRow("Arquivo de Modelo", file_layout)

        self.send_btn = QPushButton("Enviar")
        device_form.addRow(self.send_btn)

        self.res_slider = QSlider(Qt.Horizontal)
        self.res_slider.setRange(25, 100)
        self.res_slider.setSingleStep(25)
        self.res_slider.setValue(25)
        device_form.addRow("Resolução", self.res_slider)

        self.restart_btn = QPushButton("Reiniciar")
        self.restart_btn.clicked.connect(self.reiniciar)
        device_form.addRow(self.restart_btn)

        self.reset_btn = QPushButton("Reset de Fábrica")
        self.reset_btn.clicked.connect(self.reset_fabrica)
        device_form.addRow(self.reset_btn)

        device_group.setLayout(device_form)

        ferramentas_layout.addWidget(layout_group, stretch=1)
        ferramentas_layout.addWidget(device_group, stretch=1)
        self.tabs.addTab(self.ferramentas_tab, "Ferramentas")

    def start_video(self):
        if not self.running:
            self.running = True
            self.timer.start(30)
            threading.Thread(target=self.connect_and_receive, daemon=True).start()

    def connect_and_receive(self):
        while self.running:
            try:
                if self.client_socket is None:
                    time.sleep(0.5)
                else:
                    frame = self.receber_frame()
                    if frame is not None:
                        self.latest_frame = frame
            except Exception as e:
                print(f"Erro de conexão: {e}")
                if self.client_socket:
                    self.client_socket.close()
                    self.client_socket = None
                self.latest_frame = self.gerar_frame_exemplo()
                time.sleep(1)

    def conectar_socket(self):
        try:
            ip_parts = [box.text() for box in self.ip_inputs]
            ip = ".".join(ip_parts) + ".1"
            porta = int(self.port_input.text())
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, porta))
            QMessageBox.information(self, "Conexão", f"Conectado a {ip}:{porta}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao conectar: {e}")

    def receber_frame(self):
        try:
            size_data = self.client_socket.recv(4)
            if len(size_data) < 4:
                return None
            frame_size = struct.unpack(">I", size_data)[0]
            frame_data = b''
            while len(frame_data) < frame_size:
                more = self.client_socket.recv(frame_size - len(frame_data))
                if not more:
                    return None
                frame_data += more
            frame = cv2.imdecode(np.frombuffer(frame_data, dtype=np.uint8), cv2.IMREAD_COLOR)
            return frame
        except:
            return None

    def gerar_frame_exemplo(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(frame, 'SEM VIDEO', (240, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        return frame

    def update_video(self):
        if hasattr(self, "latest_frame"):
            frame = cv2.cvtColor(self.latest_frame, cv2.COLOR_BGR2RGB)
            viewer_width = self.video_label.width()
            viewer_height = int(viewer_width * 9 / 16)
            frame = cv2.resize(frame, (viewer_width, viewer_height), interpolation=cv2.INTER_LINEAR)
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            self.video_label.setPixmap(QPixmap.fromImage(qimg))

            self.total_produtos += 1
            self.total_value.setText(str(self.total_produtos))

            now = time.time()
            if self.last_update_time:
                elapsed = now - self.last_update_time
                if elapsed > 0:
                    media_hora = (self.total_produtos / elapsed) * 3600
                    self.media_value.setText(f"{media_hora:.2f}")
            self.last_update_time = now

            self.unidades.append(self.total_produtos)
            self.timestamps.append(time.strftime("%H:%M:%S"))
            self.update_graph()

    def update_graph(self):
        self.unidades = self.unidades[-30:]
        self.timestamps = self.timestamps[-30:]
        self.line.set_xdata(np.arange(len(self.unidades)))
        self.line.set_ydata(self.unidades)
        self.ax.set_xlim(0, max(1, len(self.unidades)))
        self.ax.set_ylim(0, max(self.unidades) + 5 if self.unidades else 10)
        self.ax.set_xticks(np.arange(len(self.timestamps)))
        self.ax.set_xticklabels(self.timestamps, rotation=45, fontsize=8)
        self.canvas.draw()

    def buscar_dispositivos(self):
        try:
            ip_parts = [int(box.text()) for box in self.ip_inputs]
            if any(p < 0 or p > 255 for p in ip_parts):
                raise ValueError
        except:
            QMessageBox.critical(self, "Erro", "Digite um IP válido (0-255 em cada campo)")
            return

        base_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}."
        try:
            porta = int(self.port_input.text())
        except:
            porta = 65432

        self.device_list.clear()
        for i in range(1, 255):
            ip = f"{base_ip}{i}"
            try:
                s = socket.create_connection((ip, porta), timeout=0.05)
                s.close()
                self.device_list.addItem(ip)
            except:
                pass
        if self.device_list.count() == 0:
            self.device_list.addItem("Nenhum dispositivo encontrado")

    def ajustar_fonte(self, value):
        font = QFont()
        font.setPointSize(value)
        self.setFont(font)

    def trocar_tema(self, state):
        self.dark_theme = state != Qt.Checked
        self.apply_theme()

    def abrir_arquivo(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Abrir arquivo de modelo', '', 'Todos os arquivos (*)')
        if fname:
            self.model_input.setText(fname)

    def reiniciar(self):
        QMessageBox.information(self, "Reiniciar", "Reiniciando...")
        self.running = False
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None
        self.start_video()

    def reset_fabrica(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Reset de Fábrica")
        msg.setText("Você quer mesmo realizar o reset de fábrica?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        result = msg.exec_()
        if result == QMessageBox.Yes:
            QMessageBox.warning(self, "Reset de Fábrica", "O dispositivo foi resetado para configuração de fábrica.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = VideoClient()
    window.setMinimumSize(800, 600)
    window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    window.show()
    sys.exit(app.exec_())
