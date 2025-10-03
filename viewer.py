import sys
import socket
import struct
import threading
import time
import json
import os
import numpy as np
import queue
import cv2
import mysql.connector


try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QLabel, QPushButton, QLineEdit, QListWidget,
        QVBoxLayout, QHBoxLayout, QSizePolicy, QTabWidget,
        QGroupBox, QMessageBox, QFileDialog, QSlider, QCheckBox, QFormLayout, QFrame,
        QComboBox, QTextEdit, QSpinBox
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
CONFIG_FILENAME = 'config.json'

DB_NAME = "EYEO"
DB_CONFIG = {
    "user": "root",
    "password": "SSAautom@369741",
    "host": "127.0.0.1",
    "port": 3306
}

# Default config used for validation / initial values
DEFAULT_CONFIG = {
    "scale_percent": 25,
    "width": 1920,
    "height": 1080,
    "modbus_ip": "127.0.0.1",
    "modbus_port": 502,
    "host": "127.0.0.1",
    "port": 65432,
    "roi": [[189,485],[1855,13],[1813,653],[210,1014]]
}

class VideoClient(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Eye/O Viewer")
        self.dark_theme = True
        self.resize(1280, 720)

        self.client_socket = None
        self.running = False
        self.unidades = []
        self.timestamps = []
        self.total_produtos = 0
        self.last_update_time = 0
        self.last_produtos = 0

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_video)
        # queue used by background IP scanner thread to push discovered IPs
        self.ip_queue = queue.Queue()

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

        # IP inputs (3 parts) and label
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

        # Porta
        porta_layout = QHBoxLayout()
        porta_label = QLabel("Porta:")
        self.port_input = QLineEdit(str(DEFAULT_CONFIG['port']))
        self.port_input.setFixedWidth(80)
        porta_layout.addWidget(porta_label)
        porta_layout.addWidget(self.port_input)
        config_box.addLayout(porta_layout)

        self.buscar_btn = QPushButton("BUSCAR IP")
        self.buscar_btn.clicked.connect(self.buscar_dispositivos)
        config_box.addWidget(self.buscar_btn)

        self.device_list = QListWidget()
        config_box.addWidget(self.device_list)

        # History list for discovered IPs (removable via context menu)
        self.history_list = QListWidget()
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._history_context_menu)
        config_box.addWidget(QLabel("Histórico de IPs:"))
        config_box.addWidget(self.history_list)

        # start a timer to poll the ip_queue and add found IPs to lists
        self.ip_poll_timer = QTimer()
        self.ip_poll_timer.timeout.connect(self._poll_ip_queue)
        self.ip_poll_timer.start(200)

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

        # --- Aba Ferramentas (config JSON) ---
        self.ferramentas_tab = QWidget()
        ferramentas_layout = QHBoxLayout(self.ferramentas_tab)

        # left: config fields
        cfg_group = QGroupBox("Configurações (config.json)")
        cfg_form = QFormLayout()

        # scale_percent
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(1, 100)
        self.scale_spin.setValue(DEFAULT_CONFIG['scale_percent'])
        cfg_form.addRow("scale_percent", self.scale_spin)

        # resolution dropdown -> sets width/height
        self.res_combo = QComboBox()
        # resolutions from 8K to 480p
        RESOLUTIONS = [
            ("8K (7680x4320)", 7680, 4320),
            ("5K (5120x2880)", 5120, 2880),
            ("4K (3840x2160)", 3840, 2160),
            ("1440p (2560x1440)", 2560, 1440),
            ("1080p (1920x1080)", 1920, 1080),
            ("720p (1280x720)", 1280, 720),
            ("480p (854x480)", 854, 480),
            ("240p (480X240)",480, 240)
        ]
        for name, w, h in RESOLUTIONS:
            self.res_combo.addItem(name, (w, h))
        # default select based on DEFAULT_CONFIG
        for i in range(self.res_combo.count()):
            w,h = self.res_combo.itemData(i)
            if w == DEFAULT_CONFIG['width'] and h == DEFAULT_CONFIG['height']:
                self.res_combo.setCurrentIndex(i)
                break
        cfg_form.addRow("Resolução", self.res_combo)

        # width / height display (read-only)
        self.width_label = QLabel(str(DEFAULT_CONFIG['width']))
        self.height_label = QLabel(str(DEFAULT_CONFIG['height']))
        cfg_form.addRow("Width", self.width_label)
        cfg_form.addRow("Height", self.height_label)

        # modbus ip (4 fields) and port (default 502)
        modbus_ip_layout = QHBoxLayout()
        self.modbus_ip_inputs = []
        for _ in range(4):
            e = QLineEdit()
            e.setMaxLength(3)
            e.setFixedWidth(45)
            self.modbus_ip_inputs.append(e)
            modbus_ip_layout.addWidget(e)
        self.modbus_port_input = QLineEdit(str(DEFAULT_CONFIG['modbus_port']))
        self.modbus_port_input.setFixedWidth(80)
        cfg_form.addRow("Modbus IP", modbus_ip_layout)
        cfg_form.addRow("Modbus Port", self.modbus_port_input)

        # host ip (4 fields) and port (default 65432)
        host_ip_layout = QHBoxLayout()
        self.host_ip_inputs = []
        for _ in range(4):
            e = QLineEdit()
            e.setMaxLength(3)
            e.setFixedWidth(45)
            self.host_ip_inputs.append(e)
            host_ip_layout.addWidget(e)
        self.host_port_input = QLineEdit(str(DEFAULT_CONFIG['port']))
        self.host_port_input.setFixedWidth(80)
        cfg_form.addRow("Host IP", host_ip_layout)
        cfg_form.addRow("Host Port", self.host_port_input)

        # ROI (text area with JSON)
        # ROI replaced by interactive selector (only active quando conectado)
        self.roi = DEFAULT_CONFIG['roi']
        self.roi_label = QLabel(str(self.roi))
        self.definir_roi_btn = QPushButton("Definir ROI (área de interesse)")
        self.definir_roi_btn.setEnabled(False)
        self.definir_roi_btn.clicked.connect(self.start_roi_selector)
        cfg_form.addRow("ROI", self.roi_label)
        cfg_form.addRow(self.definir_roi_btn)

        cfg_group.setLayout(cfg_form)

        # right: actions
        actions_group = QGroupBox("Ações")
        actions_form = QFormLayout()

        self.send_cfg_btn = QPushButton("Enviar Config (socket)")
        self.send_cfg_btn.clicked.connect(self.send_config_via_socket)
        actions_form.addRow(self.send_cfg_btn)

        self.save_local_btn = QPushButton("Salvar local (arquivo)")
        self.save_local_btn.clicked.connect(self.save_config_local)
        actions_form.addRow(self.save_local_btn)

        self.load_local_btn = QPushButton("Carregar último save")
        self.load_local_btn.clicked.connect(self.load_config_local)
        actions_form.addRow(self.load_local_btn)

        self.start_listener_btn = QPushButton("Iniciar Listener (recebe e atualiza json)")
        self.start_listener_btn.clicked.connect(self.start_listener_thread)
        actions_form.addRow(self.start_listener_btn)

        # contador listener (recebe updates do contador para atualizar total/graph)
        self.start_counter_btn = QPushButton("Iniciar Listener de Contador")
        self.start_counter_btn.clicked.connect(self.start_counter_listener_thread)
        actions_form.addRow(self.start_counter_btn)

        actions_group.setLayout(actions_form)

        ferramentas_layout.addWidget(cfg_group, stretch=2)
        ferramentas_layout.addWidget(actions_group, stretch=1)
        self.tabs.addTab(self.ferramentas_tab, "Ferramentas")

        # --- Nova Aba Aparencia (mover controles de tema e fonte para cá) ---
        self.aparencia_tab = QWidget()
        aparencia_layout = QVBoxLayout(self.aparencia_tab)
        aparencia_group = QGroupBox("Aparência")
        aparencia_form = QFormLayout()

        # slider e switch movidos para Aparência
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(8, 32)
        self.font_slider.setValue(12)
        self.font_slider.valueChanged.connect(self.ajustar_fonte)
        aparencia_form.addRow("Tamanho da Fonte", self.font_slider)

        self.theme_switch = QCheckBox("Tema Claro/Escuro")
        self.theme_switch.stateChanged.connect(self.trocar_tema)
        aparencia_form.addRow(self.theme_switch)

        # Comentários: aqui é possível adicionar seletor de cores (QColorDialog),
        # preview de tema, ou presets de aparência. (opções deixadas como sugestão)

        aparencia_group.setLayout(aparencia_form)
        aparencia_layout.addWidget(aparencia_group)
        self.tabs.addTab(self.aparencia_tab, "Aparência")

        # wire resolution change
        self.res_combo.currentIndexChanged.connect(self.on_resolution_changed)
        # prefill host/modbus from defaults
        self._prefill_ip_fields()

    def _prefill_ip_fields(self):
        # fill default host and modbus ip
        def fill_ip_fields(ip_str, inputs):
            parts = ip_str.split('.')
            for i in range(4):
                if i < len(parts):
                    inputs[i].setText(parts[i])
                else:
                    inputs[i].setText('0')
        fill_ip_fields(DEFAULT_CONFIG['host'], self.host_ip_inputs)
        fill_ip_fields(DEFAULT_CONFIG['modbus_ip'], self.modbus_ip_inputs)

    def on_resolution_changed(self, idx):
        w,h = self.res_combo.itemData(idx)
        self.width_label.setText(str(w))
        self.height_label.setText(str(h))

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
            # enable ROI definition when connected to a camera
            try:
                self.definir_roi_btn.setEnabled(True)
            except AttributeError:
                pass
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

            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor()
                cursor.execute(f"USE {DB_NAME}")
                cursor.execute("SELECT quant FROM chiken_count_current WHERE id=1")
                response = cursor.fetchone()
            except:
                pass
            self.total_produtos = response[0]
            self.total_value.setText(str(self.total_produtos))

            now = time.time()
            elapsed = now - self.last_update_time
            if elapsed > 10:
                
                media_hora = ((self.total_produtos - self.last_produtos) / elapsed) * 3600
                self.media_value.setText(f"{media_hora:.2f}")
                self.last_update_time = now
                self.last_produtos = self.total_produtos

                self.unidades.append(media_hora)
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
        """Start threaded IP scan and stream results into the UI via a queue.
        This avoids blocking the GUI while scanning 1..254 addresses.
        """
        try:
            ip_parts = [int(box.text()) for box in self.ip_inputs]
            if any(p < 0 or p > 255 for p in ip_parts):
                raise ValueError
        except Exception:
            QMessageBox.critical(self, "Erro", "Digite um IP válido (0-255 em cada campo)")
            return

        try:
            porta = int(self.port_input.text())
        except:
            porta = DEFAULT_CONFIG['port']

        # clear current lists
        self.device_list.clear()
        # start background thread to scan
        t = threading.Thread(target=self._ip_scanner_thread, args=(ip_parts, porta), daemon=True)
        t.start()

    def _ip_scanner_thread(self, ip_parts, porta):
        base = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}."
        for i in range(1, 255):
            ip = f"{base}{i}"
            try:
                s = socket.create_connection((ip, porta), timeout=0.08)
                s.close()
                # push to queue for main thread to add
                self.ip_queue.put(ip)
            except:
                pass

    def _poll_ip_queue(self):
        while not self.ip_queue.empty():
            ip = self.ip_queue.get()
            # add to device list and history
            self.device_list.addItem(ip)
            self.history_list.addItem(ip)

    def _history_context_menu(self, pos):
        item = self.history_list.itemAt(pos)
        if item is None:
            return
        menu = QMessageBox(self)
        # simple confirmation dialog to remove
        reply = QMessageBox.question(self, 'Remover IP', f"Remover {item.text()} do histórico?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            row = self.history_list.row(item)
            self.history_list.takeItem(row)


    def load_config_local(self):
        # loads last saved config.json and populate UI fields
        if not os.path.exists(CONFIG_FILENAME):
            QMessageBox.warning(self, 'Aviso', 'Arquivo config.json não encontrado')
            return
        try:
            with open(CONFIG_FILENAME, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Falha ao ler arquivo: {e}')
            return
        # populate fields
        try:
            self.scale_spin.setValue(int(cfg.get('scale_percent', DEFAULT_CONFIG['scale_percent'])))
            w = int(cfg.get('width', DEFAULT_CONFIG['width']))
            h = int(cfg.get('height', DEFAULT_CONFIG['height']))
            # select resolution matching width/height if available
            for i in range(self.res_combo.count()):
                ww, hh = self.res_combo.itemData(i)
                if ww == w and hh == h:
                    self.res_combo.setCurrentIndex(i)
                    break
            # modbus
            parts = cfg.get('modbus_ip', DEFAULT_CONFIG['modbus_ip']).split('.')
            for i, box in enumerate(self.modbus_ip_inputs):
                box.setText(parts[i] if i < len(parts) else '0')
            self.modbus_port_input.setText(str(cfg.get('modbus_port', DEFAULT_CONFIG['modbus_port'])))
            # host
            parts = cfg.get('host', DEFAULT_CONFIG['host']).split('.')
            for i, box in enumerate(self.host_ip_inputs):
                box.setText(parts[i] if i < len(parts) else '0')
            self.host_port_input.setText(str(cfg.get('port', DEFAULT_CONFIG['port'])))
            # roi
            self.roi = cfg.get('roi', DEFAULT_CONFIG['roi'])
            try:
                self.roi_label.setText(str(self.roi))
            except:
                pass
            QMessageBox.information(self, 'Carregado', 'Configuração carregada do arquivo')
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Falha ao popular UI: {e}')

    def start_roi_selector(self):
        # opens an OpenCV window that shows frames and lets user click 4 points
        if self.client_socket is None and not hasattr(self, 'latest_frame'):
            QMessageBox.warning(self, 'ROI', 'Conecte-se a uma câmera primeiro')
            return
        t = threading.Thread(target=self._roi_selector_thread, daemon=True)
        t.start()

    def _roi_selector_thread(self):
        pts = []
        win_name = 'Definir ROI - clique 4 pontos (r=redefinir, c=confirmar)'
        cv2.namedWindow(win_name)

        def on_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                if len(pts) < 4:
                    pts.append((x, y))

        cv2.setMouseCallback(win_name, on_mouse)

        while True:
            if hasattr(self, 'latest_frame'):
                frame = self.latest_frame.copy()
                h,w = frame.shape[0],frame.shape[1]
                frame = cv2.resize(frame, (int(w/2), int(h/2)))

            else:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, 'SEM VIDEO', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

            # draw points and polygon edges
            for p in pts:
                cv2.circle(frame, p, 5, (0,255,0), -1)
            if len(pts) == 4:
                cv2.polylines(frame, [np.array(pts)], isClosed=True, color=(0,255,0), thickness=2)

            cv2.imshow(win_name, frame)
            key = cv2.waitKey(30) & 0xFF
            if key == ord('r'):
                pts = []
            if key == ord('c') and len(pts) == 4:
                # confirm
                pts = [(p[0]*2, p[1]*2) for p in pts]
                self.roi = pts.copy()
                try:
                    # update label in main thread via Qt
                    self.roi_label.setText(str(self.roi))
                except:
                    pass
                break
            # allow window close via Esc
            if key == 27:
                break
        cv2.destroyWindow(win_name)

    def start_counter_listener_thread(self):
        # listens for counter JSON messages to update total, media and graph
        try:
            listen_port = int(self.host_port_input.text()) + 1
        except:
            listen_port = DEFAULT_CONFIG['port'] + 1
        t = threading.Thread(target=self._counter_listener, args=(listen_port,), daemon=True)
        t.start()
        QMessageBox.information(self, 'Listener', f'Listener do contador iniciado em {listen_port}')

    def _counter_listener(self, listen_port):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('0.0.0.0', listen_port))
        srv.listen(1)
        while True:
            conn, addr = srv.accept()
            try:
                size_data = conn.recv(4)
                if len(size_data) < 4:
                    conn.close(); continue
                payload_len = struct.unpack('>I', size_data)[0]
                data = b''
                while len(data) < payload_len:
                    more = conn.recv(payload_len - len(data))
                    if not more:
                        break
                    data += more
                try:
                    msg = json.loads(data.decode('utf-8'))
                    # expected format: {"type":"counter","total":123}
                    if msg.get('type') == 'counter' and 'total' in msg:
                        total = int(msg['total'])
                        # update UI in main thread via queued call
                        self.total_produtos = total
                        # update graph arrays
                        self.unidades.append(self.total_produtos)
                        self.timestamps.append(time.strftime("%H:%M:%S"))
                        # cap lists
                        self.unidades = self.unidades[-30:]
                        self.timestamps = self.timestamps[-30:]
                        # update labels using Qt via QTimer singleShot
                        QTimer.singleShot(0, lambda: self.total_value.setText(str(self.total_produtos)))
                        QTimer.singleShot(0, lambda: self.update_graph())
                except Exception as e:
                    print('Erro ao processar contador payload:', e)
            finally:
                conn.close()

    def validar_ip_fields(self, inputs):
        parts = []
        try:
            for box in inputs:
                v = int(box.text())
                if v < 0 or v > 255:
                    return None
                parts.append(str(v))
        except:
            return None
        return '.'.join(parts)

    def coletar_config_from_ui(self):
        # assemble dict from UI, validate types
        config = {}
        config['scale_percent'] = int(self.scale_spin.value())
        w = int(self.width_label.text())
        h = int(self.height_label.text())
        config['width'] = w
        config['height'] = h

        modbus_ip = self.validar_ip_fields(self.modbus_ip_inputs)
        if not modbus_ip:
            raise ValueError('Modbus IP inválido')
        config['modbus_ip'] = modbus_ip
        try:
            config['modbus_port'] = int(self.modbus_port_input.text())
        except:
            raise ValueError('Modbus port inválida')

        host_ip = self.validar_ip_fields(self.host_ip_inputs)
        if not host_ip:
            raise ValueError('Host IP inválido')
        config['host'] = host_ip
        try:
            config['port'] = int(self.host_port_input.text())
        except:
            raise ValueError('Host port inválida')

        # roi parse
        try:
            roi = json.loads(self.roi_edit.toPlainText())
            if not (isinstance(roi, list) and all(isinstance(p, list) and len(p) == 2 for p in roi)):
                raise ValueError
            config['roi'] = roi
        except Exception:
            raise ValueError('ROI inválido - deve ser lista de pares [[x,y],...]')

        return config

    def send_config_via_socket(self):
        try:
            cfg = self.coletar_config_from_ui()
        except ValueError as e:
            QMessageBox.critical(self, 'Erro', str(e))
            return

        # send to host:port via TCP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((cfg['host'], cfg['port']))
            payload = json.dumps({'cmd': 'update_config', 'config': cfg}).encode('utf-8')
            # prefix length
            s.sendall(struct.pack('>I', len(payload)) + payload)
            s.close()
            QMessageBox.information(self, 'Enviado', f"Config enviada a {cfg['host']}:{cfg['port']}")
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f"Falha ao enviar config: {e}")

    def save_config_local(self):
        try:
            cfg = self.coletar_config_from_ui()
        except ValueError as e:
            QMessageBox.critical(self, 'Erro', str(e))
            return
        try:
            with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=4)
            QMessageBox.information(self, 'Salvo', f"Config salva em {os.path.abspath(CONFIG_FILENAME)}")
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f"Falha ao salvar arquivo: {e}")

    # listener that receives a JSON payload via socket and updates local config file
    def start_listener_thread(self):
        t = threading.Thread(target=self._listener_server, daemon=True)
        t.start()
        QMessageBox.information(self, 'Listener', 'Listener iniciado em background (porta 65432)')

    def _listener_server(self, listen_port=DEFAULT_CONFIG['port']):
        # listens for incoming config update messages and writes config.json
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('0.0.0.0', listen_port))
        srv.listen(1)
        while True:
            conn, addr = srv.accept()
            try:
                size_data = conn.recv(4)
                if len(size_data) < 4:
                    conn.close(); continue
                payload_len = struct.unpack('>I', size_data)[0]
                data = b''
                while len(data) < payload_len:
                    more = conn.recv(payload_len - len(data))
                    if not more:
                        break
                    data += more
                try:
                    msg = json.loads(data.decode('utf-8'))
                    if msg.get('cmd') == 'update_config' and 'config' in msg:
                        cfg = msg['config']
                        # basic validation
                        if 'host' in cfg and 'port' in cfg:
                            with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
                                json.dump(cfg, f, indent=4)
                except Exception as e:
                    print('Erro ao processar payload:', e)
            finally:
                conn.close()

    def validar_ip_fields(self, inputs):
        parts = []
        try:
            for box in inputs:
                v = int(box.text())
                if v < 0 or v > 255:
                    return None
                parts.append(str(v))
        except:
            return None
        return '.'.join(parts)

    def coletar_config_from_ui(self):
        # assemble dict from UI, validate types
        config = {}
        config['scale_percent'] = int(self.scale_spin.value())
        w = int(self.width_label.text())
        h = int(self.height_label.text())
        config['width'] = w
        config['height'] = h

        modbus_ip = self.validar_ip_fields(self.modbus_ip_inputs)
        if not modbus_ip:
            raise ValueError('Modbus IP inválido')
        config['modbus_ip'] = modbus_ip
        try:
            config['modbus_port'] = int(self.modbus_port_input.text())
        except:
            raise ValueError('Modbus port inválida')

        host_ip = self.validar_ip_fields(self.host_ip_inputs)
        if not host_ip:
            raise ValueError('Host IP inválido')
        config['host'] = host_ip
        try:
            config['port'] = int(self.host_port_input.text())
        except:
            raise ValueError('Host port inválida')

        # roi parse
        try:
            roi = json.loads(self.roi_edit.toPlainText())
            if not (isinstance(roi, list) and all(isinstance(p, list) and len(p) == 2 for p in roi)):
                raise ValueError
            config['roi'] = roi
        except Exception:
            raise ValueError('ROI inválido - deve ser lista de pares [[x,y],...]')

        return config

    def send_config_via_socket(self):
        try:
            cfg = self.coletar_config_from_ui()
        except ValueError as e:
            QMessageBox.critical(self, 'Erro', str(e))
            return

        # send to host:port via TCP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((cfg['host'], cfg['port']))
            payload = json.dumps({'cmd': 'update_config', 'config': cfg}).encode('utf-8')
            # prefix length
            s.sendall(struct.pack('>I', len(payload)) + payload)
            s.close()
            QMessageBox.information(self, 'Enviado', f"Config enviada a {cfg['host']}:{cfg['port']}")
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f"Falha ao enviar config: {e}")

    def save_config_local(self):
        try:
            cfg = self.coletar_config_from_ui()
        except ValueError as e:
            QMessageBox.critical(self, 'Erro', str(e))
            return
        try:
            with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=4)
            QMessageBox.information(self, 'Salvo', f"Config salva em {os.path.abspath(CONFIG_FILENAME)}")
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f"Falha ao salvar arquivo: {e}")

    # remaining methods (receiving frames, UI helpers, etc.) remain as before

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
