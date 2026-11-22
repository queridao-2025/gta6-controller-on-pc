# -*- coding: utf-8 -*-
"""
GTA 6 / FiveM — Controle virtual Xbox 360 via teclado + mouse
Substituto do reWASD: lemos teclado/mouse com pynput e emitimos um
controle virtual Xbox 360 com ViGEmBus (vgamepad).

Uso:
    python gta6-controller.py

MODO A PE (padrão):
    W/A/S/D       = andar (LS)
    Espaco        = A (pular)
    F             = Y (entrar/sair do carro)
    E             = D-Pad Dir (interagir)
    R             = X (recarregar)
    G             = X (quebrar janela)
    Q             = RB (cobertura)
    C             = LB (roda de armas)
    B             = B (soco)
    LShift        = L3 (correr)
    Z             = R3 (agachar/rolar)
    CapsLock      = LT (mirar)
    Esc           = Menu (pause)
    O             = Menu (pause)
    P             = Back (mapa)
    Enter         = A (pular/selecionar)
    Backspace     = B (voltar/fechar)
    F1            = Guide
    F2            = Back (View)
    Home          = Guide
    Insert        = Back (View)
    1/2/3/4       = D-Pad Up/Down/Esq/Dir
    LCtrl         = precisão (mouse mais lento)
    LWin          = liga/desliga emulação
    F12           = alterna modo a pe / no carro
    V             = RT ~25% (meia aceleração)

MODO NO CARRO (F12 para ativar):
    W / Seta Cima  = acelerar (RT)
    S / Seta Baixo = frear/ré (LT)
    A/D/Setas Esq/Dir = esterçar (LS)
    Espaco         = A (freio de mão)
    F              = Y (sair do carro)
    Ctrl Dir       = RB (freio de mão)
    E              = D-Pad Dir (interagir)
    Q              = RB (cobertura)
    C              = LB (roda de armas)
    V              = RT ~25% (meia aceleração)
    LCtrl          = precisão
    LWin           = toggle emulação
    F12            = voltar para modo a pe

Mouse (ambos modos):
    movimento     = analógico direito (câmera)
    LMB           = RT (atirar/acelerar)
    RMB (segurar) = LT (mirar/frear) + mira (mouse mais lento)
    MMB           = B (soco)
    MB4           = A (pular)
    MB5           = RB (cobertura)
    wheel up/down = LB (roda de armas)
"""

import time
import threading

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
    print("[ERRO] vgamepad não instalado. Rode: pip install vgamepad")
    raise

try:
    from pynput import keyboard, mouse
except ImportError:
    print("[ERRO] pynput não instalado. Rode: pip install pynput")
    raise

# ------------------------------------------------------------------ estado
state = {
    "emulation": True,
    "mode": "on_foot",   # "on_foot" ou "driving"
    "precision": False,
    "aim": False,
}

buttons = {
    "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "L3": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "R3": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
    "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "GUIDE": vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
    "DPAD_UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "DPAD_DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "DPAD_LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "DPAD_RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}

KEY_MAP = {
    "space": "A",
    "b": "B",
    "r": "X",
    "g": "X",
    "f": "Y",
    "q": "RB",
    "c": "LB",
    "z": "R3",
    "esc": "START",
    "o": "START",
    "p": "BACK",
    "enter": "A",
    "backspace": "B",
    "f1": "GUIDE",
    "f2": "BACK",
    "home": "GUIDE",
    "insert": "BACK",
    "1": "DPAD_UP",
    "2": "DPAD_DOWN",
    "3": "DPAD_LEFT",
    "4": "DPAD_RIGHT",
    "e": "DPAD_RIGHT",
    "t": "DPAD_RIGHT",
}

MOVE_KEYS = {"w", "a", "s", "d"}
DRIVE_KEYS = {"up", "down", "left", "right"}

pressed = set()
mouse_vel = {"x": 0.0, "y": 0.0}
mouse_lock = threading.Lock()
rs_value = {"x": 0.0, "y": 0.0}
_last_mouse = {"x": None, "y": None}
gamepad = None

# Carro: estado de aceleração/freio/esterço
car_accel = 0.0
car_brake = 0.0
car_steer = 0.0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def curve(v):
    if CURVE == "exponential":
        return v * abs(v)
    return v


