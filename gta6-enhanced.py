# -*- coding: utf-8 -*-
"""
GTA 6 Enhanced Controller Emulator
- Mouse capture exclusivo (não interage com outras janelas)
- Cursor confinement
- Hook global de mouse
- Indicador visual de captura
"""

import time
import threading
import tkinter as tk
from tkinter import ttk
import ctypes
import ctypes.wintypes

# ------------------------------------------------------------------ config
DEADZONE_RS = 0.10
SENS_X = 0.10
SENS_Y = 0.10
SMOOTHING = 0.3
CURVE = "linear"
MAX_VEL = 1.0
PRECISION_MULT = 0.5
AIM_MULT = 0.6
HALF_THROTTLE = 0.25
TOGGLE_KEY = "f12"

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

# ------------------------------------------------------------------ Win32 API para mouse capture
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Estruturas Win32
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

# Constantes
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C

# Callback type
LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)
)

# ------------------------------------------------------------------ estado
state = {
    "emulation": False,
    "mouse_captured": False,  # Mouse capturado exclusivamente
    "capture_rect": None,     # Área de confinamento
    "block_external": True,   # Bloqueia eventos fora da área
}

buttons = {}
pressed = set()
mouse_vel = {"x": 0.0, "y": 0.0}
mouse_lock = threading.Lock()
rs_value = {"x": 0.0, "y": 0.0}
_last_mouse = {"x": None, "y": None}
gamepad = None
log_lines = []
log_lock = threading.Lock()

# Hook global
mouse_hook = None
hook_thread = None
hook_handle = None

KEY_MAP = {
    "num_8": "LS_UP", "num_2": "LS_DOWN", "num_4": "LS_LEFT", "num_6": "LS_RIGHT",
    "num_7": "RS_LEFT", "num_9": "RS_RIGHT", "num_1": "RS_DOWN", "num_3": "RS_UP",
    "num_enter": "RT", "num_0": "LT", "num_decimal": "A", "num_add": "B",
    "num_subtract": "X", "num_multiply": "Y", "num_divide": "LS_CLICK",
    "page_up": "RB", "page_down": "LB", "home": "START", "end": "BACK",
    "insert": "DPAD_UP", "delete": "DPAD_DOWN", "scroll_lock": "DPAD_LEFT",
    "pause": "DPAD_RIGHT",
}

MOVE_KEYS = {"num_8", "num_2", "num_4", "num_6"}
car_accel = 0.0
car_brake = 0.0
car_steer = 0.0

XBOX_EXPLAIN = {
    "num_8": "Esquerdo Analógico ↑ (caminhar para frente)",
    "num_2": "Esquerdo Analógico ↓ (caminhar para trás)",
    "num_4": "Esquerdo Analógico ← (caminhar esquerda)",
    "num_6": "Esquerdo Analógico → (caminhar direita)",
    "num_7": "Direito Analógico ← (câmera/mira esquerda)",
    "num_9": "Direito Analógico → (câmera/mira direita)",
    "num_1": "Direito Analógico ↓ (câmera para baixo)",
    "num_3": "Direito Analógico ↑ (câmera para cima)",
    "num_enter": "RT (atirar/acelerar)",
    "num_0": "LT (mirar/freio)",
    "num_decimal": "A (pular/ação)",
    "num_add": "B (cancelar/sair do carro)",
    "num_subtract": "X (recarregar/interagir)",
    "num_multiply": "Y (entrar no carro/trocar arma)",
    "num_divide": "L3 (sprint/agachar)",
    "page_up": "RB (freio de mão/cobertura)",
    "page_down": "LB (roda de armas)",
    "home": "START (menu/pausa)",
    "end": "BACK (mapa)",
    "insert": "D-pad ↑ (telefone)",
    "delete": "D-pad ↓ (personagem especial)",
    "scroll_lock": "D-pad ← (rádio)",
    "pause": "D-pad → (habilidade especial)",
}

KEY_DISPLAY_TO_NORMAL = {
    "Num 8": "num_8", "Num 2": "num_2", "Num 4": "num_4", "Num 6": "num_6",
    "Num 7": "num_7", "Num 9": "num_9", "Num 1": "num_1", "Num 3": "num_3",
    "Enter": "num_enter", "Num 0": "num_0", "Decimal": "num_decimal",
    "Add": "num_add", "Subtract": "num_subtract", "Multiply": "num_multiply",
    "Divide": "num_divide", "Page Up": "page_up", "Page Down": "page_down",
    "Home": "home", "End": "end", "Insert": "insert", "Delete": "delete",
    "Scroll Lock": "scroll_lock", "Pause": "pause",
}

