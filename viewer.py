import sys
import socket
import struct
import threading
import time
import numpy as np
import cv2

try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QLabel, QPushButton, QLineEdit,
        QSlider, QVBoxLayout, QHBoxLayout, QFileDialog, QGroupBox, QFormLayout,
        QGridLayout, QSizePolicy, QTabWidget, QComboBox
    )
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QImage, QPixmap
except ModuleNotFoundError as e:
    print("Erro: PyQt5 não está instalado. Use 'pip install PyQt5' para instalar.")
    sys.exit(1)

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

HOST = '127.0.0.1'
PORT = 65432

class VideoClient(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("I/O Eye Viewer (PyQt5)")
        self.setStyleSheet("background-color: black")
        self.resize(1280, 720)

        self.client_socket = None
        self.running = False
        self.unidades = []
        self.timestamps = []
    
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_video)
        self.init_ui()
        self.start_video()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.setStyleSheet("background-color: #1e1e1e; color: white")

        main_tab = QWidget()
        main_tab.setStyleSheet("background-color: #1e1e1e;")
        main_layout = QGridLayout(main_tab)
        self.tabs.addTab(main_tab, "Visualização")
        self.tabs.addTab(QWidget(), "Tema")
        self.tabs.addTab(QWidget(), "Ferramentas")

        # === Viewer ===
        self.video_label = QLabel("Viewer")
        self.video_label.setStyleSheet("background-color: black; color: white")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        main_layout.addWidget(self.video_label, 0, 0, 1, 2, alignment=Qt.AlignTop)

        # === Graph ===
        self.figure = Figure(figsize=(6, 3), facecolor="#1e1e1e")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(200)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("Unidades por Hora", color="white")
        self.ax.set_facecolor("#1e1e1e")
        self.ax.tick_params(colors="white")
        self.ax.grid(True, linestyle="--", linewidth=0.5, color="#444")
        self.line, = self.ax.plot([], [], color="#00ffcc", marker='o')
        main_layout.addWidget(self.canvas, 1, 0, 1, 2, alignment=Qt.AlignTop)

        # === Config Panel ===
        config_layout = QFormLayout()

        self.source_input = QComboBox()
        self.source_input.setEditable(False)  
        self.source_input.setStyleSheet("background-color: #2b2b2b; color: white; border: 1px solid #555;")
        self.source_input.mousePressEvent = lambda event: self.buscar_dispositivos(event)  # quando clicar, faz a busca
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(25, 100)
        self.scale_slider.setValue(100)
        
        self.ip_input = QLineEdit()
        self.model_input = QLineEdit()
        self.model_button = QPushButton("Buscar Modelo")
        self.model_button.clicked.connect(self.browse_model)

        self.start_button = QPushButton("Iniciar Vídeo")
        self.start_button.clicked.connect(self.start_video)

        self.source_input.setStyleSheet("background-color: #2b2b2b; color: white; border: 1px solid #555;")
        self.ip_input.setStyleSheet("background-color: #2b2b2b; color: white; border: 1px solid #555;")
        self.model_input.setStyleSheet("background-color: #2b2b2b; color: white; border: 1px solid #555;")

        # self.scale_slider.setStyleSheet("""
        #     QSlider::groove:horizontal {
        #         background: #555;
        #         height: 8px;
        #         border-radius: 4px;
        #     }
        #     QSlider::handle:horizontal {
        #         background: #00ffcc;
        #         border: 1px solid #444;
        #         width: 16px;
        #         margin: -4px 0;
        #         border-radius: 8px;
        #     }
        # """)

        
        config_layout.addRow("Fonte de Vídeo:", self.source_input)
        config_layout.addRow("Escala do Vídeo:", self.scale_slider)
        config_layout.addRow("IP de Envio:", self.ip_input)
        config_layout.addRow("Modelo (arquivo):", self.model_input)
        config_layout.addRow("", self.model_button)
        config_layout.addRow("", self.start_button)

        config_box = QGroupBox("Configurações")
        config_box.setLayout(config_layout)
        config_box.setStyleSheet("color: white;")
        config_box.setMaximumWidth(300)
        main_layout.addWidget(config_box, 0, 2, 2, 1)

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar Modelo")
        if path:
            self.model_input.setText(path)

    def start_video(self):
        if not self.running:
            self.running = True
            self.timer.start(30)
            threading.Thread(target=self.connect_and_receive, daemon=True).start()

    def connect_and_receive(self):
        while self.running:
            try:
                if self.client_socket is None:
                    print("Tentando conectar...")
                    self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.client_socket.connect((HOST, PORT))
                    print("Conectado ao servidor.")

                while self.running:
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

            self.unidades.append(len(self.unidades) + 1)
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
        self.ax.set_xticklabels(self.timestamps, rotation=45, fontsize=8, color="white")
        self.canvas.draw()

    def buscar_dispositivos(self, event):
        self.source_input.clear()
        base_ip = "127.0.0."   # ajuste para sua rede
        porta = 65432

        for i in range(1, 255):
            ip = f"{base_ip}{i}"
            try:
                s = socket.create_connection((ip, porta), timeout=0.1)
                s.close()
                self.source_input.addItem(ip)
            except:
                pass

        if self.source_input.count() == 0:
            self.source_input.addItem("Nenhum dispositivo encontrado")

        # mantém o comportamento padrão do clique
        QComboBox.mousePressEvent(self.source_input, event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = VideoClient()
    window.setMinimumSize(800, 600)
    window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    window.show()
    sys.exit(app.exec_())
