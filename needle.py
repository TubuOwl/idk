# python 3.11.4

import websocket
import time
import re
import html
import threading
import requests
import random
import traceback


def getServer(group):
    special = {"nico-nico": 29}.get(group)
    if special is not None:
        return special

    weights = [
        (str(x), w)
        for g, w in [([5, 6, 7, 8, 16, 17, 18],
                      75), ([9, 11, 12, 13, 14, 15],
                            95), ([19, 23, 24, 25, 26],
                                  110), (range(28, 34),
                                         104), (range(35, 51), 101),
                     ([52, 53, 55, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66],
                      110), ([68], 95), (range(71, 85), 116)] for x in g
    ]
    g = group.replace('-', 'q').replace('_', 'q')
    base = int(g[6:9], 36) if len(g) > 6 else 1000
    pos = (int(g[:5], 36) % base) / base

    total = sum(w for _, w in weights)
    cum = 0
    for server, w in weights:
        cum += w / total
        if pos <= cum:
            return server
    return weights[-1][0]


def get_auth(user, password):
    r = requests.get(
        f"https://st.chatango.com/script/setcookies?pwd={password}&sid={user}",
        headers={
            "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        })
    return r.headers.get("Set-Cookie",
                         "").split("auth.chatango.com=")[1].split(";")[0]


class ChatangoGroup:

    def __init__(self, group_name, username, password, uid):
        self.group_name = group_name
        self.username = username.lower()
        self.password = password
        self.uid = uid # ?
        self.server_num = getServer(group_name)
        self.ws = None
        self.running = False
        self.cmdPrefix = "!"
        self.fSize, self.fFace, self.fColor, self.nColor = "11", "0", "000", "000"

    def connect(self):
        try:
            self.ws = websocket.WebSocket()
            self.ws.connect(
                f'wss://s{self.server_num}.chatango.com:8081/websocket',
                origin='https://st.chatango.com')
            self.ws.send(
                bytes(
                    f"bauth:{self.group_name}::{self.username}:{self.password}\x00",
                    "utf-8"))
            self.running = True
            print(f"[{self.group_name}] Connected (Group)")
        except Exception as e:
            print(f"[{self.group_name}] Connection error:", e)

    def sendPost(self, text, html_enabled=True):
        if not html_enabled:
            text = text.replace("<", "&lt;").replace(">", "&gt;")
        if len(text) < 2700:
            payload = f"bmsg:t12r:<n{self.nColor}/><f x{self.fSize}{self.fColor}=\"{self.fFace}\">{text}\r\n\x00"
            if self.ws:
                self.ws.send(payload)

    def close(self):
        self.running = False
        if self.ws:
            self.ws.close()


class ChatangoPrivate:

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.token = get_auth(username, password)
        self.ws = None
        self.running = False
        self.fSize, self.fFace, self.fColor, self.nColor = "11", "0", "000", "000"

    def connect(self):
        try:
            self.ws = websocket.WebSocket()
            self.ws.connect("ws://c1.chatango.com:8080",
                            origin='https://st.chatango.com')
            self.ws.send(f"tlogin:{self.token}:2:\x00".encode())
            self.running = True
            print("[PM] Connected (Private Message)")
        except Exception as e:
            print("[PM] Connection error:", e)

    def sendPM(self, user, message): # thamks chemsee & agung
        if self.running and self.ws is not None:
            self.ws.send(f'wladd:{user}\r\n\x00'.encode())
            time.sleep(1)
            self.ws.send(f'connect:{user}\r\n\x00'.encode())
            time.sleep(1)
            self.ws.send(
                f'msg:{user}:<n{self.nColor}/><m v=\"1\"><g x{self.fSize}s{self.fColor}=\"{self.fFace}\">{message}</g>'
                .encode())

    def closePM(self):
        self.running = False
        if self.ws:
            self.ws.close()
            print("[PM] Disconnected")


class ChatManager:

    def __init__(self, user, password):
        self.user = user
        self.password = password
        self.uid = str(random.randrange(10**15, 10**16))
        self.groups = {}
        self.pm = None
        self.running = False
        self.heartbeat_interval = 50
        self.heartbeat_thread = None
        self.receive_thread = None

    def add_group(self, name):
        if name not in self.groups:
            group = ChatangoGroup(name, self.user, self.password, self.uid)
            self.groups[name] = group
            group.connect()
            self.start_unified_threads()

    def connect_pm(self):
        if not self.pm:
            self.pm = ChatangoPrivate(self.user, self.password)
            self.pm.connect()
            self.start_unified_threads()

    def close_all(self):
        self.running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join()
        if self.receive_thread:
            self.receive_thread.join()
        for grp in self.groups.values():
            grp.close()
        if self.pm:
            self.pm.closePM()

    def start_unified_threads(self):
        if not self.running:
            self.running = True
            self.heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True)
            self.heartbeat_thread.start()
            self.receive_thread = threading.Thread(target=self._unified_receive_loop, daemon=True)
            self.receive_thread.start()

    def _unified_receive_loop(self):
        while self.running:
            try:
                for group in list(self.groups.values()):
                    if group.ws and group.running:
                        try:
                            group.ws.settimeout(0.1)
                            raw = group.ws.recv()
                            if raw:
                                self._unified_on_message(raw, source_type="group", source=group)
                        except websocket.WebSocketTimeoutException:
                            continue
                        except websocket.WebSocketConnectionClosedException:
                            print(f"[{group.group_name}] Connection closed")
                            group.running = False
                        except Exception as e:
                            if "timed out" not in str(e).lower():
                                print(f"[{group.group_name}] Receive error:", e)


                if self.pm and self.pm.ws and self.pm.running:
                    try:
                        self.pm.ws.settimeout(0.1)
                        raw = self.pm.ws.recv()
                        if raw:
                            self._unified_on_message(raw, source_type="pm", source=self.pm)
                    except websocket.WebSocketTimeoutException:
                        continue
                    except websocket.WebSocketConnectionClosedException:
                        print("[PM] Connection closed")
                        self.pm.running = False
                    except Exception as e:
                        if "timed out" not in str(e).lower():
                            print("[PM] Receive error:", e)

                time.sleep(0.01)  # overHIT cpu
            except Exception as e:
                print("Unified receive loop error:", e)

    def _unified_on_message(self, raw, source_type, source):
        try:
            if source_type == "group":
                bites = raw.rstrip("\x00").split(":")
                cmd = bites[0]
                if cmd == "b" and len(bites) > 10:
                    user = bites[2].lower()
                    msg_raw = bites[10]
                    cleaned = re.sub(r"<n(.*?)><f x(.*?)=\"(.*?)\">|</f>|</n>", "", msg_raw)
                    cleaned = html.unescape(cleaned).replace("<b>", "").replace("</b>", "")
                    msg = cleaned.lower()
                    
                    if user == source.username:
                        return

                    if msg.startswith(source.cmdPrefix + "eval "):
                        try:
                            result = str(eval(cleaned.split(" ", 1)[1]))
                        except Exception as e:
                            result = f"Error: {e}"
                        source.sendPost(result, html_enabled=False)
                        
            elif source_type == "pm":
                msg = raw.strip("\x00")
                print("[PM] Received:", msg)
                
        except Exception as e:
            print(f"Unified message handler error ({source_type}):", e)

    def _heartbeat(self # inspired by kon
        while self.running:
            try:
                for group in self.groups.values():
                    if group.ws:
                        try:
                            group.ws.send(b'\r\n\x00')
                        except Exception as e:
                            print(f"[{group.group_name}] Heartbeat error:", e)
                            group.running = False

                if self.pm and self.pm.ws:
                    try:
                        self.pm.ws.send(b'\r\n\x00')
                    except Exception as e:
                        print("[PM] Heartbeat error:", e)
                        self.pm.running = False
            except Exception as e:
                print("Heartbeat error:", e)

            time.sleep(self.heartbeat_interval)


if __name__ == "__main__":
    mgr = ChatManager("Amio", "Amio")
    mgr.add_group("nico-nico")
    mgr.connect_pm()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting…")
        mgr.close_all()


# Bajigur - disco