# ------------------------------------------------------------------ utilidades
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def curve(v):
    if CURVE == "exponential":
        return v * abs(v)
    return v

def log(msg):
    with log_lock:
        log_lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(log_lines) > 100:
            log_lines.pop(0)

# ------------------------------------------------------------------ mouse capture exclusivo
def get_screen_rect():
    """Retorna a área total da tela principal."""
    rect = RECT()
    user32.GetWindowRect(user32.GetDesktopWindow(), ctypes.byref(rect))
    return rect

def confine_cursor(rect=None):
    """Confina o cursor a uma área específica (ou libera se None)."""
    if rect:
        r = RECT(rect[0], rect[1], rect[2], rect[3])
        user32.ClipCursor(ctypes.byref(r))
        log(f"Cursor confinado: {rect}")
    else:
        user32.ClipCursor(None)
        log("Cursor liberado")

def is_point_in_rect(x, y, rect):
    """Verifica se um ponto está dentro de um retângulo."""
    if rect is None:
        return True
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]

def get_game_window_rect():
    """Tenta obter a área da janela do jogo."""
    hwnd = user32.GetForegroundWindow()
    if hwnd == 0:
        return None
    
    # Verifica se é janela do jogo
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return None
    
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    title = buff.value.lower()
    
    if not any(k in title for k in ["xbox", "remote play", "veyra", "gta"]):
        return None
    
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)

# ------------------------------------------------------------------ hook global de mouse
def low_level_mouse_handler(nCode, wParam, lParam):
    """Handler do hook de mouse de baixo nível."""
    if nCode >= 0 and state["mouse_captured"]:
        # Pega posição do cursor
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        
        # Verifica se está dentro da área permitida
        if state["capture_rect"] and not is_point_in_rect(pt.x, pt.y, state["capture_rect"]):
            # Fora da área - bloqueia o evento
            if state["block_external"]:
                return 1  # Bloqueia
    
    # Passa adiante
    return user32.CallNextHookEx(hook_handle, nCode, wParam, lParam)

def install_mouse_hook():
    """Instala o hook global de mouse."""
    global hook_handle, mouse_hook
    
    # Cria callback
    mouse_hook = LowLevelMouseProc(low_level_mouse_handler)
    
    # Instala hook
    hook_handle = user32.SetWindowsHookExA(
        WH_MOUSE_LL,
        mouse_hook,
        kernel32.GetModuleHandleW(None),
        0
    )
    
    if hook_handle == 0:
        log("ERRO: Falha ao instalar hook de mouse")
        return False
    
    log("Hook de mouse instalado")
    return True

def uninstall_mouse_hook():
    """Remove o hook global de mouse."""
    global hook_handle
    if hook_handle:
        user32.UnhookWindowsHookEx(hook_handle)
        hook_handle = None
        log("Hook de mouse removido")

def start_mouse_capture():
    """Inicia a captura exclusiva do mouse."""
    if state["mouse_captured"]:
        return
    
    # Tenta obter a área da janela do jogo
    game_rect = get_game_window_rect()
    if game_rect:
        state["capture_rect"] = game_rect
    else:
        # Usa tela toda como fallback
        screen = get_screen_rect()
        state["capture_rect"] = (screen.left, screen.top, screen.right, screen.bottom)
    
    # Confina cursor
    confine_cursor(state["capture_rect"])
    
    # Instala hook
    install_mouse_hook()
    
    state["mouse_captured"] = True
    log("Mouse capturado!")

def stop_mouse_capture():
    """Para a captura exclusiva do mouse."""
    if not state["mouse_captured"]:
        return
    
    # Libera cursor
    confine_cursor(None)
    
    # Remove hook
    uninstall_mouse_hook()
    
    state["mouse_captured"] = False
    state["capture_rect"] = None
    log("Mouse liberado")

