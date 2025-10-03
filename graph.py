import os
import graphviz

# Força o caminho do Graphviz no Windows (ajuste se instalou em outro lugar)
graphviz_path = r"C:\Program Files\Graphviz\bin"
if graphviz_path not in os.environ["PATH"]:
    os.environ["PATH"] += os.pathsep + graphviz_path

graphviz.set_default_engine("dot")
graphviz.set_default_format("png")

from graphviz import Digraph
dot = graphviz.Digraph()
# dot.node("A", "Node A")
# dot.render("output", view=True) # Raises ExecutableNotFound error

dot = graphviz.Digraph(comment="Fluxograma de chamadas do código")

# UI events
dot.node("UI", "Interface PyQt5", shape="box", style="filled", color="lightblue")
dot.node("BTN_CONN", "Botão Conectar", shape="box")
dot.node("BTN_SCAN", "Botão Buscar IPs", shape="box")
dot.node("BTN_RESET", "Botão Reset Fábrica", shape="box")
dot.node("BTN_ROI", "Botão Definir ROI", shape="box")
dot.node("SLIDER_FONT", "Slider Fonte", shape="box")
dot.node("SWITCH_THEME", "Switch Tema", shape="box")

# Core functions
dot.node("CONNECT", "conectar_socket()", shape="ellipse")
dot.node("SCAN", "buscar_dispositivos()", shape="ellipse")
dot.node("RESET", "reset_fabrica()", shape="ellipse")
dot.node("ROI", "definir_roi()", shape="ellipse")
dot.node("FONT", "ajustar_fonte()", shape="ellipse")
dot.node("THEME", "trocar_tema()", shape="ellipse")

# Threads
dot.node("THREAD_RECV", "Thread: connect_and_receive", shape="parallelogram", color="orange")
dot.node("THREAD_SCAN", "Thread: scan_network", shape="parallelogram", color="orange")
dot.node("THREAD_CONF", "Thread: config_listener", shape="parallelogram", color="orange")
dot.node("THREAD_CNT", "Thread: counter_listener", shape="parallelogram", color="orange")

# Video update
dot.node("UPDATE_VIDEO", "update_video()", shape="ellipse", color="green")
dot.node("UPDATE_GRAPH", "update_graph()", shape="ellipse", color="green")

# Connections UI -> functions
dot.edges([("BTN_CONN", "CONNECT"),
           ("BTN_SCAN", "SCAN"),
           ("BTN_RESET", "RESET"),
           ("BTN_ROI", "ROI"),
           ("SLIDER_FONT", "FONT"),
           ("SWITCH_THEME", "THEME")])

# Main UI
dot.edge("UI", "BTN_CONN")
dot.edge("UI", "BTN_SCAN")
dot.edge("UI", "BTN_RESET")
dot.edge("UI", "BTN_ROI")
dot.edge("UI", "SLIDER_FONT")
dot.edge("UI", "SWITCH_THEME")

# Threads start
dot.edge("CONNECT", "THREAD_RECV")
dot.edge("SCAN", "THREAD_SCAN")
dot.edge("UI", "THREAD_CONF")
dot.edge("UI", "THREAD_CNT")

# Thread outputs
dot.edge("THREAD_RECV", "UPDATE_VIDEO")
dot.edge("UPDATE_VIDEO", "UPDATE_GRAPH")

# IP scan results feed back to UI
dot.edge("THREAD_SCAN", "SCAN")

fluxograma_path = "fluxograma_codigo"
dot.render(fluxograma_path, format="pdf", cleanup=True)

fluxograma_path + ".pdf"