def update_rs():
    global rs_value
    while True:
        with mouse_lock:
            vx = mouse_vel["x"]
            vy = mouse_vel["y"]
        vx *= 0.7
        vy *= 0.7
        with mouse_lock:
            mouse_vel["x"] = vx
            mouse_vel["y"] = vy

        mult = 1.0
        if state["precision"]:
            mult *= PRECISION_MULT
        if state["aim"]:
            mult *= AIM_MULT
        vx2 = clamp(vx * SENS_X * mult, -MAX_VEL, MAX_VEL)
        vy2 = clamp(vy * SENS_Y * mult, -MAX_VEL, MAX_VEL)

        if abs(vx2) < DEADZONE_RS:
            vx2 = 0.0
        if abs(vy2) < DEADZONE_RS:
            vy2 = 0.0

        vx2 = curve(vx2)
        vy2 = curve(vy2)

        rs_value["x"] = rs_value["x"] * SMOOTHING + vx2 * (1 - SMOOTHING)
        rs_value["y"] = rs_value["y"] * SMOOTHING + vy2 * (1 - SMOOTHING)

        if gamepad is not None and state["emulation"]:
            gamepad.right_joystick_float(
                x_value_float=clamp(rs_value["x"], -1.0, 1.0),
                y_value_float=clamp(rs_value["y"], -1.0, 1.0),
            )
            gamepad.update()

        time.sleep(1.0 / 60.0)


def set_button(name, pressed):
    if gamepad is None or not state["emulation"]:
        return
    btn = buttons[name]
    if pressed:
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


def normalize_key(key):
    try:
        if key.char is not None:
            return key.char.lower()
    except AttributeError:
        pass
    try:
        return str(key).replace("Key.", "").lower()
    except Exception:
        return None


def on_key_press(key):
    global pressed, state, car_accel, car_brake, car_steer
    k = normalize_key(key)
    if k is None:
        return

    # toggle emulação (LWin / Cmd)
    if k in ("cmd", "cmd_l", "cmd_r", "left_windows", "right_windows"):
        state["emulation"] = not state["emulation"]
        print("[emulacao] " + ("ON" if state["emulation"] else "OFF"))
        return

    # toggle modo a pe / no carro
    if k == TOGGLE_KEY:
        state["mode"] = "driving" if state["mode"] == "on_foot" else "on_foot"
        print("=" * 40)
        print("  MODO: " + state["mode"].upper())
        print("=" * 40)
        return

    pressed.add(k)

    # precisão (LCtrl)
    if k in ("ctrl_l", "ctrl", "left_ctrl"):
        state["precision"] = True

    if not state["emulation"]:
        return

    # ===== MODO NO CARRO =====
    if state["mode"] == "driving":
        # W = acelerar, S = frear/ré
        if k in ("w", "up"):
            car_accel = 1.0
            set_trigger("RT", 1.0)
            print("[carro] acelerar RT=1.0")
        if k in ("s", "down"):
            car_brake = 1.0
            set_trigger("LT", 1.0)
            print("[carro] frear LT=1.0")
        # A/D/Setas Esq/Dir = esterçar
        if k in ("a", "left"):
            car_steer = -1.0
        if k in ("d", "right"):
            car_steer = 1.0
        if k in ("a", "d", "left", "right"):
            set_left_stick(car_steer, 0.0)
            print("[carro] estercar LS=" + str(car_steer))
        # freio de mão
        if k == "space":
            set_button("A", True)
        # meia aceleração
        if k == "v":
            set_trigger("RT", HALF_THROTTLE)
            print("[carro] meia acel RT=" + str(HALF_THROTTLE))
        # mapeamentos diretos
        if k in KEY_MAP:
            set_button(KEY_MAP[k], True)
        return

    # ===== MODO A PE =====
    # movimento WASD -> LS
    if k in MOVE_KEYS:
        x = 0.0; y = 0.0
        if "a" in pressed: x -= 1.0
        if "d" in pressed: x += 1.0
        if "w" in pressed: y += 1.0
        if "s" in pressed: y -= 1.0
        set_left_stick(x, y)

    # meia aceleração (V) — em qualquer modo
    if k == "v":
        set_trigger("RT", HALF_THROTTLE)

    # mapeamentos diretos (camada 0)
    if k in KEY_MAP:
        set_button(KEY_MAP[k], True)