# ------------------------------------------------------------------ gamepad
def update_rs():
    global rs_value
    while True:
        if not state["emulation"]:
            time.sleep(0.05)
            continue
        
        with mouse_lock:
            vx = mouse_vel["x"]
            vy = mouse_vel["y"]
            mouse_vel["x"] *= (1.0 - SMOOTHING)
            mouse_vel["y"] *= (1.0 - SMOOTHING)
        
        vx = clamp(vx, -MAX_VEL, MAX_VEL)
        vy = clamp(vy, -MAX_VEL, MAX_VEL)
        
        vx = curve(vx)
        vy = curve(vy)
        
        if abs(vx) < DEADZONE_RS:
            vx = 0.0
        if abs(vy) < DEADZONE_RS:
            vy = 0.0
        
        rs_value["x"] = vx
        rs_value["y"] = vy
        
        if gamepad and state["emulation"]:
            x_int = int(clamp(vx * 32767, -32767, 32767))
            y_int = int(clamp(vy * 32767, -32767, 32767))
            gamepad.right_joystick(x_int, -y_int)
            gamepad.update()
        
        time.sleep(1.0 / 60.0)

def set_button(name, pressed):
    if gamepad is None or not state["emulation"]:
        return
    vg_name = f"XUSB_BUTTON_{name}"
    attr = getattr(vg.XUSB_BUTTON, name, None)
    if attr:
        if pressed:
            gamepad.press_button(attr)
        else:
            gamepad.release_button(attr)
        gamepad.update()

def set_trigger(name, value):
    if gamepad is None or not state["emulation"]:
        return
    val = int(clamp(value * 255, 0, 255))
    if name == "RT":
        gamepad.right_trigger(val)
    elif name == "LT":
        gamepad.left_trigger(val)
    gamepad.update()

def set_left_stick(x, y):
    if gamepad is None or not state["emulation"]:
        return
    xi = int(clamp(x * 32767, -32767, 32767))
    yi = int(clamp(y * 32767, -32767, 32767))
    gamepad.left_joystick(xi, -yi)
    gamepad.update()

# ------------------------------------------------------------------ input handlers
def normalize_key(key):
    try:
        if hasattr(key, "name"):
            return key.name
        elif hasattr(key, "vk"):
            return keyboard.KeyCode.from_vk(key.vk).name
        else:
            return str(key)
    except:
        return None

def on_key_press(key):
    global pressed, state, car_accel, car_brake, car_steer
    
    if not state["emulation"]:
        return
    
    k = normalize_key(key)
    if k is None:
        return
    
    # Toggle
    if k == TOGGLE_KEY:
        return
    
    pressed.add(k)
    
    # Movimentação (left stick)
    if k in MOVE_KEYS:
        x, y = 0.0, 0.0
        if "num_4" in pressed:
            x -= 1.0
        if "num_6" in pressed:
            x += 1.0
        if "num_8" in pressed:
            y += 1.0
        if "num_2" in pressed:
            y -= 1.0
        set_left_stick(x, y)
        return
    
    # Câmera manual (right stick)
    if k in ["num_7", "num_9", "num_1", "num_3"]:
        x, y = 0.0, 0.0
        if "num_7" in pressed:
            x -= 0.8
        if "num_9" in pressed:
            x += 0.8
        if "num_1" in pressed:
            y -= 0.8
        if "num_3" in pressed:
            y += 0.8
        if gamepad and state["emulation"]:
            xi = int(clamp(x * 32767, -32767, 32767))
            yi = int(clamp(y * 32767, -32767, 32767))
            gamepad.right_joystick(xi, -yi)
            gamepad.update()
        return
    
    # Triggers
    if k == "num_enter":
        set_trigger("RT", 1.0)
        return
    if k == "num_0":
        set_trigger("LT", 1.0)
        return
    
    # Botões
    if k in KEY_MAP:
        set_button(KEY_MAP[k], True)

def on_key_release(key):
    global pressed, state, car_accel, car_brake, car_steer
    
    if not state["emulation"]:
        return
    
    k = normalize_key(key)
    if k is None:
        return
    
    # Toggle
    if k == TOGGLE_KEY:
        state["emulation"] = not state["emulation"]
        if state["emulation"]:
            start_mouse_capture()
            log("✓ Emulação ATIVADA")
        else:
            stop_mouse_capture()
            log("✗ Emulação DESATIVADA")
        return
    
    pressed.discard(k)
    
    # Movimentação
    if k in MOVE_KEYS:
        x, y = 0.0, 0.0
        if "num_4" in pressed:
            x -= 1.0
        if "num_6" in pressed:
            x += 1.0
        if "num_8" in pressed:
            y += 1.0
        if "num_2" in pressed:
            y -= 1.0
        set_left_stick(x, y)
        return
    
    # Câmera manual
    if k in ["num_7", "num_9", "num_1", "num_3"]:
        x, y = 0.0, 0.0
        if "num_7" in pressed:
            x -= 0.8
        if "num_9" in pressed:
            x += 0.8
        if "num_1" in pressed:
            y -= 0.8
        if "num_3" in pressed:
            y += 0.8
        if gamepad and state["emulation"]:
            xi = int(clamp(x * 32767, -32767, 32767))
            yi = int(clamp(y * 32767, -32767, 32767))
            gamepad.right_joystick(xi, -yi)
            gamepad.update()
        return
    
    # Triggers
    if k == "num_enter":
        set_trigger("RT", 0.0)
        return
    if k == "num_0":
        set_trigger("LT", 0.0)
        return
    
    # Botões
    if k in KEY_MAP:
        set_button(KEY_MAP[k], False)

