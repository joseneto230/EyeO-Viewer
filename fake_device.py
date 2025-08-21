import socket
import threading

def handle_client(conn, addr):
    print(f"📡 Conexão recebida de {addr}")
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            print(f"➡️ Recebido: {data.decode('utf-8', errors='ignore')}")
            # responde como se fosse o dispositivo
            conn.sendall(b"ACK - dispositivo fake")
    except:
        pass
    finally:
        conn.close()
        print(f"❌ Conexão encerrada com {addr}")

def start_fake_device(ip="0.0.0.0", port=65432):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((ip, port))
    server.listen(5)
    print(f"✅ Dispositivo fake rodando em {ip}:{port}")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    start_fake_device()