def on_key_release(key):
    global pressed, state, car_accel, car_brake, car_steer
    k = normalize_key(key)
    if k is None:
        return

    if k in pressed:
        pressed.discard(k)

    # precisão
    if k in ("ctrl_l", "ctrl", "left_ctrl"):
        state["precision"] = False

    if not state["emulation"]:
        return

    # ===== MODO NO CARRO =====
    if state["mode"] == "driving":
        if k in ("w", "up"):
            car_accel = 0.0
            set_trigger("RT", 0.0)
        if k in ("s", "down"):
            car_brake = 0.0
            set_trigger("LT", 0.0)
        if k in ("a", "left"):
            car_steer = 0.0 if "d" not in pressed and "right" not in pressed else -1.0
        if k in ("d", "right"):
            car_steer = 0.0 if "a" not in pressed and "left" not in pressed else 1.0
        if k in ("a", "d", "left", "right"):
            # recalcular steer
            x = 0.0
            if "a" in pressed or "left" in pressed: x -= 1.0
            if "d" in pressed or "right" in pressed: x += 1.0
            set_left_stick(x, 0.0)
        if k == "space":
            set_button("A", False)
        if k == "v":
            set_trigger("RT", 0.0)
        if k in KEY_MAP:
            set_button(KEY_MAP[k], False)
        return

    # ===== MODO A PE =====
    if k in MOVE_KEYS:
        x = 0.0; y = 0.0
        if "a" in pressed: x -= 1.0
        if "d" in pressed: x += 1.0
        if "w" in pressed: y += 1.0
        if "s" in pressed: y -= 1.0
        set_left_stick(x, y)

    if k == "v":
        set_trigger("RT", 0.0)

    if k in KEY_MAP:
        set_button(KEY_MAP[k], False)


def _is_game_window_active():
    """Verifica se a janela ativa eh o Xbox/Remote Play ou Veyra (via ctypes)."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()
        keywords = ["xbox", "remote play", "veyra", "gta", "remote", "game bar"]
        result = any(kw in title for kw in keywords)
        if not result:
            print("[debug] janela ativa: '" + title + "' (nao eh jogo)")
        return result
    except Exception as e:
        print("[debug] erro ao verificar janela: " + str(e))
        return True


def on_mouse_move_abs(x, y):
    global _last_mouse
    if _last_mouse is None or _last_mouse.get("x") is None:
        _last_mouse = {"x": x, "y": y}
        return
    dx = x - _last_mouse["x"]
    dy = y - _last_mouse["y"]
    _last_mouse["x"] = x
    _last_mouse["y"] = y
    if not state["emulation"]:
        return
    if not _is_game_window_active():
        return
    with mouse_lock:
        mouse_vel["x"] += dx
        mouse_vel["y"] += dy


def on_mouse_click(x, y, button, pressed_flag):
    if not state["emulation"]:
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
    if not state["emulation"]:
        return
    if dy > 0:
        set_button("LB", True)
        time.sleep(0.05)
        set_button("LB", False)
    elif dy < 0:
        set_button("LB", True)
        time.sleep(0.05)
        set_button("LB", False)


def main():
    global gamepad, _last_mouse
    gamepad = vg.VX360Gamepad()
    _last_mouse = {"x": None, "y": None}

    print("=" * 60)
    print("GTA6 controller ativo. Emulação ON.")
    print("Modo: A PE (padrão)")
    print("")
    print("  >>> IMPORTANTE: para dirigir, entre no carro e aperte F12 <<<")
    print("  >>> F12 alterna entre modo A PE e modo NO CARRO <<<")
    print("")
    print("  No carro: W ou Seta Cima = acelerar, S ou Seta Baixo = frear")
    print("  A/D ou Setas Esq/Dir = esterçar")
    print("  Espaco = freio de mão, F = sair do carro")
    print("")
    print("F12 = alterna modo a pe / no carro")
    print("LWin = liga/desliga emulação")
    print("Ctrl+C para sair.")
    print("=" * 60)

    threading.Thread(target=update_rs, daemon=True).start()

    kb_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)
    mouse_listener = mouse.Listener(
        on_move=on_mouse_move_abs,
        on_click=on_mouse_click,
        on_scroll=on_mouse_scroll,
    )
    kb_listener.start()
    mouse_listener.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nSaindo.")
        kb_listener.stop()
        mouse_listener.stop()


if __name__ == "__main__":
    main()