def on_mouse_move_abs(x, y):
    global _last_mouse
    if not state["emulation"]:
        return
    
    # Ignora se mouse não está capturado
    if not state["mouse_captured"]:
        return
    
    # Verifica se está dentro da área
    if state["capture_rect"] and not is_point_in_rect(x, y, state["capture_rect"]):
        return
    
    if _last_mouse["x"] is None:
        _last_mouse["x"] = x
        _last_mouse["y"] = y
        return
    
    dx = (x - _last_mouse["x"]) * SENS_X
    dy = (y - _last_mouse["y"]) * SENS_Y
    _last_mouse["x"] = x
    _last_mouse["y"] = y
    
    # Multiplica pela sensibilidade
    mult = PRECISION_MULT if "shift" in pressed else 1.0
    mult *= AIM_MULT if "num_0" in pressed else 1.0
    dx *= mult
    dy *= mult
    
    with mouse_lock:
        mouse_vel["x"] += dx
        mouse_vel["y"] += dy

def on_mouse_click(x, y, button, pressed_flag):
    if not state["emulation"] or not state["mouse_captured"]:
        return
    
    # Verifica se está dentro da área
    if state["capture_rect"] and not is_point_in_rect(x, y, state["capture_rect"]):
        return
    
    if button == mouse.Button.left:
        set_trigger("RT", 1.0 if pressed_flag else 0.0)
    elif button == mouse.Button.right:
        set_trigger("LT", 1.0 if pressed_flag else 0.0)
    elif button == mouse.Button.middle:
        set_button("Y", pressed_flag)
    elif button == mouse.Button.x1:
        set_button("LB", pressed_flag)
    elif button == mouse.Button.x2:
        set_button("RB", pressed_flag)

def on_mouse_scroll(x, y, dx, dy):
    if not state["emulation"] or not state["mouse_captured"]:
        return
    
    if dy > 0:
        set_button("LB", True)
        time.sleep(0.1)
        set_button("LB", False)
    elif dy < 0:
        set_button("RB", True)
        time.sleep(0.1)
        set_button("RB", False)

