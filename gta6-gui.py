# -*- coding: utf-8 -*-
"""
GTA6 Controller — Interface Gráfica Profissional
Mouse: leitura via pynput + ClipCursor para confinar o cursor fisicamente.
LWin: liga/desliga emulação (e confinamento).
F12: alterna modo a pé / no carro.
"""

import time
import threading
import tkinter as tk
import ctypes
import ctypes.wintypes

# ------------------------------------------------------------------ Win32
_user32  = ctypes.windll.user32

class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

def _clip_to_foreground():
    """Confina o cursor à janela em foco (ou à tela inteira como fallback)."""
    hwnd = _user32.GetForegroundWindow()
    r = _RECT()
    if hwnd:
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        # sanity: janela muito pequena → usa tela inteira
        if (r.right - r.left) < 100 or (r.bottom - r.top) < 100:
            hwnd = 0
    if not hwnd:
        r.left = 0; r.top = 0
        r.right  = _user32.GetSystemMetrics(0)
        r.bottom = _user32.GetSystemMetrics(1)
    _user32.ClipCursor(ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def _unclip():
    _user32.ClipCursor(None)

def start_capture():
    rect = _clip_to_foreground()
    state["mouse_captured"] = True
    state["capture_rect"]   = rect
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    log(f"[mouse] capturado  {w}x{h}  — cursor confinado")

def stop_capture():
    _unclip()
    state["mouse_captured"] = False
    state["capture_rect"]   = None
    log("[mouse] liberado")


# ------------------------------------------------------------------ config
DEADZONE_RS    = 0.08   # deadzone radial do right stick (0–1)
ANTI_DZ        = 0.08   # anti-deadzone: empurra saída além da DZ do jogo (0–0.3)
SENS_X         = 0.20   # sensibilidade horizontal (aumentado p/ rotação 360°)
SENS_Y         = 0.18   # sensibilidade vertical
FRICTION       = 0.80   # momentum entre frames (menor = para mais rápido)
SMOOTHING      = 0.20   # EMA: menor = câmera mais responsiva / 360° mais rápida
RESPONSE       = "progressive"  # "linear" ou "progressive"
AIM_RESPONSE   = "aim"          # curva mais precisa quando RMB pressionado
MAX_VEL        = 1.0
PRECISION_MULT = 0.35   # multiplicador ao segurar LCtrl
AIM_MULT       = 0.45   # multiplicador ao segurar RMB (mirar)
WHEEL_MULT      = 0.12   # multiplicador com roda de armas aberta (movimento lento p/ selecionar)
HALF_THROTTLE  = 0.25
TOGGLE_KEY     = "f12"

# ------------------------------------------------------------------ imports
try:
    import vgamepad as vg
except ImportError:
    import tkinter.messagebox as mb
    mb.showerror("Erro", "vgamepad não instalado. Rode: pip install vgamepad")
    raise

try:
    from pynput import keyboard, mouse
except ImportError:
    import tkinter.messagebox as mb
    mb.showerror("Erro", "pynput não instalado. Rode: pip install pynput")
    raise

# ------------------------------------------------------------------ estado
state = {
    "emulation":      True,
    "mode":           "on_foot",   # "on_foot" | "driving" | "inventory"
    "precision":      False,
    "aim":            False,
    "mouse_captured": False,
    "capture_rect":   None,        # (l, t, r, b) atual
}

buttons     = {}
pressed     = set()
mouse_vel    = {"x": 0.0, "y": 0.0}    # deltas brutos acumulados
mouse_smooth = {"x": 0.0, "y": 0.0}   # saída EMA suavizada
_mouse_idle  = 0                       # frames consecutivos sem movimento
mouse_lock   = threading.Lock()
rs_value     = {"x": 0.0, "y": 0.0}
_last_mouse  = {"x": None, "y": None}
gamepad      = None
log_lines    = []
log_lock     = threading.Lock()

KEY_MAP = {
    # --- face buttons (GTA VI default) ---
    "space": "A",          # Pular / Subir / Handbrake
    "z": "B",              # Agachar (B no GTA VI; antes era R3 — CORRIGIDO)
    "b": "X",              # Soco / Melee (X no GTA VI; antes era B — CORRIGIDO)
    "r": "X",              # Recarregar (também X)
    "x": "X",              # Shove / Clear Trunk (X hold no jogo)
    "f": "Y",              # Interagir / Entrar-sair veículo
    "g": "Y",              # Arrombar (também Y)
    # --- bumpers / triggers ---
    "q": "RB",             # Cobertura
    "c": "LB",             # LB — weapon wheel / quick holster (hold no jogo)
    # --- sticks ---
    "h": "R3",             # Olhar atrás (R3 hold) — tecla nova
    # --- menu ---
    "esc": "START", "o": "START",
    "p": "BACK", "i": "BACK",
    "enter": "A", "backspace": "B",
    "f1": "GUIDE", "f2": "BACK", "home": "GUIDE", "insert": "BACK",
    # --- D-Pad ---
    "1": "DPAD_UP", "2": "DPAD_DOWN", "3": "DPAD_LEFT", "4": "DPAD_RIGHT",
    "e": "DPAD_RIGHT", "t": "DPAD_RIGHT",
    # --- sprint ---
    "rshift": "L3", "shift": "L3", "shift_l": "L3",
}
MOVE_KEYS = {"w", "a", "s", "d"}
car_accel = 0.0
car_brake = 0.0
car_steer = 0.0

XBOX_EXPLAIN = {
    "Esc": "Menu (Pause) — abre/fecha o menu de pausa",
    "F1":  "Guia (botão Xbox) — menu do console",
    "F2":  "Voltar (View) — mapa / voltar",
    "Home":"Guia (botão Xbox) — menu do console",
    "Ins": "Voltar (View) — mapa / voltar",
    "P":   "Voltar (View) — abre o mapa",
    "O":   "Menu (Pause) — pausa o jogo",
    "`":   "— (não mapeado)",
    "1":   "D-Pad Cima — celular (segurar)",
    "2":   "D-Pad Baixo — objetivo/minimap",
    "3":   "D-Pad Esquerda — rádio (segurar)",
    "4":   "D-Pad Direita — parceiro (segurar)",
    "5": "— (não mapeado)", "6": "— (não mapeado)",
    "7": "— (não mapeado)", "8": "— (não mapeado)",
    "9": "— (não mapeado)", "0": "— (não mapeado)",
    "-": "— (não mapeado)", "=": "— (não mapeado)",
    "Bksp": "B (Circle) — soco / voltar em menus",
    "Tab":  "— (não mapeado)",
    "Q":    "RB (R1) — cobertura",
    "W":    "LS Cima — andar para frente",
    "E":    "D-Pad Direita — interagir",
    "R":    "X (Square) — recarregar",
    "T":    "D-Pad Direita — interagir",
    "Y": "— (não mapeado)", "U": "— (não mapeado)",
    "I": "BACK (View) — inventário / mapa",
    "[": "— (não mapeado)", "]": "— (não mapeado)",
    "Enter": "A (Cross) — pular / selecionar",
    "A":  "LS Esquerda — andar para esquerda",
    "S":  "LS Baixo — andar para trás",
    "D":  "LS Direita — andar para direita",
    "F":  "Y (Triangle) — entrar/sair do carro",
    "G":  "X (Square) — quebrar janela",
    "H": "— (não mapeado)", "J": "— (não mapeado)",
    "K": "— (não mapeado)", "L": "— (não mapeado)",
    ";": "— (não mapeado)", "'": "— (não mapeado)",
    "Alt":    "Camada 1 — precisão (mouse mais lento)",
    "LCtrl":  "Camada 1 — precisão (mouse mais lento)",
    "LShift": "L3 (clique) — correr",
    "RShift": "L3 (clique) — correr",
    "Caps":   "LT (L2) — mirar (segurar)",
    "Z":      "R3 (clique) — agachar/rolar",
    "C":      "LB (L1) — roda de armas",
    "V":      "RT (R2) — meia aceleração (~25%)",
    "B":      "B (Circle) — soco",
    "N": "— (não mapeado)", "M": "— (não mapeado)",
    ",": "— (não mapeado)", ".": "— (não mapeado)",
    "/": "— (não mapeado)",
    "RCtrl": "RB (R1) — cobertura/freio de mão",
    "Space": "A (Cross) — pular",
    "LWin":  "Liga/desliga emulação + captura de mouse",
    "Up":    "RT (R2) — acelerar (carro)",
    "Down":  "LT (L2) — frear/ré (carro)",
    "Left":  "LS Esquerda — esterçar (carro)",
    "Right": "LS Direita — esterçar (carro)",
}

KEY_DISPLAY_TO_NORMAL = {
    "Esc":"esc","F1":"f1","F2":"f2","Home":"home","Ins":"insert",
    "P":"p","O":"o","LWin":"cmd","`":"`",
    "1":"1","2":"2","3":"3","4":"4","5":"5","6":"6",
    "7":"7","8":"8","9":"9","0":"0","-":"-","=":"=",
    "Bksp":"backspace","Tab":"tab","Q":"q","W":"w","E":"e",
    "R":"r","T":"t","Y":"y","U":"u","I":"i","[":"[","]":"]",
    "Enter":"enter","A":"a","S":"s","D":"d","F":"f","G":"g",
    "H":"h","J":"j","K":"k","L":"l",";":";","'":"'",
    "Alt":"alt_l","LCtrl":"ctrl_l","LShift":"shift","RShift":"shift_r","Caps":"caps_lock",
    "Z":"z","C":"c","V":"v","B":"b","N":"n","M":"m",
    ",": ",", ".": ".", "/": "/", "RCtrl": "ctrl_r", "Space": "space",
    "Up":"up","Down":"down","Left":"left","Right":"right",
}

# ------------------------------------------------------------------ helpers
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def log(msg):
    with log_lock:
        log_lines.append(msg)
        if len(log_lines) > 50:
            log_lines.pop(0)


def _apply_response(v, mode=None):
    """
    Curvas de resposta do stick:
      linear      — 1:1
      progressive — expoente 0.65: mais controle no início, alcança máximo rápido
      aim         — expoente 0.45: ainda mais controle fino (mira)
    """
    if mode is None:
        mode = RESPONSE
    if mode in ("progressive", "aim"):
        exp = 0.45 if mode == "aim" else 0.65
        sign = 1.0 if v >= 0 else -1.0
        return sign * (abs(v) ** exp)
    return v


def _apply_anti_deadzone(v):
    """Empurra a saída para além da deadzone interna do jogo (anti-deadzone)."""
    if v == 0.0:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (ANTI_DZ + abs(v) * (1.0 - ANTI_DZ))


def _radial_deadzone(vx, vy, dz):
    """Deadzone circular: zera o vetor inteiro se magnitude < dz."""
    mag = (vx * vx + vy * vy) ** 0.5
    if mag < dz:
        return 0.0, 0.0
    # re-normaliza para que o stick chegue a 1.0 na borda
    scale = (mag - dz) / (1.0 - dz)
    return vx / mag * scale, vy / mag * scale


def update_rs():
    """
    Pipeline de câmera por frame (60 Hz):
      1. Lê deltas brutos; aplica cap ±MAX_VEL para evitar overshoot
      2. Zera velocidade se mouse ficou parado (elimina drift)
      3. Aplica friction (momentum entre frames)
      4. EMA smoothing (CronusMax-style)
      5. Escala por sensibilidade + modificadores (precisão / mira)
      6. Curva de resposta (progressive normal / aim quando mirando)
      7. Deadzone radial circular
      8. Anti-deadzone (cancela a deadzone interna do jogo)
      9. Envia ao right stick
    """
    global rs_value, _mouse_idle, mouse_smooth
    while True:
        dt = 1.0 / 60.0

        # --- 1. coleta deltas + cap ---
        with mouse_lock:
            raw_x = clamp(mouse_vel["x"], -MAX_VEL / (SENS_X + 1e-6),
                          MAX_VEL / (SENS_X + 1e-6))
            raw_y = clamp(mouse_vel["y"], -MAX_VEL / (SENS_Y + 1e-6),
                          MAX_VEL / (SENS_Y + 1e-6))

            # --- 2. detecta mouse parado ---
            if raw_x == 0.0 and raw_y == 0.0:
                _mouse_idle += 1
            else:
                _mouse_idle = 0

            # zera acúmulo imediatamente quando mouse parou
            if _mouse_idle >= 1:
                mouse_vel["x"] = 0.0
                mouse_vel["y"] = 0.0
                mouse_smooth["x"] = 0.0
                mouse_smooth["y"] = 0.0
            else:
                # --- 3. friction ---
                mouse_vel["x"] *= FRICTION
                mouse_vel["y"] *= FRICTION
                if abs(mouse_vel["x"]) < 0.005: mouse_vel["x"] = 0.0
                if abs(mouse_vel["y"]) < 0.005: mouse_vel["y"] = 0.0

        # --- 4. EMA smoothing ---
        a = SMOOTHING
        mouse_smooth["x"] = a * mouse_smooth["x"] + (1.0 - a) * raw_x
        mouse_smooth["y"] = a * mouse_smooth["y"] + (1.0 - a) * raw_y
        sx, sy = mouse_smooth["x"], mouse_smooth["y"]

        # --- 5. sensibilidade + modificadores ---
        mult = 1.0
        if state["precision"]: mult *= PRECISION_MULT
        if state["aim"]:       mult *= AIM_MULT

        vx = clamp(sx * SENS_X * mult, -MAX_VEL, MAX_VEL)
        vy = clamp(sy * SENS_Y * mult, -MAX_VEL, MAX_VEL)

        # --- 6. curva de resposta ---
        curve = AIM_RESPONSE if state["aim"] else None
        vx = _apply_response(vx, curve)
        vy = _apply_response(vy, curve)

        # --- 7. deadzone radial ---
        vx, vy = _radial_deadzone(vx, vy, DEADZONE_RS)

        # --- 8. anti-deadzone ---
        if vx != 0.0 or vy != 0.0:
            vx = _apply_anti_deadzone(vx)
            vy = _apply_anti_deadzone(vy)

        rs_value["x"] = vx
        rs_value["y"] = vy

        # --- 9. envia ao gamepad (ignorado se roda de armas aberta — RS controlado pelo WASD) ---
        if gamepad is not None and state["emulation"] and state["mode"] != "inventory":
            gamepad.right_joystick_float(
                x_value_float=clamp(vx, -1.0, 1.0),
                y_value_float=clamp(vy, -1.0, 1.0),
            )
            gamepad.update()

        time.sleep(dt)


def set_button(name, val):
    if gamepad is None or not state["emulation"]:
        return
    btn = buttons.get(name)
    if btn is None:
        return
    if val:
        gamepad.press_button(button=btn)
    else:
        gamepad.release_button(button=btn)
    gamepad.update()


def set_trigger(name, value):
    if gamepad is None or not state["emulation"]:
        return
    if name == "LT":
        gamepad.left_trigger_float(value_float=clamp(value, 0.0, 1.0))
    elif name == "RT":
        gamepad.right_trigger_float(value_float=clamp(value, 0.0, 1.0))
    gamepad.update()


def set_left_stick(x, y):
    if gamepad is None or not state["emulation"]:
        return
    gamepad.left_joystick_float(
        x_value_float=clamp(x, -1.0, 1.0),
        y_value_float=clamp(y, -1.0, 1.0),
    )
    gamepad.update()

# ------------------------------------------------------------------ keyboard
def normalize_key(key):
    try:
        if key.char is not None:
            return key.char.lower()
    except AttributeError:
        pass
    try:
        name = str(key).replace("Key.", "").lower()
        # pynput reports the Windows keys as "cmd" / "cmd_l" / "cmd_r"
        if name in ("cmd", "cmd_l", "cmd_r", "left_windows", "right_windows"):
            return "cmd"
        # pynput reports Shift as "shift" / "shift_l" / "shift_r"
        if name in ("shift", "shift_l"):
            return "shift"
        if name == "shift_r":
            return "rshift"
        return name
    except Exception:
        return None


def on_key_press(key):
    global pressed, state, car_accel, car_brake, car_steer
    k = normalize_key(key)
    if k is None:
        return

    # LWin: toggle emulation + capture
    if k in ("cmd", "cmd_l", "cmd_r", "left_windows", "right_windows"):
        state["emulation"] = not state["emulation"]
        if state["emulation"]:
            start_capture()
        else:
            stop_capture()
        log("[emulacao] " + ("ON" if state["emulation"] else "OFF"))
        return

    # F12 ou Tab: toggle mode
    if k == TOGGLE_KEY or k == "tab":
        _modes = ["on_foot", "driving", "inventory"]
        _idx = (_modes.index(state["mode"]) + 1) % len(_modes)
        state["mode"] = _modes[_idx]
        # ao sair do inventário, solta LB
        if state["mode"] != "inventory":
            set_button("LB", False)
        log("[modo] " + state["mode"])
        return

    pressed.add(k)

    if k in ("ctrl_l", "ctrl", "left_ctrl"):
        state["precision"] = True

    # --- dentro do modo inventário: D-Pad = navegação, N = troca aba ---
    if state["mode"] == "inventory":
        # N: troca aba Weapons↔Items (RB tap)
        if k == "n":
            set_button("RB", True)
            time.sleep(0.05)
            set_button("RB", False)
            return
        # W/A/S/D: RS direto (wheel do GTA 6 usa right stick, não D-Pad)
        # update_rs() está bloqueado no inventory mode, então não há race condition
        if k in ("w", "a", "s", "d"):
            vx, vy = {"w": (0,1), "s": (0,-1), "a": (-1,0), "d": (1,0)}[k]
            gamepad.right_joystick_float(x_value_float=vx, y_value_float=vy)
            return
        return   # ignora outras teclas no inventário

    if not state["emulation"]:
        return

    if state["mode"] == "driving":
        if k in ("w", "up"):
            car_accel = 1.0; set_trigger("RT", 1.0)
        if k in ("s", "down"):
            car_brake = 1.0; set_trigger("LT", 1.0)
        if k in ("a", "left"):
            car_steer = -1.0
        if k in ("d", "right"):
            car_steer = 1.0
        if k in ("a", "d", "left", "right"):
            set_left_stick(car_steer, 0.0)
        if k == "space": set_button("A", True)
        if k == "v":     set_trigger("RT", HALF_THROTTLE)
        if k in KEY_MAP: set_button(KEY_MAP[k], True)
        return

    if k in MOVE_KEYS:
        x = (-1.0 if "a" in pressed else 0.0) + (1.0 if "d" in pressed else 0.0)
        y = ( 1.0 if "w" in pressed else 0.0) + (-1.0 if "s" in pressed else 0.0)
        set_left_stick(x, y)
    if k == "v":     set_trigger("RT", HALF_THROTTLE)
    if k in KEY_MAP: set_button(KEY_MAP[k], True)


def on_key_release(key):
    global pressed, state, car_accel, car_brake, car_steer
    k = normalize_key(key)
    if k is None:
        return

    pressed.discard(k)

    # C solto no inventory mode: NÃO solta LB (mantém roda aberta; Tab/F12 sai do modo)
    if k == "c" and state["mode"] == "inventory":
        return

    # W/A/S/D solto no modo inventário → RS volta ao centro
    if state["mode"] == "inventory" and k in ("w", "a", "s", "d"):
        if gamepad is not None:
            gamepad.right_joystick_float(x_value_float=0.0, y_value_float=0.0)
        return

    if k in ("ctrl_l", "ctrl", "left_ctrl"):
        state["precision"] = False

    if not state["emulation"]:
        return

    if state["mode"] == "driving":
        if k in ("w", "up"):
            car_accel = 0.0; set_trigger("RT", 0.0)
        if k in ("s", "down"):
            car_brake = 0.0; set_trigger("LT", 0.0)
        if k in ("a", "d", "left", "right"):
            x = (-1.0 if "a" in pressed or "left" in pressed else 0.0) + \
                ( 1.0 if "d" in pressed or "right" in pressed else 0.0)
            set_left_stick(x, 0.0)
        if k == "space": set_button("A", False)
        if k == "v":     set_trigger("RT", 0.0)
        if k in KEY_MAP: set_button(KEY_MAP[k], False)
        return

    if k in MOVE_KEYS:
        x = (-1.0 if "a" in pressed else 0.0) + (1.0 if "d" in pressed else 0.0)
        y = ( 1.0 if "w" in pressed else 0.0) + (-1.0 if "s" in pressed else 0.0)
        set_left_stick(x, y)
    if k == "v":     set_trigger("RT", 0.0)
    if k in KEY_MAP: set_button(KEY_MAP[k], False)

# ------------------------------------------------------------------ mouse
def on_mouse_move(x, y):
    global _last_mouse
    if _last_mouse["x"] is None:
        _last_mouse["x"] = x; _last_mouse["y"] = y
        return
    dx = x - _last_mouse["x"]
    dy = y - _last_mouse["y"]
    _last_mouse["x"] = x
    _last_mouse["y"] = y
    if not state["emulation"] or not state["mouse_captured"]:
        return
    with mouse_lock:
        mouse_vel["x"] += dx
        mouse_vel["y"] += dy


def on_mouse_click(x, y, button, pressed_flag):
    if not state["emulation"] or not state["mouse_captured"]:
        return
    btn = str(button).replace("Button.", "")
    if btn == "left":
        set_trigger("RT", 1.0 if pressed_flag else 0.0)
    elif btn == "right":
        state["aim"] = pressed_flag
        set_trigger("LT", 1.0 if pressed_flag else 0.0)
    elif btn == "middle":
        set_button("B", pressed_flag)
    elif btn == "x1":
        set_button("A", pressed_flag)
    elif btn == "x2":
        set_button("RB", pressed_flag)


def on_mouse_scroll(x, y, dx, dy):
    if not state["emulation"] or not state["mouse_captured"]:
        return
    if dy > 0:
        set_button("LB", True);  time.sleep(0.05); set_button("LB", False)
    elif dy < 0:
        set_button("RB", True);  time.sleep(0.05); set_button("RB", False)

# ------------------------------------------------------------------ GUI
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("GTA6 Controller — ViGEmBus")
        self.root.geometry("1200x800")
        self.root.configure(bg="#1a1a2e")

        # Header
        header = tk.Frame(root, bg="#1a1a2e")
        header.pack(fill="x", padx=10, pady=4)

        self.mode_label = tk.Label(header, text="MODO: A PE",
                                   font=("Segoe UI", 20, "bold"),
                                   fg="#00ff88", bg="#1a1a2e")
        self.mode_label.pack(side="left")

        self.emu_btn = tk.Button(header, text="Emulação: ON",
                                 font=("Segoe UI", 12, "bold"),
                                 bg="#00ff88", fg="#1a1a2e", width=16,
                                 command=self.toggle_emu)
        self.emu_btn.pack(side="right")

        self.mouse_label = tk.Label(header, text="🖱 MOUSE: LIVRE",
                                    font=("Segoe UI", 12, "bold"),
                                    fg="#808080", bg="#1a1a2e")
        self.mouse_label.pack(side="right", padx=12)

        # Sliders
        sliders = tk.Frame(root, bg="#1a1a2e")
        sliders.pack(fill="x", padx=10, pady=5)
        self.sliders = {}
        for name, val, lo, hi, res in [
            ("SENS_X",      0.20, 0.05, 0.60, 0.01),
            ("SENS_Y",      0.18, 0.05, 0.60, 0.01),
            ("DEADZONE_RS", 0.08, 0.00, 0.40, 0.01),
            ("ANTI_DZ",     0.08, 0.00, 0.30, 0.01),
            ("FRICTION",    0.80, 0.50, 0.98, 0.01),
            ("SMOOTHING",   0.20, 0.00, 0.80, 0.01),
            ("WHEEL_MULT",  0.12, 0.02, 0.50, 0.01),
        ]:
            f = tk.Frame(sliders, bg="#1a1a2e")
            f.pack(side="left", padx=8, expand=True, fill="x")
            lbl_text = {
                "SENS_X":      "SENS X (horiz)",
                "SENS_Y":      "SENS Y (vert)",
                "DEADZONE_RS": "DEADZONE",
                "ANTI_DZ":     "ANTI-DEADZONE",
                "FRICTION":    "FRICTION",
                "SMOOTHING":   "SMOOTHING",
                "WHEEL_MULT":  "SENS RODA",
            }.get(name, name)
            tk.Label(f, text=lbl_text, fg="#e0e0e0", bg="#1a1a2e",
                     font=("Segoe UI", 11, "bold")).pack()
            s = tk.Scale(f, from_=lo, to=hi, resolution=res, orient="horizontal",
                         bg="#2d2d44", fg="#e0e0e0", troughcolor="#3d3d5c",
                         highlightthickness=0, length=200, font=("Segoe UI", 9))
            s.set(val)
            s.pack()
            self.sliders[name] = s

        # Botão de curva de resposta
        self.response_var = tk.StringVar(value="progressive")
        resp_frame = tk.Frame(sliders, bg="#1a1a2e")
        resp_frame.pack(side="left", padx=8)
        tk.Label(resp_frame, text="CURVA", fg="#e0e0e0", bg="#1a1a2e",
                 font=("Segoe UI", 11, "bold")).pack()
        self.resp_btn = tk.Button(resp_frame, text="Progressive",
                                  font=("Segoe UI", 10, "bold"),
                                  bg="#3d3d5c", fg="#e0e0e0", width=12,
                                  command=self.toggle_response)
        self.resp_btn.pack(pady=4)

        # Keyboard zoom
        zoom_frame = tk.Frame(root, bg="#1a1a2e")
        zoom_frame.pack(fill="x", padx=10, pady=2)
        tk.Label(zoom_frame, text="TAMANHO DO TECLADO", fg="#e0e0e0", bg="#1a1a2e",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=5)
        self.kb_zoom = tk.Scale(zoom_frame, from_=0.5, to=3.0, resolution=0.1,
                                orient="horizontal", bg="#2d2d44", fg="#e0e0e0",
                                troughcolor="#3d3d5c", highlightthickness=0,
                                length=300, font=("Segoe UI", 9))
        self.kb_zoom.set(1.0)
        self.kb_zoom.pack(side="left", padx=5)

        # Main area
        main_area = tk.Frame(root, bg="#1a1a2e")
        main_area.pack(fill="both", expand=True, padx=10, pady=5)

        kb_frame = tk.LabelFrame(main_area, text="  TECLADO (Camada 0)  ",
                                 fg="#e0e0e0", bg="#1a1a2e",
                                 font=("Segoe UI", 14, "bold"))
        kb_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        right_panel = tk.Frame(main_area, bg="#1a1a2e")
        right_panel.pack(side="right", fill="y", padx=(5, 0))

        mouse_frame = tk.LabelFrame(right_panel, text="  MOUSE  ",
                                    fg="#e0e0e0", bg="#1a1a2e",
                                    font=("Segoe UI", 11, "bold"))
        mouse_frame.pack(fill="x", pady=(0, 3))
        for line in ["LMB → RT (atirar/acelerar)",
                     "RMB (segurar) → LT (mirar/frear)",
                     "MMB → B (soco)", "MB4 → A (pular)",
                     "MB5 → RB (cobertura)",
                     "Wheel ↑ → LB  /  ↓ → RB",
                     "Move → RS (câmera)"]:
            tk.Label(mouse_frame, text=line, fg="#e0e0e0", bg="#1a1a2e",
                     font=("Consolas", 10), anchor="w").pack(fill="x", padx=5, pady=1)

        layer_frame = tk.LabelFrame(right_panel, text="  CAMADAS  ",
                                    fg="#e0e0e0", bg="#1a1a2e",
                                    font=("Segoe UI", 11, "bold"))
        layer_frame.pack(fill="x", pady=(3, 0))
        for line in ["LCtrl/Alt: mouse mais lento",
                     "RMB: LT (mira) + cursor mais lento",
                     "C (segurar): roda de armas / inventário (LB)",
                     "N: troca aba Weapons↔Items (roda aberta)",
                     "F12/Tab: a pé / no carro  |  LWin: liga/desliga",
                     "V: RT ~25% (meia acel)  |  H: olhar atrás (R3)"]:
            tk.Label(layer_frame, text=line, fg="#e0e0e0", bg="#1a1a2e",
                     font=("Consolas", 10), anchor="w").pack(fill="x", padx=5, pady=1)

        rows = [
            [("Esc","Menu"),("F1","Guia"),("F2","Mapa"),("Home","Guia"),
             ("Ins","Mapa"),("P","Mapa"),("O","Menu"),("LWin","Captura")],
            [("`",""),("1","D-Cima"),("2","D-Baixo"),("3","D-Esq"),("4","D-Dir"),
             ("5",""),("6",""),("7",""),("8",""),("9",""),("0",""),
             ("-",""),("=",""),("Bksp","B")],
            [("Tab",""),("Q","RB Cobertura"),("W","LS Cima"),("E","D-Dir"),("R","X Recarrega"),
             ("T","D-Dir"),("Y",""),("U",""),("I","BACK"),
             ("[",""),("'",""),("Enter","A")],
            [("A","LS Esq"),("S","LS Baixo"),("D","LS Dir"),("F","Y Interage"),("G","Y Arromba"),
             ("H","R3 Atrás"),("J",""),("K",""),("L",""),
             (";",""),("Alt","Cam1")],
            [("LCtrl","Cam1"),("LShift","L3 Corre"),("RShift","L3 Corre"),("Caps","LT"),
             ("Z","B Agacha"),("C","LB Segura"),("V","RT 25%"),("B","X Soco"),("N","Tab Roda"),("M",""),
             (",",""),(".",""),("/",""),("RCtrl","RB")],
            [("Space","A Pula")],
        ]

        self.key_buttons = {}
        for row in rows:
            rf = tk.Frame(kb_frame, bg="#1a1a2e")
            rf.pack(fill="x", pady=2)
            for key, action in row:
                color = "#3d3d5c" if action else "#252535"
                fg    = "#ffffff"  if action else "#707080"
                btn = tk.Button(rf, text=key + "\n" + (action or "—"),
                                width=10, height=3,
                                font=("Consolas", 10, "bold"),
                                bg=color, fg=fg, relief="flat",
                                borderwidth=1, highlightthickness=1,
                                highlightbackground="#505070")
                btn.pack(side="left", padx=2, pady=2)
                self.key_buttons[key] = btn
                self._add_tooltip(btn, XBOX_EXPLAIN.get(key, "— (não mapeado)"))
                btn.bind("<Button-3>", lambda e, k=key: self._open_binding_editor(k))

        # Log
        log_frame = tk.LabelFrame(root, text="  LOG  ", fg="#e0e0e0", bg="#1a1a2e",
                                  font=("Segoe UI", 11, "bold"))
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text = tk.Text(log_frame, height=8, bg="#0a0a14", fg="#00ff88",
                                font=("Consolas", 10), state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Tooltip
        self.tooltip = tk.Toplevel(root)
        self.tooltip.withdraw()
        self.tooltip.overrideredirect(True)
        self.tooltip.attributes("-topmost", True)
        self.tooltip_label = tk.Label(self.tooltip, text="", bg="#2d2d44",
                                      fg="#e0e0e0", font=("Segoe UI", 10),
                                      padx=8, pady=4, relief="solid", borderwidth=1)
        self.tooltip_label.pack()

        self.update_ui()

    def _add_tooltip(self, widget, text):
        def on_enter(e):
            self.tooltip_label.config(text=text)
            self.tooltip.geometry("+%d+%d" % (e.x_root + 10, e.y_root + 10))
            self.tooltip.deiconify()
        def on_leave(e):
            self.tooltip.withdraw()
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def toggle_emu(self):
        state["emulation"] = not state["emulation"]
        if state["emulation"]:
            start_capture()
        else:
            stop_capture()
        self.emu_btn.config(
            text="Emulação: " + ("ON" if state["emulation"] else "OFF"),
            bg="#00ff88" if state["emulation"] else "#ff5555",
        )
        log("[emulacao] " + ("ON" if state["emulation"] else "OFF"))

    def toggle_response(self):
        global RESPONSE
        RESPONSE = "linear" if RESPONSE == "progressive" else "progressive"
        self.resp_btn.config(
            text="Progressive" if RESPONSE == "progressive" else "Linear",
            bg="#005599" if RESPONSE == "progressive" else "#3d3d5c",
        )
        log(f"[câmera] curva: {RESPONSE}")

    def _open_binding_editor(self, display_key):
        """Botão direito numa tecla → popup para reatribuir o botão Xbox."""
        XBOX_BUTTONS = [
            "A", "B", "X", "Y",
            "LB", "RB", "LT", "RT",
            "L3", "R3",
            "START", "BACK", "GUIDE",
            "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
            "— (remover)",
        ]
        norm = KEY_DISPLAY_TO_NORMAL.get(display_key, display_key.lower())
        current = KEY_MAP.get(norm, "—")

        popup = tk.Toplevel(self.root)
        popup.title(f"Reatribuir  {display_key}")
        popup.configure(bg="#1a1a2e")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)
        tk.Label(popup, text=f"Tecla:  {display_key}   →   atual: {current}",
                 fg="#e0e0e0", bg="#1a1a2e",
                 font=("Segoe UI", 11, "bold")).pack(padx=16, pady=(12, 4))
        tk.Label(popup, text="Clique no botão Xbox desejado (feche para cancelar):",
                 fg="#aaaaaa", bg="#1a1a2e",
                 font=("Segoe UI", 9)).pack(padx=16, pady=(0, 8))

        grid = tk.Frame(popup, bg="#1a1a2e")
        grid.pack(padx=16, pady=(0, 12))

        def apply_binding(xbox_btn):
            if xbox_btn == "— (remover)":
                KEY_MAP.pop(norm, None)
                new_action = "—"
            else:
                KEY_MAP[norm] = xbox_btn
                new_action = xbox_btn
            if display_key in self.key_buttons:
                has = new_action != "—"
                self.key_buttons[display_key].config(
                    text=display_key + "\n" + new_action,
                    bg="#3d3d5c" if has else "#252535",
                    fg="#ffffff"  if has else "#707080",
                )
            log(f"[binding] {display_key} → {new_action}")
            popup.destroy()

        for i, xbtn in enumerate(XBOX_BUTTONS):
            col, row_i = i % 4, i // 4
            highlight = "#005599" if xbtn == current else "#3d3d5c"
            tk.Button(grid, text=xbtn, width=14,
                      font=("Segoe UI", 10, "bold"),
                      bg=highlight, fg="#e0e0e0",
                      command=lambda b=xbtn: apply_binding(b)
                      ).grid(row=row_i, column=col, padx=4, pady=3)


    def update_ui(self):
        # mode
        mode = state["mode"]
        MODE_LABELS = {"on_foot": ("A PE", "#00ff88"), "driving": ("NO CARRO", "#ffaa00"), "inventory": ("INVENTÁRIO", "#aa66ff")}
        txt, clr = MODE_LABELS.get(mode, (mode.upper(), "#e0e0e0"))
        self.mode_label.config(text="MODO: " + txt, fg=clr)

        # sliders → globals
        global DEADZONE_RS, ANTI_DZ, SENS_X, SENS_Y, FRICTION, SMOOTHING, WHEEL_MULT
        DEADZONE_RS  = self.sliders["DEADZONE_RS"].get()
        ANTI_DZ      = self.sliders["ANTI_DZ"].get()
        SENS_X       = self.sliders["SENS_X"].get()
        SENS_Y       = self.sliders["SENS_Y"].get()
        FRICTION     = self.sliders["FRICTION"].get()
        SMOOTHING    = self.sliders["SMOOTHING"].get()
        WHEEL_MULT   = self.sliders["WHEEL_MULT"].get()
        # emulacao + mouse capture status
        self.emu_btn.config(
            text="Emulação: " + ("ON" if state["emulation"] else "OFF"),
            bg="#00ff88" if state["emulation"] else "#ff5555",
        )
        if state["mouse_captured"]:
            r = state["capture_rect"]
            dim = f" {r[2]-r[0]}x{r[3]-r[1]}" if r else ""
            self.mouse_label.config(text=f"🖱 CAPTURADO{dim}", fg="#00aaff")
        else:
            self.mouse_label.config(text="🖱 MOUSE: LIVRE", fg="#808080")



        # zoom
        zoom      = self.kb_zoom.get()
        btn_w     = max(6, int(10 * zoom))
        btn_h     = max(2, int(3  * zoom))
        font_size = max(8, int(10 * zoom))
        for btn in self.key_buttons.values():
            btn.config(width=btn_w, height=btn_h,
                       font=("Consolas", font_size, "bold"))

        # key LEDs
        for key, btn in self.key_buttons.items():
            norm = KEY_DISPLAY_TO_NORMAL.get(key, key.lower())
            if norm in pressed:
                btn.config(bg="#ffdd00", fg="#1a1a2e")
            else:
                action = XBOX_EXPLAIN.get(key, "—")
                if action and action != "— (não mapeado)":
                    btn.config(bg="#3d3d5c", fg="#e0e0e0")
                else:
                    btn.config(bg="#252535", fg="#707080")

        # log
        with log_lock:
            lines = list(log_lines)
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(lines))
        self.log_text.config(state="disabled")
        self.log_text.see("end")

        self.root.after(100, self.update_ui)

# ------------------------------------------------------------------ main
def main():
    global gamepad, buttons
    gamepad = vg.VX360Gamepad()
    buttons.update({
        "A":          vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
        "B":          vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
        "X":          vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
        "Y":          vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
        "LB":         vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
        "RB":         vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
        "L3":         vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
        "R3":         vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
        "START":      vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
        "BACK":       vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
        "GUIDE":      vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
        "DPAD_UP":    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        "DPAD_DOWN":  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        "DPAD_LEFT":  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        "DPAD_RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    })

    threading.Thread(target=update_rs, daemon=True).start()

    kb_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)
    mouse_listener = mouse.Listener(
        on_move=on_mouse_move,
        on_click=on_mouse_click,
        on_scroll=on_mouse_scroll,
    )
    kb_listener.start()
    mouse_listener.start()

    root = tk.Tk()
    app = App(root)
    # captura logo após a janela aparecer (emulação começa ON)
    root.after(600, start_capture)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        stop_capture()
        kb_listener.stop()
        mouse_listener.stop()


if __name__ == "__main__":
    main()