# ------------------------------------------------------------------ GUI
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("GTA 6 Enhanced Controller - Mouse Capture")
        self.root.geometry("700x600")
        
        # Frame principal
        main_frame = ttk.Frame(root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Título
        title = ttk.Label(main_frame, text="🎮 GTA 6 Enhanced Controller", font=("Arial", 16, "bold"))
        title.pack(pady=10)
        
        # Status
        self.status_frame = ttk.LabelFrame(main_frame, text="Status", padding=10)
        self.status_frame.pack(fill=tk.X, pady=5)
        
        self.lbl_status = ttk.Label(self.status_frame, text="❌ Desativado", font=("Arial", 12, "bold"), foreground="red")
        self.lbl_status.pack()
        
        self.lbl_mouse = ttk.Label(self.status_frame, text="🖱️ Mouse: Livre", font=("Arial", 10))
        self.lbl_mouse.pack()
        
        # Controles
        ctrl_frame = ttk.LabelFrame(main_frame, text="Controles", padding=10)
        ctrl_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(ctrl_frame, text="Pressione F12 para ativar/desativar", font=("Arial", 10, "bold")).pack()
        ttk.Label(ctrl_frame, text="Quando ativado, o mouse fica capturado e não interage com outras janelas").pack()
        
        # Configurações
        config_frame = ttk.LabelFrame(main_frame, text="Configurações", padding=10)
        config_frame.pack(fill=tk.X, pady=5)
        
        # Captura estrita
        self.var_strict = tk.BooleanVar(value=True)
        chk_strict = ttk.Checkbutton(
            config_frame,
            text="Bloquear mouse fora da área do jogo",
            variable=self.var_strict,
            command=self.on_strict_changed
        )
        chk_strict.pack(anchor=tk.W)
        
        # Sensibilidade
        sens_frame = ttk.Frame(config_frame)
        sens_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(sens_frame, text="Sensibilidade X:").pack(side=tk.LEFT)
        self.scale_sens_x = ttk.Scale(sens_frame, from_=0.01, to=0.5, orient=tk.HORIZONTAL, length=150)
        self.scale_sens_x.set(SENS_X)
        self.scale_sens_x.pack(side=tk.LEFT, padx=5)
        self.lbl_sens_x = ttk.Label(sens_frame, text=f"{SENS_X:.2f}")
        self.lbl_sens_x.pack(side=tk.LEFT)
        
        sens_frame2 = ttk.Frame(config_frame)
        sens_frame2.pack(fill=tk.X, pady=5)
        
        ttk.Label(sens_frame2, text="Sensibilidade Y:").pack(side=tk.LEFT)
        self.scale_sens_y = ttk.Scale(sens_frame2, from_=0.01, to=0.5, orient=tk.HORIZONTAL, length=150)
        self.scale_sens_y.set(SENS_Y)
        self.scale_sens_y.pack(side=tk.LEFT, padx=5)
        self.lbl_sens_y = ttk.Label(sens_frame2, text=f"{SENS_Y:.2f}")
        self.lbl_sens_y.pack(side=tk.LEFT)
        
        # Log
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.txt_log = tk.Text(log_frame, height=15, state=tk.DISABLED, font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        
        # Atualiza UI
        self.update_ui()
    
    def on_strict_changed(self):
        state["block_external"] = self.var_strict.get()
        log(f"Bloqueio externo: {'ativado' if state['block_external'] else 'desativado'}")
    
    def update_ui(self):
        global SENS_X, SENS_Y
        
        # Status
        if state["emulation"]:
            self.lbl_status.config(text="✅ Ativado", foreground="green")
        else:
            self.lbl_status.config(text="❌ Desativado", foreground="red")
        
        # Mouse
        if state["mouse_captured"]:
            rect = state["capture_rect"]
            if rect:
                self.lbl_mouse.config(text=f"🖱️ Mouse: CAPTURADO [{rect[2]-rect[0]}x{rect[3]-rect[1]}]", foreground="blue")
            else:
                self.lbl_mouse.config(text="🖱️ Mouse: CAPTURADO", foreground="blue")
        else:
            self.lbl_mouse.config(text="🖱️ Mouse: Livre", foreground="gray")
        
        # Sensibilidade
        SENS_X = self.scale_sens_x.get()
        SENS_Y = self.scale_sens_y.get()
        self.lbl_sens_x.config(text=f"{SENS_X:.2f}")
        self.lbl_sens_y.config(text=f"{SENS_Y:.2f}")
        
        # Log
        with log_lock:
            log_text = "\n".join(log_lines[-20:])
        
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.insert("1.0", log_text)
        self.txt_log.config(state=tk.DISABLED)
        
        self.root.after(100, self.update_ui)

# ------------------------------------------------------------------ main
def main():
    global gamepad, _last_mouse, buttons
    
    log("Iniciando emulador...")
    
    # Cria controle virtual
    try:
        gamepad = vg.VX360Gamepad()
        log("✓ Controle virtual Xbox 360 criado")
    except Exception as e:
        log(f"ERRO: {e}")
        return
    
    # Inicia thread de atualização do right stick
    rs_thread = threading.Thread(target=update_rs, daemon=True)
    rs_thread.start()
    log("✓ Thread de right stick iniciada")
    
    # Listeners
    kb_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)
    kb_listener.start()
    log("✓ Listener de teclado iniciado")
    
    mouse_listener = mouse.Listener(
        on_move=on_mouse_move_abs,
        on_click=on_mouse_click,
        on_scroll=on_mouse_scroll
    )
    mouse_listener.start()
    log("✓ Listener de mouse iniciado")
    
    # GUI
    root = tk.Tk()
    app = App(root)
    
    log("✓ GUI iniciada")
    log("Pressione F12 para ativar/desativar")
    
    try:
        root.mainloop()
    finally:
        stop_mouse_capture()
        kb_listener.stop()
        mouse_listener.stop()

if __name__ == "__main__":
    main()
