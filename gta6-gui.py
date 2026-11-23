# -*- coding: utf-8 -*-
"""
Xbox Virtual Controller — FiveM Roleplay / GTA V
=================================================
Teclado + mouse  ->  controle Xbox 360 virtual (ViGEmBus).

Requisitos:  pip install vgamepad pynput     (e o driver ViGEmBus instalado)

  F8 ou Scroll Lock ... liga/desliga a emulação
  Pause ........................ mouse livre (usar menus/inventário do RP)
  F12 .......................... alterna a pé / no carro   (também no painel)
  Ctrl direito ................. liga/desliga o caminhar
  T ou /  ...................... pausa o teclado enquanto digita no chat
  Enter ou Esc ................. volta do chat

Princípio do perfil "FiveM Roleplay": cada tecla do PC vira o botão Xbox que
dispara o MESMO controle do GTA V. Teclas que os scripts de RP usam (F1-F10,
números, K, L, U, J, X...) NÃO viram botão do controle, para não duplicar
ações (ex.: Backspace virar "B" e dar soco). Elas continuam passando como
teclado normal.
"""

import atexit
import copy
import ctypes
import ctypes.wintypes as wt
import heapq
import inspect
import itertools
import json
import math
import os
import sys
import threading
import time
from collections import deque

import tkinter as tk
from tkinter import ttk

try:
    import vgamepad as vg
except Exception:            # tratado em main()
    vg = None

try:
    from pynput import keyboard, mouse
except Exception:            # tratado em main()
    keyboard = mouse = None

APP_TITLE = "Xbox Virtual Controller — FiveM RP"
APP_TITLE_LOWER = APP_TITLE.lower()

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()
CONFIG_PATH = os.path.join(_HERE, "gta6-gui.config.json")

# ====================================================================== Win32
IS_WINDOWS = os.name == "nt"
_user32 = None
if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _user32.GetForegroundWindow.restype = wt.HWND
    _user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    _user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    _user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    _user32.ClipCursor.argtypes = [ctypes.POINTER(wt.RECT)]
    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    try:                                  # coordenadas físicas (pynput == ClipCursor)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass


class _CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD),
                ("hCursor", wt.HANDLE), ("ptScreenPos", wt.POINT)]


def screen_rect():
    if _user32 is None:
        return (0, 0, 1920, 1080)
    return (0, 0, _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1))


def _exe_name(hwnd):
    """Nome do executável dono da janela (ex.: 'fivem_b3258_gtaprocess.exe')."""
    if _user32 is None:
        return ""
    try:
        pid = wt.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wt.HANDLE
        k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k32.CloseHandle.argtypes = [wt.HANDLE]
        h = k32.OpenProcess(0x1000, False, pid.value)      # QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = wt.DWORD(520)
            k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                       ctypes.POINTER(wt.DWORD)]
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            k32.CloseHandle(h)
    except Exception:
        pass
    return ""


def fg_window():
    """(hwnd, título, executável) da janela em primeiro plano, em minúsculas."""
    if _user32 is None:
        return 0, "", ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return 0, "", ""
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(hwnd, buf, 256)
    return hwnd, buf.value.lower(), _exe_name(hwnd)


def client_rect(hwnd):
    """Área útil (sem bordas) da janela, em coordenadas de tela."""
    if _user32 is None or not hwnd:
        return screen_rect()
    rc = wt.RECT()
    pt = wt.POINT(0, 0)
    if not _user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return screen_rect()
    _user32.ClientToScreen(hwnd, ctypes.byref(pt))
    rect = (pt.x, pt.y, pt.x + rc.right, pt.y + rc.bottom)
    if (rect[2] - rect[0]) < 200 or (rect[3] - rect[1]) < 200:
        return screen_rect()
    return rect

# ====================================================================== Cursor
def clip_cursor(rect):
    """Confina o cursor à janela (usado pelo start_capture)"""
    if _user32 is None:
        return
    r = wt.RECT(rect[0], rect[1], rect[2], rect[3])
    _user32.ClipCursor(ctypes.byref(r))


def unclip_cursor():
    if _user32 is not None:
        _user32.ClipCursor(None)


def set_cursor(x, y):
    if _user32 is not None:
        _user32.SetCursorPos(int(x), int(y))


# Guarda o cursor original para restaurar depois
_SAVED_CURSORS = {}  # id -> cursor original
_EMPTY_CURSOR = None

def _create_empty_cursor():
    """Cria um cursor 1x1 totalmente transparente via CreateIconIndirect."""
    global _EMPTY_CURSOR
    if _EMPTY_CURSOR is not None:
        return _EMPTY_CURSOR
    if _user32 is None:
        return None

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                    ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                    ("bmPlanes", ctypes.c_uint16), ("bmBitsPixel", ctypes.c_uint16),
                    ("bmBits", ctypes.c_void_p)]

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD),
                    ("yHotspot", wt.DWORD), ("hbmMask", wt.HBITMAP),
                    ("hbmColor", wt.HBITMAP)]

    try:
        _gdi32 = ctypes.windll.gdi32
        # Cria bitmap AND mask 1x1 (todo transparente = 0xFFFFFFFF)
        hbm_mask = _gdi32.CreateBitmap(1, 1, 1, 1, ctypes.byref(
            (ctypes.c_uint32 * 1)(0xFFFFFFFF)))
        if not hbm_mask:
            return None

        ii = ICONINFO()
        ii.fIcon = False
        ii.xHotspot = 0
        ii.yHotspot = 0
        ii.hbmMask = hbm_mask
        ii.hbmColor = None  # sem cor = cursor monocromático

        hcur = _user32.CreateIconIndirect(ctypes.byref(ii))
        _gdi32.DeleteObject(hbm_mask)
        _EMPTY_CURSOR = hcur
        return hcur
    except Exception:
        return None


# IDs dos cursores do sistema que precisamos substituir
_OCR_NORMAL = 32512      # seta normal
_OCR_IBEAM = 32513       # cursor de texto
_OCR_WAIT = 32514        # ampulheta
_OCR_CROSS = 32515       # cruz
_OCR_UP = 32516          # seta vertical
_OCR_SIZENWSE = 32642    # diagonal
_OCR_SIZENESW = 32643    # diagonal
_OCR_SIZEWE = 32644      # horizontal
_OCR_SIZENS = 32645      # vertical
_OCR_SIZEALL = 32646     # mover
_OCR_NO = 32648          # proibido
_OCR_HAND = 32649        # mão
_OCR_APPSTARTING = 32650 # seta com ampulheta

_ALL_OCR_IDS = [_OCR_NORMAL, _OCR_IBEAM, _OCR_WAIT, _OCR_CROSS,
                _OCR_UP, _OCR_SIZENWSE, _OCR_SIZENESW, _OCR_SIZEWE,
                _OCR_SIZENS, _OCR_SIZEALL, _OCR_NO, _OCR_HAND, _OCR_APPSTARTING]

def hide_cursor():
    """Esconde o cursor GLOBALMENTE usando SetSystemCursor com cursor vazio.
    Afeta TODAS as janelas (incluindo Remote Play)."""
    if _user32 is None:
        return
    empty = _create_empty_cursor()
    if empty is None:
        # Fallback: ShowCursor
        _user32.ShowCursor(False)
        return
    for ocr_id in _ALL_OCR_IDS:
        # Salva o original na primeira vez
        if ocr_id not in _SAVED_CURSORS:
            orig = _user32.LoadCursorW(None, ctypes.c_wchar_p(ocr_id))
            if orig:
                _SAVED_CURSORS[ocr_id] = orig
        # Substitui pelo cursor vazio
        _user32.SetSystemCursor(empty, ocr_id)
    log("[cursor] escondido (SetSystemCursor)")


def show_cursor():
    """Restaura os cursores padrão do Windows."""
    if _user32 is None:
        return
    # Restaura cada cursor salvo
    for ocr_id, orig in _SAVED_CURSORS.items():
        _user32.SetSystemCursor(orig, ocr_id)
    _SAVED_CURSORS.clear()
    # Garante que o contador ShowCursor está correto
    _user32.ShowCursor(True)
    log("[cursor] restaurado")

class CursorConfiner:
    """Monitora e mantém o cursor confinado continuamente.
    Reaplica ClipCursor se o Remote Play liberar o confinamento."""
    
    def __init__(self, engine_ref):
        self.engine = engine_ref
        self.running = False
        self.thread = None
        self._check_interval = 0.016  # 16ms = ~60Hz

    def start(self):
        """Inicia o monitoramento contínuo"""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        log("[cursor] monitoramento de confinamento iniciado")

    def stop(self):
        """Para o monitoramento"""
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        log("[cursor] monitoramento parado")

    def _monitor_loop(self):
        """Loop que verifica e reaplica o confinamento continuamente"""
        while self.running:
            try:
                # Só monitora se o mouse deve estar capturado
                if (state["mouse_captured"] and 
                    state.get("capture_rect") and 
                    state["emulation"] and 
                    not self.engine.menu_active()):
                    
                    expected_rect = state["capture_rect"]
                    
                    # Verifica se o confinamento ainda está ativo
                    current = wt.RECT()
                    if not _user32.GetClipCursor(ctypes.byref(current)):
                        # Confinamento foi liberado - reaplica
                        r = wt.RECT(
                            expected_rect[0], expected_rect[1],
                            expected_rect[2], expected_rect[3]
                        )
                        _user32.ClipCursor(ctypes.byref(r))
                    else:
                        # Verifica se o retângulo está correto
                        if (current.left != expected_rect[0] or
                            current.top != expected_rect[1] or
                            current.right != expected_rect[2] or
                            current.bottom != expected_rect[3]):
                            # Retângulo incorreto - reaplica
                            r = wt.RECT(
                                expected_rect[0], expected_rect[1],
                                expected_rect[2], expected_rect[3]
                            )
                            _user32.ClipCursor(ctypes.byref(r))
                    
                    # Re-esconde cursor se o Remote Play o restaurou
                    # Verifica a cada ~1s para não sobrecarregar
                    self._cursor_rehide_timer = getattr(self, '_cursor_rehide_timer', 0) + 1
                    if self._cursor_rehide_timer >= 60:  # ~1s a 60Hz
                        self._cursor_rehide_timer = 0
                        # Verifica se o cursor normal voltou
                        ci = _CURSORINFO()
                        ci.cbSize = ctypes.sizeof(ci)
                        if _user32.GetCursorInfo(ctypes.byref(ci)):
                            # Se o cursor não é o vazio, reaplica
                            if ci.hCursor != _EMPTY_CURSOR:
                                empty = _create_empty_cursor()
                                if empty:
                                    for ocr_id in _ALL_OCR_IDS:
                                        if ocr_id not in _SAVED_CURSORS:
                                            orig = _user32.LoadCursorW(None, ctypes.c_wchar_p(ocr_id))
                                            if orig:
                                                _SAVED_CURSORS[ocr_id] = orig
                                        _user32.SetSystemCursor(empty, ocr_id)
                
                time.sleep(self._check_interval)
                
            except Exception as e:
                # Silenciosamente ignora erros (evita spam no log)
                time.sleep(0.1)

def cursor_showing():
    """True se o cursor do sistema está visível (menus com mouse)."""
    if _user32 is None:
        return False
    ci = _CURSORINFO()
    ci.cbSize = ctypes.sizeof(ci)
    if _user32.GetCursorInfo(ctypes.byref(ci)):
        return bool(ci.flags & 1)
    return False


atexit.register(unclip_cursor)

# ================================================================ configuração
DEFAULTS = {
    # câmera (mouse -> analógico direito)
    "SENS_X": 0.22, "SENS_Y": 0.20,
    "DEADZONE_RS": 0.06, "ANTI_DZ": 0.10,
    "FRICTION": 0.85, "SMOOTHING": 0.25, "SMOOTHING_MAX_TAU_MS": 50.0,
    "RESPONSE": "progressive", "AIM_RESPONSE": "aim",
    "PRECISION_MULT": 0.35, "AIM_MULT": 0.45,
    "INVERT_Y": False,
    # modo direto (posição do mouse = posição do stick, sem suavização/decai)
    # Ideal para lockpick: o RS fica onde você deixa, sem voltar ao centro.
    "DIRECT_MODE": True,
    "DIRECT_SENS_X": 0.008,
    "DIRECT_SENS_Y": 0.008,
    "DIRECT_DEADZONE": 0.02,
    # roda (armas / rádio) e andar
    "WHEEL_RADIUS": 140.0, "WALK_SCALE": 0.50,
    "SPRINT_HZ": 9.0, "TAP_MS": 60.0,
    # veículo
    "HALF_THROTTLE": 0.25, "PEDAL_RAMP": 4.0, "STEER_RAMP": 4.0,
    # comportamento
    "profile": "fivem_rp",
    "require_focus": True, "smart_capture": True,
    "typing_pause": True, "auto_mode_f": False, "auto_menu_cursor": False,
    "game_patterns": "gta, grand theft, fivem, cfx",
    "overrides": {},
}
SAVE_KEYS = [k for k in DEFAULTS if k != "overrides"]
S = copy.deepcopy(DEFAULTS)

SETTLE = 0.003                       # abaixo disso o stick vai a zero
MOUSE_WINDOW_MS = 32.0               # janela de acumulação (ms) — maior = mais suave
EMU_TOGGLE_KEYS = ("cmd", "cmd_l", "cmd_r", "scroll_lock", "f8")
MENU_TOGGLE_KEYS = ("pause",)
TYPING_OPEN_KEYS = ("t", "/")
TYPING_CLOSE_KEYS = ("enter", "esc")
# janelas que podem ter "GTA" no título (aba de navegador etc.) mas não são o jogo
NOT_GAME_EXES = ("chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe",
                 "vivaldi.exe", "discord.exe", "code.exe", "explorer.exe", "notepad.exe",
                 "notepad++.exe", "obs64.exe", "spotify.exe", "cmd.exe", "powershell.exe",
                 "windowsterminal.exe", "python.exe", "pythonw.exe")

state = {
    "emulation": True,
    "menu_mode": False,       # alternado manualmente (Pause)
    "menu_auto": False,       # detectado pelo cursor visível
    "typing": False,
    "mode": "foot",           # "foot" | "car"
    "walk": False,
    "mouse_captured": False,
    "capture_rect": None,
    "game_focus": False,
    "fg_title": "",
}
pressed = set()              # teclas físicas pressionadas (para a GUI)
log_lines = []
log_lock = threading.Lock()
log_version = [0]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def log(msg):
    with log_lock:
        timestamp = time.strftime("%H:%M:%S ")
        log_lines.append(timestamp + msg)
        if len(log_lines) > 60:
            log_lines.pop(0)
        log_version[0] += 1
        # Salva no arquivo
        try:
            with open("C:/GTA6Controller/emulator.log", "a", encoding="utf-8") as f:
                f.write(timestamp + msg + "\n")
        except:
            pass


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    for k, v in data.get("settings", {}).items():
        if k in SAVE_KEYS and isinstance(v, type(DEFAULTS[k])):
            S[k] = v
        elif k in SAVE_KEYS and isinstance(DEFAULTS[k], float) and isinstance(v, int):
            S[k] = float(v)
    ov = data.get("overrides", {})
    if isinstance(ov, dict):
        S["overrides"] = ov
    if S["profile"] not in PROFILES:
        S["profile"] = "fivem_rp"


def save_config():
    try:
        data = {"settings": {k: S[k] for k in SAVE_KEYS}, "overrides": S["overrides"]}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"[config] não foi possível salvar: {e}")
        return False


# ==================================================================== ações
BUTTONS = ["A", "B", "X", "Y", "LB", "RB", "L3", "R3", "START", "BACK", "GUIDE",
           "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"]
_BTN_TEXT = {
    "A": "Botão A", "B": "Botão B", "X": "Botão X", "Y": "Botão Y",
    "LB": "LB (ombro esquerdo)", "RB": "RB (ombro direito)",
    "L3": "L3 (clique no analógico esq.)", "R3": "R3 (clique no analógico dir.)",
    "START": "Menu (Start)", "BACK": "View (Back)", "GUIDE": "Guia Xbox",
    "DPAD_UP": "D-Pad ↑", "DPAD_DOWN": "D-Pad ↓",
    "DPAD_LEFT": "D-Pad ←", "DPAD_RIGHT": "D-Pad →",
}
_BTN_SHORT = {"START": "Menu", "BACK": "View", "GUIDE": "Guia",
              "DPAD_UP": "D↑", "DPAD_DOWN": "D↓", "DPAD_LEFT": "D←", "DPAD_RIGHT": "D→"}

LS_ACTIONS = {"LS_UP": (0, 1), "LS_DOWN": (0, -1), "LS_LEFT": (-1, 0), "LS_RIGHT": (1, 0)}
RAMP_ACTIONS = ("ACCEL", "ACCEL_HALF", "BRAKE")
EVENT_ACTIONS = {"@WALK", "@MODE", "@MENU", "@GRENADE"}   # disparam ao apertar

ACTION_INFO = {"": ("— nenhum —", "")}
for _b in BUTTONS:
    ACTION_INFO[_b] = (_BTN_TEXT[_b], _BTN_SHORT.get(_b, _b))
ACTION_INFO["LT"] = ("LT (gatilho esquerdo)", "LT")
ACTION_INFO["RT"] = ("RT (gatilho direito)", "RT")
ACTION_INFO["LS_UP"] = ("Analógico esq. ↑ (andar p/ frente)", "Andar↑")
ACTION_INFO["LS_DOWN"] = ("Analógico esq. ↓ (andar p/ trás)", "Andar↓")
ACTION_INFO["LS_LEFT"] = ("Analógico esq. ← (andar / esterçar)", "Andar←")
ACTION_INFO["LS_RIGHT"] = ("Analógico esq. → (andar / esterçar)", "Andar→")
ACTION_INFO["ACCEL"] = ("Acelerar (com rampa)", "Acel.")
ACTION_INFO["ACCEL_HALF"] = ("Acelerar leve (RT parcial)", "Acel.½")
ACTION_INFO["BRAKE"] = ("Frear / ré (com rampa)", "Freio")
for _b in BUTTONS + ["LT", "RT"]:
    ACTION_INFO["tap:" + _b] = ("Toque rápido: " + ACTION_INFO[_b][0], "t:" + ACTION_INFO[_b][1])
ACTION_INFO["@SPRINT"] = ("Correr (A repetido enquanto segura)", "Correr")
ACTION_INFO["@GRENADE"] = ("Granada (LT + D-Pad ←)", "Granada")
ACTION_INFO["@WALK"] = ("Caminhar (liga/desliga)", "Caminhar")
ACTION_INFO["@MODE"] = ("Alternar a pé / no carro", "Modo")
ACTION_INFO["@PRECISION"] = ("Mouse lento (segurar)", "Precisão")
ACTION_INFO["@MENU"] = ("Mouse livre para menus (liga/desliga)", "Menu")

ACTION_ORDER = (
    [""] + BUTTONS + ["LT", "RT"] + list(LS_ACTIONS) + list(RAMP_ACTIONS)
    + ["tap:" + b for b in BUTTONS + ["LT", "RT"]]
    + ["@SPRINT", "@GRENADE", "@WALK", "@MODE", "@PRECISION", "@MENU"]
)


def action_label(code):
    return ACTION_INFO.get(code, (code, code))[0]


def action_short(code):
    return ACTION_INFO.get(code, (code, code))[1]


def action_category(code):
    if not code:
        return "none"
    if code.startswith("tap:"):
        return action_category(code[4:])
    if code.startswith("@"):
        return "macro"
    if code in LS_ACTIONS:
        return "move"
    if code.startswith("DPAD"):
        return "dpad"
    if code in ("LT", "RT", "LB", "RB") or code in RAMP_ACTIONS:
        return "trigger"
    return "button"


# ==================================================================== perfis
def _merge(base, extra):
    d = dict(base)
    d.update(extra)
    return d


# ---- FiveM RP: só o que existe no GTA V; teclas de RP ficam livres ----------
_RP_FOOT = {
    "w": "LS_UP", "a": "LS_LEFT", "s": "LS_DOWN", "d": "LS_RIGHT",
    "shift_l": "@SPRINT", "shift_r": "@SPRINT",
    "space": "X",            # pular
    "f": "Y",                # entrar no veículo
    "ctrl_l": "L3",          # furtivo / agachar
    "c": "R3",               # olhar para trás
    "tab": "LB",             # roda de armas (segurar)
    "q": "RB",               # cobertura
    "r": "B",                # recarregar / soco leve
    "e": "DPAD_RIGHT",       # ação contextual
    "v": "BACK",             # trocar câmera
    "ctrl_r": "@WALK", "alt_l": "@PRECISION", "f12": "@MODE",
}
_RP_CAR = {
    "w": "ACCEL", "s": "BRAKE", "a": "LS_LEFT", "d": "LS_RIGHT",
    "shift_l": "ACCEL_HALF", "shift_r": "ACCEL_HALF",
    "space": "RB",           # freio de mão
    "f": "Y",                # sair do veículo
    "e": "L3",               # buzina
    "h": "DPAD_RIGHT",       # faróis
    "q": "DPAD_LEFT",        # roda do rádio (segurar)
    "r": "B",                # câmera cinematográfica
    "x": "A",                # abaixar no carro
    "c": "R3",               # olhar para trás
    "v": "BACK",
    "alt_l": "@PRECISION", "f12": "@MODE",
}
_RP_MOUSE_FOOT = {
    "left": "RT", "right": "LT", "middle": "DPAD_UP",
    "x1": "@SPRINT", "x2": "RB",
    "wheel_up": "tap:DPAD_RIGHT", "wheel_down": "tap:DPAD_LEFT",
}
_RP_MOUSE_CAR = {
    "left": "RB", "right": "LB", "middle": "DPAD_UP", "x1": "", "x2": "",
    "wheel_up": "tap:X", "wheel_down": "tap:DPAD_LEFT",
}

# ---- GTA VI (legado): mapeamento original, com os conflitos corrigidos ------
_G6_FOOT = {
    # Movimento (analógico esquerdo)
    "w": "LS_UP", "a": "LS_LEFT", "s": "LS_DOWN", "d": "LS_RIGHT",
    # Ações principais (conforme jogargta.com)
    "space": "A",           # pular (A)
    "z": "B",               # granada/alternativo
    "b": "X", "r": "X", "x": "X",   # X (interação)
    "f": "Y", "g": "Y",     # Y (entrar/sair veículo)
    "q": "RB",              # cobertura (RB)
    "c": "LB",              # roda de armas (LB)
    "h": "R3",              # analógico direito clique
    # Sistema
    "esc": "START", "o": "START",   # menu do sistema
    "p": "MENU",            # menu do jogo (MENU)
    "i": "BACK",            # voltar
    "enter": "A",           # confirmar (A)
    "backspace": "B",       # recarregar / voltar (B)
    "f1": "GUIDE", "f2": "BACK", "home": "GUIDE", "insert": "BACK",
    # Direcional
    "1": "DPAD_UP", "2": "DPAD_DOWN", "3": "DPAD_LEFT", "4": "DPAD_RIGHT",
    "e": "DPAD_RIGHT", "t": "DPAD_RIGHT",
    "up": "DPAD_UP", "down": "DPAD_DOWN", "left": "DPAD_LEFT", "right": "DPAD_RIGHT",
    "page_up": "DPAD_UP", "page_down": "DPAD_DOWN",
    # Analógico esquerdo (caminhar/correr)
    "shift": "L3", "shift_l": "L3", "shift_r": "L3", "rshift": "L3",   # caminhar
    "capslock": "LS",       # correr (Shift no site)
    "ctrl_l": "@PRECISION", "ctrl_r": "@PRECISION",   # precisão/mirar fino
    "v": "ACCEL_HALF",
    "tab": "@MODE", "f12": "@MODE",   # alternar a pé/carro
}
_G6_CAR = _merge(_G6_FOOT, {
    # Movimento do veículo (conforme jogargta.com)
    "w": "ACCEL", "s": "BRAKE", "a": "LS_LEFT", "d": "LS_RIGHT",
    "up": "ACCEL", "down": "BRAKE", "left": "LS_LEFT", "right": "LS_RIGHT",
    # Ações no carro
    "space": "RB",       # freio de mão (RB)
    "x": "X",            # alternar câmera/visão (X)
    # Sistema
    "enter": "A",        # confirmar (A)
    "backspace": "B",    # recarregar/voltar (B)
    "r": "B",            # recarregar/voltar (B)
    "f": "Y",            # entrar/sair veículo (Y)
    "p": "MENU",         # menu do jogo (MENU)
    "up": "UP",          # telefone (UP)
    "down": "DPAD_DOWN", # direcional baixo
    "left": "DPAD_LEFT", # direcional esquerdo
    "right": "DPAD_RIGHT", # direcional direito
})
_G6_MOUSE = {
    "left": "RT", "right": "RS", "middle": "LT", "x1": "LB", "x2": "RB",
    "wheel_up": "tap:LB", "wheel_down": "tap:RB",
}

PROFILES = {
    "fivem_rp": {
        "label": "FiveM Roleplay (GTA V)",
        "note": "mapeamento oficial FiveM RP / GTA V",
        "key": {"foot": _G6_FOOT, "car": _G6_CAR},
        "mouse": {"foot": _G6_MOUSE, "car": _G6_MOUSE},
    },
    "gta6": {
        "label": "GTA VI (v2 oficial)",
        "note": "mapeamento idêntico ao gta6_controller_v2",
        "key": {"foot": _G6_FOOT, "car": _G6_CAR},
        "mouse": {"foot": _G6_MOUSE, "car": _G6_MOUSE},
    },
}
PROFILE_BY_LABEL = {p["label"]: pid for pid, p in PROFILES.items()}


def get_action(kind, name, mode=None):
    """kind: 'key' | 'mouse'. Aplica as alterações feitas na GUI sobre o perfil."""
    mode = mode or state["mode"]
    pid = S["profile"] if S["profile"] in PROFILES else "fivem_rp"
    ov = S["overrides"].get(pid, {}).get(kind, {}).get(mode, {})
    if name in ov:
        return ov[name]
    return PROFILES[pid][kind][mode].get(name, "")


def set_override(kind, mode, name, action):
    pid = S["profile"]
    S["overrides"].setdefault(pid, {}).setdefault(kind, {}).setdefault(mode, {})[name] = action


def clear_overrides():
    S["overrides"].pop(S["profile"], None)


# ============================================================ teclado (nomes)
_KEY_CANON = {
    "shift": "shift_l", "shift_l": "shift_l", "shift_r": "shift_r",
    "ctrl": "ctrl_l", "ctrl_l": "ctrl_l", "ctrl_r": "ctrl_r",
    "alt": "alt_l", "alt_l": "alt_l", "alt_r": "alt_r", "alt_gr": "alt_r",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd_r",
}


_VK_SPECIAL = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc", 0x20: "space",
    0x21: "page_up", 0x22: "page_down", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2D: "insert", 0x2E: "delete", 0x5B: "cmd", 0x5C: "cmd_r",
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4", 0x74: "f5",
    0x75: "f6", 0x76: "f7", 0x77: "f8", 0x78: "f9", 0x79: "f10",
    0x7A: "f11", 0x7B: "f12", 0x90: "num_lock", 0x91: "scroll_lock",
    0x13: "pause", 0x14: "caps_lock", 0x10: "shift_l", 0x11: "ctrl_l",
    0x12: "alt_l", 0xA0: "shift_l", 0xA1: "shift_r", 0xA2: "ctrl_l",
    0xA3: "ctrl_r", 0xA4: "alt_l", 0xA5: "alt_r",
}
_VK_NUMPAD = {0x60+i: "num%d" % i for i in range(10)}

def normalize_key(key):
    """Nome estável da tecla. Letras/números usam o código virtual (corretos
    com Shift/Ctrl e em qualquer layout); teclas especiais usam o nome do
    pynput ou o vk. NUNCA retorna None para tecla física válida."""
    try:
        if keyboard is not None and isinstance(key, keyboard.KeyCode):
            vk = getattr(key, "vk", None)
            if vk is not None:
                if 0x41 <= vk <= 0x5A:
                    return chr(vk).lower()
                if 0x30 <= vk <= 0x39:
                    return chr(vk)
                if vk in _VK_NUMPAD:
                    return _VK_NUMPAD[vk]
                if vk in _VK_SPECIAL:
                    return _VK_SPECIAL[vk]
            ch = getattr(key, "char", None)
            if ch and ch.isprintable():
                return ch.lower()
            return None
        name = getattr(key, "name", None) or str(key).replace("Key.", "")
        name = name.lower()
        return _KEY_CANON.get(name, name)
    except Exception:
        return None


# ===================================================================== gamepad
class Scheduler(threading.Thread):
    """Executa toques/macros sem bloquear os listeners (substitui time.sleep)."""

    def __init__(self):
        super().__init__(daemon=True)
        self._cv = threading.Condition()
        self._heap = []
        self._seq = itertools.count()

    def call_later(self, delay, fn, *args):
        with self._cv:
            heapq.heappush(self._heap, (time.monotonic() + delay, next(self._seq), fn, args))
            self._cv.notify()

    def run(self):
        while True:
            with self._cv:
                while not self._heap:
                    self._cv.wait()
                due, _, fn, args = self._heap[0]
                wait = due - time.monotonic()
                if wait > 0:
                    self._cv.wait(wait)
                    continue
                heapq.heappop(self._heap)
            try:
                fn(*args)
            except Exception as e:           # nunca derruba o agendador
                log(f"[erro] agendador: {e}")


class VirtualPad:
    """Estado do controle. Cada botão tem um CONJUNTO de origens: só solta quando
    todas soltarem (resolve duas teclas no mesmo botão Xbox)."""

    def __init__(self, gamepad, codes):
        self.gp = gamepad
        self.codes = codes
        self.lock = threading.RLock()
        self.holders = {n: set() for n in BUTTONS}
        self.trig = {"LT": {}, "RT": {}}
        self.ls = (0.0, 0.0)
        self.rs = (0.0, 0.0)
        self._a_btn = {n: False for n in BUTTONS}
        self._a_trig = {"LT": 0.0, "RT": 0.0}
        self._a_ls = (0.0, 0.0)
        self._a_rs = (0.0, 0.0)

    def press(self, name, src, flush=True):
        with self.lock:
            self.holders[name].add(src)
            if flush:
                self.flush()

    def release(self, name, src, flush=True):
        with self.lock:
            self.holders[name].discard(src)
            if flush:
                self.flush()

    def set_trigger(self, name, src, value, flush=True):
        with self.lock:
            if value > 0.0:
                self.trig[name][src] = clamp(value, 0.0, 1.0)
            else:
                self.trig[name].pop(src, None)
            if flush:
                self.flush()

    def trigger_value(self, name):
        with self.lock:
            return max(self.trig[name].values(), default=0.0)

    def set_ls(self, x, y, flush=True):
        with self.lock:
            self.ls = (clamp(x, -1.0, 1.0), clamp(y, -1.0, 1.0))
            if flush:
                self.flush()

    def set_rs(self, x, y, flush=True):
        with self.lock:
            self.rs = (clamp(x, -1.0, 1.0), clamp(y, -1.0, 1.0))
            if flush:
                self.flush()

    def release_all(self):
        with self.lock:
            for n in BUTTONS:
                self.holders[n].clear()
            for n in ("LT", "RT"):
                self.trig[n].clear()
            self.ls = (0.0, 0.0)
            self.rs = (0.0, 0.0)
            self.flush()

    def snapshot(self):
        with self.lock:
            return {
                "buttons": {n for n in BUTTONS if self.holders[n]},
                "lt": max(self.trig["LT"].values(), default=0.0),
                "rt": max(self.trig["RT"].values(), default=0.0),
                "ls": self.ls, "rs": self.rs,
            }

    def flush(self):
        with self.lock:
            gp = self.gp
            changed = False
            for n in BUTTONS:
                want = bool(self.holders[n])
                if want != self._a_btn[n]:
                    if want:
                        gp.press_button(button=self.codes[n])
                    else:
                        gp.release_button(button=self.codes[n])
                    self._a_btn[n] = want
                    changed = True
            lt = max(self.trig["LT"].values(), default=0.0)
            rt = max(self.trig["RT"].values(), default=0.0)
            if lt != self._a_trig["LT"]:
                gp.left_trigger_float(value_float=lt)
                self._a_trig["LT"] = lt
                changed = True
            if rt != self._a_trig["RT"]:
                gp.right_trigger_float(value_float=rt)
                self._a_trig["RT"] = rt
                changed = True
            if self.ls != self._a_ls:
                gp.left_joystick_float(x_value_float=self.ls[0], y_value_float=self.ls[1])
                self._a_ls = self.ls
                changed = True
            if self.rs != self._a_rs:
                gp.right_joystick_float(x_value_float=self.rs[0], y_value_float=self.rs[1])
                self._a_rs = self.rs
                changed = True
            if changed:
                gp.update()
        # Força update inicial para o Remote Play detectar o controle virtual
        gp.update()


# ===================================================================== curvas
def apply_response(v, mode=None):
    """Curvas do stick: linear | progressive | aim | enhanced | easing_quadratic."""
    mode = mode or S["RESPONSE"]
    sign = 1.0 if v >= 0 else -1.0
    a = abs(v)
    if mode in ("enhanced", "easing_quadratic"):
        if a < 0.40:
            return sign * (a * 0.405)
        if a < 0.80:
            return sign * ((a - 0.40) / 0.40 * 0.595 + 0.162)
        t = (a - 0.80) / 0.20
        if mode == "enhanced":
            return sign * (t * t * 0.243 + 0.757)
        return sign * ((t * t * (3.0 - 2.0 * t)) * 0.243 + 0.757)
    if mode == "aim":
        return sign * (a ** 0.45)
    if mode == "progressive":
        return sign * (a ** 0.65)
    return v


def anti_deadzone(v):
    if v == 0.0:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (S["ANTI_DZ"] + abs(v) * (1.0 - S["ANTI_DZ"]))


def radial_deadzone(vx, vy, dz):
    mag = math.hypot(vx, vy)
    if mag < dz:
        return 0.0, 0.0
    scale = (mag - dz) / (1.0 - dz)
    return vx / mag * scale, vy / mag * scale


def approach(cur, target, up, down, dt):
    """Move `cur` até `target`: sobe com `up`, desce com `down` (unidades/s)."""
    if abs(target) > abs(cur) or (target * cur) < 0:
        step = up * dt
    else:
        step = down * dt
    if target > cur:
        return min(target, cur + step)
    return max(target, cur - step)


# ==================================================================== engine
class Engine:
    def __init__(self, pad):
        self.pad = pad
        self.sched = Scheduler()
        self.sched.start()
        self.running = True
        self.held = {}                   # origem -> ação aplicada ("k:w", "m:left")
        self.ls_src = {}
        self.ramp_src = {}
        self.sprint_src = set()
        self.prec_src = set()
        self.ramp = {"steer": 0.0, "RT": 0.0, "LT": 0.0}
        self.wheel = {"x": 0.0, "y": 0.0, "active": False}
        self.rs_direct = [0.0, 0.0]            # posição do stick no modo direto
        self.rs_pos = [0.0, 0.0]               # posição do stick no modo velocidade
        self._last_mouse_move_time = 0.0
        self.samples = deque(maxlen=128)
        self.mouse_lock = threading.Lock()
        self.smooth = [0.0, 0.0]
        self.idle = 0
        self._tap_id = itertools.count()
        self._last = None
        self._pending = False
        self._pending_t = 0.0
        self._center = (0, 0)
        self._half = (1, 1)
        self._kb_was = False
        self._ms_was = False
        self._menu_votes = 0
        self.cursor_confiner = CursorConfiner(self)

    # ------------------------------------------------------------ condições
    def menu_active(self):
        return state["menu_mode"] or state["menu_auto"]

    def focus_ok(self):
        return state["game_focus"] or not S["require_focus"]

    def keyboard_active(self):
        return (state["emulation"] and not self.menu_active()
                and not state["typing"] and self.focus_ok())

    def mouse_active(self):
        return (state["emulation"] and not self.menu_active()
                and state["mouse_captured"] and self.focus_ok())

    def radial_active(self):
        if state["mode"] == "foot":
            return bool(self.pad.holders["LB"])        # roda de armas
        return bool(self.pad.holders["DPAD_LEFT"])     # roda do rádio

    def aim_active(self):
        if state["mode"] == "foot":
            return self.pad.trigger_value("LT") > 0.5
        return bool(self.pad.holders["LB"])            # mira de drive-by

    # --------------------------------------------------------------- captura
    def start_capture(self, rect):
        clip_cursor(rect)
        state["mouse_captured"] = True
        state["capture_rect"] = rect
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        self._center = (cx, cy)
        self._half = (max(1, (rect[2] - rect[0]) // 2), max(1, (rect[3] - rect[1]) // 2))
        self._last = (cx, cy)
        self._pending = False
        set_cursor(cx, cy)
        # Esconde o cursor (mantém funcional)
        hide_cursor()
        # Inicia monitoramento contínuo de confinamento
        self.cursor_confiner.start()
        log(f"[mouse] capturado {rect[2] - rect[0]}x{rect[3] - rect[1]}")

    def stop_capture(self):
        if state["mouse_captured"]:
            # Mostra o cursor antes de liberar
            show_cursor()
            unclip_cursor()
            state["mouse_captured"] = False
            state["capture_rect"] = None
            self._last = None
            self._pending = False
            self._reset_mouse()
            # Para monitoramento de confinamento
            self.cursor_confiner.stop()
            log("[mouse] liberado")

    def _reset_mouse(self):
        with self.mouse_lock:
            self.samples.clear()
        self.smooth = [0.0, 0.0]
        self.idle = 0
        self.wheel.update(x=0.0, y=0.0, active=False)

    # --------------------------------------------------------------- toggles
    def toggle_emulation(self):
        state["emulation"] = not state["emulation"]
        if state["emulation"]:
            if not S["smart_capture"]:
                hwnd = fg_window()[0]
                self.start_capture(client_rect(hwnd))
        else:
            self.stop_capture()
            self.release_everything()
        log("[emulação] " + ("ligada" if state["emulation"] else "desligada"))

    def toggle_menu_mode(self):
        state["menu_mode"] = not state["menu_mode"]
        if state["menu_mode"]:
            self.stop_capture()
            self.release_everything()
            log("[menu] mouse livre — teclado e mouse não controlam o jogo")
        else:
            log("[menu] voltou ao jogo")

    def toggle_mode(self):
        state["mode"] = "car" if state["mode"] == "foot" else "foot"
        self.reapply_all()
        log("[modo] " + ("no carro" if state["mode"] == "car" else "a pé"))

    def toggle_walk(self):
        state["walk"] = not state["walk"]
        log("[andar] " + ("caminhando" if state["walk"] else "normal"))

    def set_typing(self, on):
        if state["typing"] == on:
            return
        state["typing"] = on
        if on:
            self.release_prefix("k:")
        log("[chat] teclado pausado (Enter/Esc volta)" if on else "[chat] teclado ativo")

    # ------------------------------------------------------- aplicar ações
    def apply_action(self, action, src, down):
        if not action:
            return
        with self.pad.lock:
            if action.startswith("tap:"):
                if down:
                    self.tap(action[4:])
                return
            if action in EVENT_ACTIONS:
                if down:
                    if action == "@WALK":
                        self.toggle_walk()
                    elif action == "@MODE":
                        self.toggle_mode()
                    elif action == "@MENU":
                        self.toggle_menu_mode()
                    elif action == "@GRENADE":
                        self.macro_grenade()
                return
            if action == "@SPRINT":
                (self.sprint_src.add if down else self.sprint_src.discard)(src)
            elif action == "@PRECISION":
                (self.prec_src.add if down else self.prec_src.discard)(src)
            elif action in LS_ACTIONS:
                if down:
                    self.ls_src[src] = action
                else:
                    self.ls_src.pop(src, None)
            elif action in RAMP_ACTIONS:
                if down:
                    self.ramp_src[src] = action
                else:
                    self.ramp_src.pop(src, None)
            elif action in ("LT", "RT"):
                self.pad.set_trigger(action, src, 1.0 if down else 0.0)
            elif action in BUTTONS:
                if down:
                    self.pad.press(action, src)
                else:
                    self.pad.release(action, src)

    def tap(self, name):
        src = f"tap:{name}:{next(self._tap_id)}"
        ms = max(20.0, float(S["TAP_MS"])) / 1000.0
        if name in ("LT", "RT"):
            self.pad.set_trigger(name, src, 1.0)
            self.sched.call_later(ms, self.pad.set_trigger, name, src, 0.0)
        elif name in BUTTONS:
            self.pad.press(name, src)
            self.sched.call_later(ms, self.pad.release, name, src)

    def macro_grenade(self):
        src = f"macro:grenade:{next(self._tap_id)}"
        self.pad.set_trigger("LT", src, 1.0)
        self.sched.call_later(0.06, self.tap, "DPAD_LEFT")
        self.sched.call_later(0.25, self.pad.set_trigger, "LT", src, 0.0)

    def release_prefix(self, prefix):
        with self.pad.lock:
            for src in [s for s in self.held if s.startswith(prefix)]:
                act = self.held.pop(src)
                self.apply_action(act, src, False)

    def release_everything(self):
        with self.pad.lock:
            self.held.clear()
            self.ls_src.clear()
            self.ramp_src.clear()
            self.sprint_src.clear()
            self.prec_src.clear()
            self.ramp.update(steer=0.0, RT=0.0, LT=0.0)
            self.pad.release_all()
        self._reset_mouse()

    def reapply_all(self):
        """Trocou a pé/carro com teclas seguradas: re-resolve cada uma sem ficar presa."""
        with self.pad.lock:
            for src, old in list(self.held.items()):
                self.apply_action(old, src, False)
                kind = "key" if src.startswith("k:") else "mouse"
                new = get_action(kind, src[2:])
                self.held[src] = new
                if new and not new.startswith("tap:") and new not in EVENT_ACTIONS:
                    self.apply_action(new, src, True)

    # ------------------------------------------------------------- teclado
    def on_key_press(self, key):
        k = normalize_key(key)
        if k is None or k in pressed:        # ignora o auto-repeat do Windows
            return
        pressed.add(k)
        if k in EMU_TOGGLE_KEYS:
            self.toggle_emulation()
            return
        if k in MENU_TOGGLE_KEYS:
            self.toggle_menu_mode()
            return
        if not state["emulation"]:
            return
        if S["typing_pause"] and state["game_focus"] and not self.menu_active():
            if state["typing"]:
                if k in TYPING_CLOSE_KEYS:
                    self.set_typing(False)
                return
            if k in TYPING_OPEN_KEYS:
                self.set_typing(True)
                return
        if not self.keyboard_active():
            return
        if k == "n" and self.pad.holders["LB"]:
            self.tap("RB")
            return
        if k == "m":
            S["DIRECT_MODE"] = not S["DIRECT_MODE"]
            log("[câmera] modo direto: " + ("LIGADO (lockpick)" if S["DIRECT_MODE"] else "DESLIGADO (velocidade)"))
            return
        action = get_action("key", k)
        src = "k:" + k
        with self.pad.lock:
            self.held[src] = action
            self.apply_action(action, src, True)
        if S["auto_mode_f"] and k == "f" and action == "Y":
            self.toggle_mode()

    def on_key_release(self, key):
        k = normalize_key(key)
        if k is None:
            return
        pressed.discard(k)
        src = "k:" + k
        with self.pad.lock:
            act = self.held.pop(src, None)
            if act:
                self.apply_action(act, src, False)

    # --------------------------------------------------------------- mouse
    def on_mouse_move(self, x, y):
        if not self.mouse_active():
            self._last = (x, y)
            return
        now = time.monotonic()
        cx, cy = self._center

        # Filtro de recentro / warp: se o evento veio do set_cursor ao centro
        if self._pending:
            if abs(x - cx) <= 2 and abs(y - cy) <= 2:
                self._pending = False
                self._last = (cx, cy)
                return
            elif now - self._pending_t > 0.04:
                self._pending = False

        if self._last is None:
            self._last = (x, y)
            return

        dx = x - self._last[0]
        dy = y - self._last[1]
        self._last = (x, y)
        self._last_mouse_move_time = now

        if S["DIRECT_MODE"]:
            # Modo direto: delta do mouse mapeia para posição do stick.
            # Ideal para lockpick (RS segura posição do mouse).
            with self.mouse_lock:
                self.rs_direct[0] = clamp(
                    self.rs_direct[0] + dx * S["DIRECT_SENS_X"], -1.0, 1.0
                )
                self.rs_direct[1] = clamp(
                    self.rs_direct[1] - dy * S["DIRECT_SENS_Y"], -1.0, 1.0
                )
        else:
            # MODO VELOCIDADE (comportamento GTA V real):
            # A posição do mouse relativa ao centro da tela = velocidade da câmera.
            # Quando para de mover, o cursor volta ao centro e a câmera pára.
            # NÃO acumulamos deltas — usamos posição absoluta relativa ao centro.
            feed_mouse_position(self, x, y, now)

        # Se afastar mais de 30% do raio útil da janela, recentra
        hw, hh = self._half
        if abs(x - cx) > hw * 0.30 or abs(y - cy) > hh * 0.30:
            self._pending = True
            self._pending_t = now
            self._last = (cx, cy)
            set_cursor(cx, cy)

    def feed_mouse_position(self, x, y, now):
        """Acumula deltas do mouse e armazena como valor do analógico direito.

        No GTA V real, o jogo lê o delta do mouse via Raw Input e converte
        em velocidade da câmera. O analógico direito (RS) representa essa
        velocidade, não uma posição absoluta.

        Quando o mouse para de se mover, o valor decai rapidamente para zero
        (sem efeito gelo prolongado).
        """
        dx = x - self._last[0]
        dy = y - self._last[1]

        # Acumula delta com sensibilidade
        sx = dx * S["SENS_X"]
        sy = dy * S["SENS_Y"]

        with self.mouse_lock:
            self.rs_pos[0] = clamp(
                self.rs_pos[0] + sx, -1.0, 1.0
            )
            self.rs_pos[1] = clamp(
                self.rs_pos[1] - sy, -1.0, 1.0
            )



    def on_mouse_click(self, x, y, button, is_down):
        name = str(button).replace("Button.", "")
        src = "m:" + name
        if is_down:
            if not self.mouse_active():
                return
            action = get_action("mouse", name)
            with self.pad.lock:
                self.held[src] = action
                self.apply_action(action, src, True)
        else:
            with self.pad.lock:
                act = self.held.pop(src, None)
                if act:
                    self.apply_action(act, src, False)

    def on_mouse_scroll(self, x, y, dx, dy):
        if not self.mouse_active() or dy == 0:
            return
        if self.pad.holders["LB"]:
            self.tap("LT" if dy > 0 else "RT")
            return
        name = "wheel_up" if dy > 0 else "wheel_down"
        action = get_action("mouse", name)
        if action and not action.startswith("tap:") and action not in EVENT_ACTIONS:
            if action in BUTTONS or action in ("LT", "RT"):
                action = "tap:" + action
            else:
                return
        self.apply_action(action, "w:" + name, True)

    # Novo motor baseado no comportamento real do GTA V / FiveM:
    #   - O cursor fica preso ao centro da tela
    #   - Distância do centro = velocidade da câmera (RS = velocidade)
    #   - Deadzone nativa do jogo: 0.467 (14/30)
    #   - Quando o mouse para, o cursor volta ao centro e a câmera pára
    #   - Modo direto: posição do mouse = posição do stick (lockpick)

    def camera_vector(self, now, dt):
        # ------------------------------------------------------------------ Direto
        if S["DIRECT_MODE"]:
            with self.mouse_lock:
                vx, vy = self.rs_direct[0], self.rs_direct[1]

            # Decaimento exponencial quando o mouse para (evita efeito gelo)
            idle_time = now - self._last_mouse_move_time
            if idle_time > 0.05:
                tau = 0.200  # meia-vida de 200ms
                decay = math.exp(-dt / tau)
                vx *= decay
                vy *= decay
                with self.mouse_lock:
                    self.rs_direct[0] = vx
                    self.rs_direct[1] = vy

            dz_ours = S["DIRECT_DEADZONE"]   # nossa zona morta (0.04)
            dz_game = 0.467                  # deadzone nativa do GTA V (14/30)
            useful_range = 1.0 - dz_game     # 0.533 faixa útil

            mag = math.hypot(vx, vy)
            if mag < dz_ours:
                return 0.0, 0.0

            # Normaliza após nossa zona morta (0 → 1)
            normalized = (mag - dz_ours) / (1.0 - dz_ours)

            # Aim acceleration: curva exponencial (mais lento perto do centro)
            curved = normalized ** 1.4

            # Transição suave através da deadzone do jogo (0 → dz_game)
            transition_zone = 0.15
            if curved < transition_zone:
                t = curved / transition_zone
                t = t * t * (3.0 - 2.0 * t)  # smoothstep
                output_mag = t * dz_game
            else:
                t = (curved - transition_zone) / (1.0 - transition_zone)
                output_mag = dz_game + t * useful_range

            # Anti-deadzone: empurra mínimo para acima da deadzone do jogo
            if output_mag > 0:
                output_mag = anti_deadzone(output_mag)

            # Curva de resposta configurável
            curve = S["RESPONSE"]
            if curve == "progressive":
                output_mag = output_mag ** 0.65
            elif curve == "aim":
                output_mag = output_mag ** 0.45

            output_mag = min(output_mag, 1.0)
            scale = output_mag / mag
            vx *= scale
            vy *= scale

            # Deadzone radial mínima final (evita drift)
            vx, vy = radial_deadzone(vx, vy, dz_ours)
            return vx, vy

        # ----------------------------------------------------------------- Velocidade
        # MODO VELOCIDADE (comportamento GTA V real):
        # A posição do mouse relativa ao centro = velocidade da câmera (RS = velocidade).
        # Quando o mouse para, o cursor volta ao centro e a câmera pára imediatamente.
        #
        # Pipeline fiel ao GTA V:
        #   1. Pos do mouse relativa ao centro (normalizada -1..1)
        #   2. Aplica sensibilidade SENS_X/SENS_Y
        #   3. Deadzone nativa do jogo (0.467): valores abaixo são IGNORADOS pelo jogo
        # ----------------------------------------------------------------- Velocidade
        # MODO VELOCIDADE (comportamento GTA V real):
        # O jogo lê deltas do mouse via Raw Input e converte em velocidade da câmera.
        # O analógico direito (RS) = velocidade da câmera.
        # Quando o mouse para, o valor decai rapidamente para zero.
        #
        # Pipeline fiel ao GTA V:
        #   1. Acumula deltas do mouse (rs_pos) com sensibilidade
        #   2. Aplica aim acceleration (suaviza movimentos pequenos perto do centro)
        #   3. Deadzone nativa do jogo (0.467): valores abaixo são IGNORADOS
        #   4. Reescalona faixa útil [0.467, 1.0] para [0, 1] com smoothstep
        #   5. Anti-deadzone: empurra mínimo acima da zona morta do jogo
        #   6. Decaimento quando não há entrada (sem efeito gelo)
        with self.mouse_lock:
            vx, vy = self.rs_pos[0], self.rs_pos[1]

        mag = math.hypot(vx, vy)

        # Sem entrada: decai rapidamente para zero (sem efeito gelo)
        if mag == 0.0:
            return 0.0, 0.0

        # --- Aim acceleration: mais lento perto do centro ---
        # Expoente > 1.0 suaviza pequenos movimentos perto do centro
        curved_mag = mag ** 1.6

        # --- Deadzone nativa do GTA V (0.467) ---
        # O jogo ignora qualquer valor do stick abaixo de 0.467.
        dz_game = 0.467   # deadzone nativa do GTA V (14/30)
        dz_ours = S["DEADZONE_RS"]  # nossa zona morta (0.12)
        useful_range = 1.0 - dz_game  # 0.533

        # Normaliza após nossa zona morta (0 -> 1)
        if curved_mag < dz_ours:
            return 0.0, 0.0
        normalized = (curved_mag - dz_ours) / (1.0 - dz_ours)

        # Transição suave através da deadzone do jogo (0 -> dz_game)
        # Sem isso, o câmera "pula" quando sai da zona morta do GTA V
        transition_zone = 0.15
        if normalized < transition_zone:
            t = normalized / transition_zone
            t = t * t * (3.0 - 2.0 * t)  # smoothstep
            output_mag = t * dz_game
        else:
            t = (normalized - transition_zone) / (1.0 - transition_zone)
            output_mag = dz_game + t * useful_range

        # Anti-deadzone: garante mínimo acima da deadzone do jogo (para Remote Play)
        if output_mag > 0:
            output_mag = anti_deadzone(output_mag)

        # Curva de resposta configurável (progressive / aim / linear)
        curve = S["AIM_RESPONSE"] if self.aim_active() else S["RESPONSE"]
        if curve == "progressive":
            output_mag = output_mag ** 0.65
        elif curve == "aim":
            output_mag = output_mag ** 0.45

        # Multiplicadores de modo (precisão / mira)
        mult = 1.0
        if self.prec_src:
            mult *= S["PRECISION_MULT"]
        if self.aim_active():
            mult *= S["AIM_MULT"]
        output_mag *= mult

        # Clamp final
        output_mag = min(output_mag, 1.0)

        # Reaplica direção (sem amplificação: output_mag <= 1, mag pode ser < output_mag)
        scale = output_mag / mag if mag > 0 else 0.0
        vx *= scale
        vy *= scale

        # Decaimento quando não há movimento contínuo (sem efeito gelo)
        decay = min(0.85, S["FRICTION"])
        vx *= decay
        vy *= decay

        # Deadzone radial mínima final (evita drift residual)
        vx, vy = radial_deadzone(vx, vy, S["DEADZONE_RS"])

        # Clamp circular: em 360° a magnitude nunca estoura 1.0
        mag = math.hypot(vx, vy)
        if mag > 1.0:
            vx /= mag
            vy /= mag

        if abs(vx) < SETTLE:
            vx = 0.0
        if abs(vy) < SETTLE:
            vy = 0.0

        return vx, vy



    def supervise(self):
        hwnd, title, exe = fg_window()

        own = title.startswith(APP_TITLE_LOWER)
        pats = [p.strip().lower() for p in S["game_patterns"].split(",") if p.strip()]
        if own:
            focus = False
        elif any(p in exe for p in pats):                  # processo do jogo
            focus = True
        else:                                              # título (ignora navegadores etc.)
            focus = exe not in NOT_GAME_EXES and any(p in title for p in pats)
        state["fg_title"] = title
        if focus != state["game_focus"]:
            state["game_focus"] = focus
            log("[jogo] em foco" if focus else "[jogo] fora de foco")
        if not focus and state["typing"]:
            self.set_typing(False)

        # auto_menu_cursor só funciona quando DIRECT_MODE está DESLIGADO
        # (lockpick precisa que o RS segure a posição mesmo com cursor visível)
        if S["auto_menu_cursor"] and not S["DIRECT_MODE"] and focus and state["emulation"] and not state["menu_mode"]:
            showing = cursor_showing()
            self._menu_votes = min(self._menu_votes + 1, 4) if showing else 0
            auto = self._menu_votes >= 2
            if auto != state["menu_auto"]:
                state["menu_auto"] = auto
                log("[menu] cursor visível — mouse livre" if auto else "[menu] cursor oculto")
                if auto:
                    self.stop_capture()
                    self.release_everything()
        elif state["menu_auto"]:
            state["menu_auto"] = False
            self._menu_votes = 0

        if S["smart_capture"]:
            wanted = state["emulation"] and not self.menu_active() and focus
            if wanted:
                rect = client_rect(hwnd)
                if (not state["mouse_captured"]) or rect != state["capture_rect"]:
                    self.start_capture(rect)
            elif state["mouse_captured"]:
                self.stop_capture()


    # ------------------------------------------------------------- loop 120Hz
    def step(self, now, dt):
        pad = self.pad
        kb_on = self.keyboard_active()
        ms_on = self.mouse_active()
        if self._kb_was and not kb_on:
            self.release_prefix("k:")
        if self._ms_was and not ms_on:
            self.release_prefix("m:")
            self._reset_mouse()
        self._kb_was, self._ms_was = kb_on, ms_on

        with pad.lock:
            # ---- analógico direito: roda (posição fixa) ou câmera (velocidade)
            if ms_on:
                radial = self.radial_active()
                if radial != self.wheel["active"]:
                    self.wheel.update(x=0.0, y=0.0, active=radial)
                    with self.mouse_lock:
                        self.samples.clear()
                    self.smooth = [0.0, 0.0]
                if radial:
                    r = max(20.0, float(S["WHEEL_RADIUS"]))
                    rs = (self.wheel["x"] / r, self.wheel["y"] / r)
                else:
                    rs = self.camera_vector(now, dt)
            else:
                rs = (0.0, 0.0)
            pad.set_rs(rs[0], rs[1], flush=False)

            # ---- analógico esquerdo (WASD)
            tx = ty = 0.0
            for a in self.ls_src.values():
                ax, ay = LS_ACTIONS[a]
                tx += ax
                ty += ay
            m = math.hypot(tx, ty)
            if m > 1.0:
                tx, ty = tx / m, ty / m
            if state["mode"] == "car":
                sr = S["STEER_RAMP"]
                if sr >= 20.0:
                    self.ramp["steer"] = tx
                else:
                    self.ramp["steer"] = approach(self.ramp["steer"], tx, sr, sr * 2.0, dt)
                pad.set_ls(self.ramp["steer"], ty, flush=False)
            else:
                self.ramp["steer"] = 0.0
                scale = S["WALK_SCALE"] if (state["walk"] and not self.sprint_src) else 1.0
                pad.set_ls(tx * scale, ty * scale, flush=False)

            # ---- pedais com rampa (acelerar / frear)
            rt_t = lt_t = 0.0
            for a in self.ramp_src.values():
                if a == "ACCEL":
                    rt_t = max(rt_t, 1.0)
                elif a == "ACCEL_HALF":
                    rt_t = max(rt_t, float(S["HALF_THROTTLE"]))
                elif a == "BRAKE":
                    lt_t = max(lt_t, 1.0)
            up = S["PEDAL_RAMP"]
            for axis, tgt in (("RT", rt_t), ("LT", lt_t)):
                cur = self.ramp[axis]
                if up >= 20.0 and tgt > cur:
                    cur = tgt
                else:
                    cur = approach(cur, tgt, up, up * 2.5 + 4.0, dt)
                self.ramp[axis] = cur
                pad.set_trigger(axis, "ramp", cur if cur > 0.001 else 0.0, flush=False)

            # ---- correr: o GTA V pede toques repetidos em A
            if self.sprint_src:
                period = 1.0 / max(1.0, float(S["SPRINT_HZ"]))
                if (now % period) < period * 0.5:
                    pad.press("A", "macro:sprint", flush=False)
                else:
                    pad.release("A", "macro:sprint", flush=False)
            else:
                pad.release("A", "macro:sprint", flush=False)

            pad.flush()

    def output_loop(self):
        last = time.monotonic()
        sup_t = 0.0
        while self.running:
            now = time.monotonic()
            dt = min(now - last, 0.1)
            last = now
            try:
                if now - sup_t > 0.25:
                    self.supervise()
                    sup_t = now
                self.step(now, dt)
            except Exception as e:
                log(f"[erro] loop: {e}")
            time.sleep(1.0 / 120.0)

    def shutdown(self):
        self.running = False
        self.stop_capture()
        self.release_everything()


# ======================================================================== GUI
# Paleta moderna e profissional — tons escuros com acentos vivos
BG = "#0f121c"            # fundo principal (quase preto)
PANEL = "#161a27"          # painéis secundários
PANEL2 = "#1f2433"         # superfície de entrada/ativos
EDGE = "#2d3446"            # bordas sutis
TEXT = "#e8ecf5"            # texto primário
MUTED = "#94a3b8"           # texto secundário
DIM = "#64748b"             # texto desabilitado/sutil
AMBER = "#f59e0b"           # aviso / atenção
TEAL = "#22d3ee"             # info / conectividade
CORAL = "#fb7185"           # erro / perigo
INDIGO = "#6366f1"          # ação primária
VIOLET = "#a855f7"          # modo especial
OLIVE = "#84cc16"           # sucesso / ativo
BRONZE = "#d97706"          # modo direto / alerta
SURFACE = "#1c2130"         # cards
SURFACE_HOVER = "#252a3b"   # cards hover
BORDER = "#334054"           # bordas dos cards
ACCENT = "#22d3ee"           # destaque principal
ACCENT_DIM = "#155e75"       # destaque escuro
SUCCESS = "#34d399"          # confirmação
WARNING = "#fbbf24"          # alerta
ERROR = "#f87171"           # erro
RING = "#6366f1"            # anel de foco
GAP = 10
CARD_PAD = 14
FONT = "Segoe UI"
FONT_BOLD = "Segoe UI Semibold"
MONO = "Consolas"

# Estados de conexão / status
STATUS_ON = OLIVE
STATUS_OFF = DIM
STATUS_WARN = AMBER
STATUS_ERR = CORAL

CAT_COLORS = {
    "foot": TEAL,
    "car": INDIGO,
    "menu": VIOLET,
    "system": OLIVE,
    "mouse": BRONZE,
}

CAT_NAMES = [
    ("foot", "A pé"),
    ("car", "No carro"),
    ("menu", "Menu"),
    ("system", "Sistema"),
    ("mouse", "Mouse"),
]



KB_UNITS = 18.5
KB_ROWS = [
    # (rótulo, nome pynput, largura) — None = espaço
    [("Esc", "esc", 1), (None, None, 1)]
    + [(f"F{i}", f"f{i}", 1) for i in range(1, 5)] + [(None, None, 0.5)]
    + [(f"F{i}", f"f{i}", 1) for i in range(5, 9)] + [(None, None, 0.5)]
    + [(f"F{i}", f"f{i}", 1) for i in range(9, 13)] + [(None, None, 0.5)]
    + [("PrtSc", "print_screen", 1), ("ScrLk", "scroll_lock", 1), ("Pause", "pause", 1)],
    [("`", "`", 1)] + [(str(i), str(i), 1) for i in list(range(1, 10)) + [0]]
    + [("-", "-", 1), ("=", "=", 1), ("Bksp", "backspace", 2), (None, None, 0.5),
       ("Ins", "insert", 1), ("Home", "home", 1), ("PgUp", "page_up", 1)],
    [("Tab", "tab", 1.5)] + [(c.upper(), c, 1) for c in "qwertyuiop"]
    + [("[", "[", 1), ("]", "]", 1), ("\\", "\\", 1.5), (None, None, 0.5),
       ("Del", "delete", 1), ("End", "end", 1), ("PgDn", "page_down", 1)],
    [("Caps", "caps_lock", 1.75)] + [(c.upper(), c, 1) for c in "asdfghjkl"]
    + [(";", ";", 1), ("'", "'", 1), ("Enter", "enter", 2.25)],
    [("Shift", "shift_l", 2.25)] + [(c.upper(), c, 1) for c in "zxcvbnm"]
    + [(",", ",", 1), (".", ".", 1), ("/", "/", 1), ("Shift", "shift_r", 2.75),
       (None, None, 1.5), ("↑", "up", 1)],
    [("Ctrl", "ctrl_l", 1.5), ("Win", "cmd", 1.25), ("Alt", "alt_l", 1.25),
     ("Espaço", "space", 6.25), ("AltGr", "alt_r", 1.25), ("Win", "cmd_r", 1.25),
     ("Ctrl", "ctrl_r", 2.0), (None, None, 0.5),
     ("←", "left", 1), ("↓", "down", 1), ("→", "right", 1)],
]

MOUSE_ROWS = [("left", "Botão esquerdo"), ("right", "Botão direito"),
              ("middle", "Clique na roda"), ("x1", "Botão lateral 1 (MB4)"),
              ("x2", "Botão lateral 2 (MB5)"), ("wheel_up", "Roda para cima"),
              ("wheel_down", "Roda para baixo")]

CAMERA_SLIDERS = [
    ("SENS_X", "Sensibilidade horizontal", 0.05, 0.60, 0.01),
    ("SENS_Y", "Sensibilidade vertical", 0.05, 0.60, 0.01),
    ("DEADZONE_RS", "Zona morta", 0.0, 0.40, 0.01),
    ("ANTI_DZ", "Anti-zona morta", 0.0, 0.30, 0.01),
    ("FRICTION", "Fricção", 0.50, 0.98, 0.01),
    ("SMOOTHING", "Suavização", 0.0, 0.80, 0.01),
    ("SMOOTHING_MAX_TAU_MS", "Suavização máxima (ms)", 0.0, 200.0, 5.0),
    ("PRECISION_MULT", "Mouse lento (Alt)", 0.05, 1.0, 0.05),
    ("AIM_MULT", "Mouse ao mirar", 0.10, 1.0, 0.05),
    # Modo direto (lockpick)
    ("DIRECT_SENS_X", "Direto: sensibilidade X", 0.001, 0.020, 0.001),
    ("DIRECT_SENS_Y", "Direto: sensibilidade Y", 0.001, 0.020, 0.001),
    ("DIRECT_DEADZONE", "Direto: zona morta", 0.0, 0.10, 0.01),
]
MOVE_SLIDERS = [
    ("WHEEL_RADIUS", "Alcance da roda de armas (px)", 40.0, 300.0, 5.0),
    ("WALK_SCALE", "Velocidade ao caminhar", 0.20, 0.90, 0.05),
    ("SPRINT_HZ", "Toques de corrida por segundo", 4.0, 14.0, 1.0),
    ("TAP_MS", "Duração do toque rápido (ms)", 30.0, 150.0, 5.0),
    ("HALF_THROTTLE", "Acelerador leve", 0.10, 0.60, 0.05),
    ("PEDAL_RAMP", "Rampa dos pedais (20 = direto)", 1.0, 20.0, 0.5),
    ("STEER_RAMP", "Rampa da direção (20 = direto)", 1.0, 20.0, 0.5),
]
CURVES = ["linear", "progressive", "enhanced", "easing_quadratic"]
CURVE_LABELS = {"linear": "Linear", "progressive": "Progressiva",
                "enhanced": "Reforçada", "easing_quadratic": "Suave nas pontas"}
MODE_LABELS = {"foot": "A pé", "car": "No carro"}

def _btn(parent, text, command, bg=SURFACE_HOVER, fg=TEXT, hover=None, **kw):
    """Botão moderno com efeito hover."""
    if hover is None:
        hover = ACCENT_DIM if bg == SURFACE_HOVER else bg
    b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                  activebackground=hover, activeforeground=TEXT, relief="flat",
                  bd=0, padx=14, pady=8, cursor="hand2",
                  font=(FONT_BOLD, 10), **kw)

    def _enter(_e):
        b.configure(bg=hover)
    def _leave(_e):
        b.configure(bg=bg)
    b.bind("<Enter>", _enter)
    b.bind("<Leave>", _leave)
    return b



class App:
    def __init__(self, root, engine):
        self.root = root
        self.eng = engine
        root.title(APP_TITLE)
        root.geometry("1400x880")
        root.minsize(1180, 760)
        root.configure(bg=BG)
        self._sig = None
        self._key_fill = {}
        self._pad_sig = None
        self._log_seen = -1
        self._kb_unit = 0
        self._resize_job = None
        self.key_items = {}
        self.mouse_btns = {}
        self._style()
        self._build_header()
        self._build_body()
        self.update_ui()

    # ---------------------------------------------------------------- estilo
    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                     padding=(16, 10), font=(FONT_BOLD, 10), borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", SURFACE)],
               foreground=[("selected", TEXT)])
        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                     foreground=TEXT, arrowcolor=TEXT, bordercolor=EDGE,
                     lightcolor=PANEL2, darkcolor=PANEL2, selectbackground=PANEL2,
                     selectforeground=TEXT)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
               foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", INDIGO)

    # ---------------------------------------------------------------- header
    def _build_header(self):
        h = tk.Frame(self.root, bg=BG)
        h.pack(fill="x", padx=CARD_PAD, pady=(14, 10))
        h.grid_columnconfigure(1, weight=1)

        # Título à esquerda
        title = tk.Frame(h, bg=BG)
        title.grid(row=0, column=0, sticky="w")
        tk.Label(title, text="GTA6 Controller", font=(FONT_BOLD, 20),
                 fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(title, text="Emulador de controle Xbox para GTA V / FiveM",
                 font=(FONT, 10), fg=MUTED, bg=BG).pack(anchor="w", pady=(2, 0))

        # Status cards no centro
        chips = tk.Frame(h, bg=BG)
        chips.grid(row=0, column=1, sticky="e", padx=(30, 0))
        self.chips = {}
        for key in ("emu", "mode", "mouse", "game", "input"):
            card = tk.Frame(chips, bg=SURFACE, highlightbackground=BORDER,
                            highlightthickness=1, bd=0, padx=12, pady=6)
            card.pack(side="left", padx=4)
            lab = tk.Label(card, text="", font=(FONT_BOLD, 9), padx=0, pady=0,
                           fg=TEXT, bg=SURFACE)
            lab.pack()
            self.chips[key] = lab

        # Ações à direita
        right = tk.Frame(h, bg=BG)
        right.grid(row=0, column=2, sticky="e")
        self.profile_var = tk.StringVar(value=PROFILES[S["profile"]]["label"])
        cb = ttk.Combobox(right, textvariable=self.profile_var, state="readonly", width=26,
                          values=[p["label"] for p in PROFILES.values()],
                          font=(FONT, 10))
        cb.pack(side="left", padx=(0, 10))
        cb.bind("<<ComboboxSelected>>", self._on_profile)
        self.btn_emu = _btn(right, "Emulação", self._toggle_emu)
        self.btn_emu.pack(side="left", padx=4)
        self.btn_mode = _btn(right, "Modo", self._toggle_mode)
        self.btn_mode.pack(side="left", padx=4)
        self.btn_menu = _btn(right, "Mouse livre", self._toggle_menu)
        self.btn_menu.pack(side="left", padx=4)
        _btn(right, "Salvar", self._save, bg=INDIGO).pack(side="left", padx=(4, 0))

    # ---------------------------------------------------------------- body
    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=CARD_PAD, pady=(0, CARD_PAD))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=460)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_left(left)
        self._build_right(right)
        self.update_ui()




    # ------------------------------------------------------------ coluna esq.
    def _section(self, parent, text):
        """Cria uma seção em card com título e borda."""
        card = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="x", pady=(0, GAP))
        tk.Label(card, text=text, font=(FONT, 11, "bold"), fg=TEXT, bg=SURFACE,
                 padx=CARD_PAD, pady=CARD_PAD).pack(anchor="w")
        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="both", expand=True, padx=CARD_PAD, pady=(0, CARD_PAD))
        return body

    def _build_left(self, left):
        kb_body = self._section(left, "Teclado")
        kb_body.pack(fill="both", expand=True, pady=(0, GAP))
        self.kb = tk.Canvas(kb_body, bg=SURFACE, highlightthickness=0, height=330)
        self.kb.pack(fill="both", expand=True)
        self.kb.bind("<Configure>", self._on_kb_configure)

        bar = tk.Frame(kb_body, bg=SURFACE)
        bar.pack(fill="x", pady=(8, 0))
        for cat, name in CAT_NAMES:
            f = tk.Frame(bar, bg=SURFACE)
            f.pack(side="left", padx=(0, 14))
            tk.Frame(f, bg=CAT_COLORS[cat], width=12, height=12).pack(side="left", padx=(0, 5))
            tk.Label(f, text=name, fg=MUTED, bg=SURFACE, font=(FONT, 9)).pack(side="left")
        tk.Frame(bar, bg=AMBER, width=12, height=12).pack(side="left", padx=(8, 5))
        tk.Label(bar, text="Pressionada", fg=MUTED, bg=SURFACE, font=(FONT, 9)).pack(side="left")

        self.info = tk.Label(kb_body, text="Passe o mouse sobre uma tecla. Clique para trocar a função.",
                             fg=TEXT, bg=SURFACE, anchor="w", padx=0, pady=8, font=(FONT, 10))
        self.info.pack(fill="x", pady=(8, 10))

        log_body = self._section(left, "Registro")
        log_body.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_body, height=6, bg=PANEL, fg=TEXT, bd=0, padx=10, pady=8,
                                font=(MONO, 10), state="disabled", wrap="word",
                                insertbackground=TEXT, highlightthickness=0)
        self.log_text.pack(fill="both", expand=True)




    def _on_kb_configure(self, event):
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.root.after(60, lambda w=event.width: self._redraw_kb(w))

    def _redraw_kb(self, width):
        unit = max(30.0, min(58.0, (width - 24) / KB_UNITS))
        if abs(unit - self._kb_unit) < 1.0 and self.key_items:
            return
        self._kb_unit = unit
        self.draw_keyboard(unit)

    def draw_keyboard(self, u):
        c = self.kb
        c.delete("all")
        self.key_items = {}
        self._key_fill = {}
        pad_x, pad_y, gap = 12, 12, 3
        tag_id = itertools.count()
        y = pad_y
        for ri, row in enumerate(KB_ROWS):
            x = pad_x
            for label, norm, w in row:
                width = w * u
                if norm is not None:
                    tag = f"key{next(tag_id)}"
                    rect = c.create_rectangle(x + gap, y + gap, x + width - gap, y + u - gap,
                                              fill=CAT_COLORS["none"], outline=EDGE, tags=(tag,))
                    t1 = c.create_text(x + gap + 5, y + gap + 4, text=label, anchor="nw",
                                       fill=MUTED, font=(FONT, max(7, int(u / 6.2))), tags=(tag,))
                    t2 = c.create_text(x + width / 2, y + u * 0.64, text="", fill=TEXT,
                                       font=(FONT, max(7, int(u / 5.2)), "bold"), tags=(tag,))
                    self.key_items[norm] = (rect, t1, t2)
                    c.tag_bind(tag, "<Enter>", lambda e, k=norm, l=label: self._key_info(k, l))
                    c.tag_bind(tag, "<Leave>", lambda e: self._clear_info())
                    c.tag_bind(tag, "<Button-1>", lambda e, k=norm, l=label: self._edit_key(k, l))
                    c.tag_bind(tag, "<Button-3>", lambda e, k=norm, l=label: self._edit_key(k, l))
                x += width
            y += u + (u * 0.35 if ri == 0 else 0)
        c.config(height=int(y + pad_y))
        self._sig = None

    def _key_info(self, norm, label):
        act = get_action("key", norm)
        txt = f"{label} — {MODE_LABELS[state['mode']]}: {action_label(act)}" if act \
            else f"{label} — sem função no controle (passa como teclado normal)"
        self.info.config(text=txt)

    def _clear_info(self):
        self.info.config(text="Passe o mouse sobre uma tecla. Clique para trocar a função.")

    # ------------------------------------------------------------ coluna dir.
    def _build_right(self, right):
        pad_body = self._section(right, "Controle virtual")
        pad_body.configure(height=280)
        pad_body.pack_propagate(False)
        self._build_pad_canvas(pad_body)
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True, pady=(GAP, 0))
        self._tab_mouse(nb)
        self._tab_sliders(nb, "Câmera", CAMERA_SLIDERS, with_curve=True)
        self._tab_sliders(nb, "Roda e carro", MOVE_SLIDERS)
        self._tab_options(nb)


    def _tab_frame(self, nb, title):
        f = tk.Frame(nb, bg=SURFACE, padx=CARD_PAD, pady=CARD_PAD)
        nb.add(f, text=title)
        return f


    def _tab_mouse(self, nb):
        f = self._tab_frame(nb, "Mouse")
        tk.Label(f, text="Movimento do mouse = analógico direito (câmera).\n"
                         "Com a roda aberta (segurar Tab), o mouse aponta e mantém a seleção.",
                 fg=MUTED, bg=SURFACE, justify="left", font=(FONT, 9)).pack(anchor="w", pady=(0, 10))
        for name, label in MOUSE_ROWS:
            row = tk.Frame(f, bg=SURFACE)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, fg=TEXT, bg=SURFACE, width=22, anchor="w",
                     font=(FONT, 10)).pack(side="left")
            b = tk.Button(row, text="", anchor="w", bg=PANEL, fg=TEXT, relief="flat", bd=0,
                          padx=10, pady=4, cursor="hand2", activebackground=EDGE,
                          activeforeground=TEXT, font=(FONT, 10),
                          command=lambda n=name, l=label: self._edit_mouse(n, l))
            b.pack(side="left", fill="x", expand=True)
            self.mouse_btns[name] = b

    def _tab_sliders(self, nb, title, specs, with_curve=False):
        f = self._tab_frame(nb, title)
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=1)
        r = 0
        for i, (key, label, lo, hi, res) in enumerate(specs):
            cell = tk.Frame(f, bg=SURFACE)
            cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=4)
            cell.grid_columnconfigure(1, weight=1)
            header = tk.Frame(cell, bg=SURFACE)
            header.pack(fill="x")
            tk.Label(header, text=label, fg=TEXT, bg=SURFACE, font=(FONT_BOLD, 9)).pack(side="left")
            val_lab = tk.Label(header, text=f"{S[key]:.2f}", fg=ACCENT, bg=SURFACE,
                               font=(FONT_BOLD, 9), width=6, anchor="e")
            val_lab.pack(side="right")
            s = tk.Scale(cell, from_=lo, to=hi, resolution=res, orient="horizontal",
                         bg=SURFACE, fg=TEXT, troughcolor=PANEL, highlightthickness=0,
                         bd=0, sliderrelief="flat", activebackground=ACCENT,
                         length=170, font=(FONT, 8),
                         command=lambda v, k=key, vl=val_lab: self._on_slider(v, k, vl))
            s.set(S[key])
            s.pack(fill="x", pady=(2, 0))
            r = i // 2 + 1
        if with_curve:
            mode_frame = tk.Frame(f, bg=SURFACE)
            mode_frame.grid(row=r, column=0, columnspan=2, sticky="ew", padx=6, pady=(12, 5))
            tk.Label(mode_frame, text="Modo da câmera:", fg=TEXT, bg=SURFACE,
                     font=(FONT_BOLD, 10)).pack(side="left")
            self.direct_var = tk.BooleanVar(value=S["DIRECT_MODE"])
            rb_direct = tk.Radiobutton(mode_frame, text="Direto (lockpick)", variable=self.direct_var,
                                        value=True, command=lambda: self._set_direct_mode(True),
                                        bg=SURFACE, fg=TEXT, selectcolor=PANEL, activebackground=SURFACE,
                                        activeforeground=TEXT, font=(FONT, 10))
            rb_direct.pack(side="left", padx=(10, 5))
            rb_velocity = tk.Radiobutton(mode_frame, text="Velocidade (câmera)", variable=self.direct_var,
                                         value=False, command=lambda: self._set_direct_mode(False),
                                         bg=SURFACE, fg=TEXT, selectcolor=PANEL, activebackground=SURFACE,
                                         activeforeground=TEXT, font=(FONT, 10))
            rb_velocity.pack(side="left", padx=5)

    def _on_slider(self, v, key, label):
        val = float(v)
        S[key] = val
        label.config(text=f"{val:.2f}")


    def _set_direct_mode(self, enabled):
        S["DIRECT_MODE"] = enabled
        log(f"[câmera] modo {'direto (lockpick)' if enabled else 'velocidade (câmera)'}")
    def _tab_options(self, nb):
        f = self._tab_frame(nb, "Opções")
        self.opt_vars = {}
        opts = [
            ("require_focus", "Enviar comandos só com o jogo em foco"),
            ("smart_capture", "Capturar o mouse sozinho ao entrar no jogo"),
            ("typing_pause", "Pausar o teclado ao digitar no chat (T ou /)"),
            ("auto_mode_f", "Alternar a pé / carro ao apertar F (experimental)"),
            ("auto_menu_cursor", "Liberar o mouse quando o cursor aparecer (experimental)"),
        ]
        for key, text in opts:
            v = tk.BooleanVar(value=S[key])
            self.opt_vars[key] = v
            tk.Checkbutton(f, text=text, variable=v, command=lambda k=key: self._set_opt(k),
                           bg=SURFACE, fg=TEXT, selectcolor=PANEL, activebackground=SURFACE,
                           activeforeground=TEXT, anchor="w", font=(FONT, 10)).pack(fill="x", pady=3)
        tk.Label(f, text="Títulos de janela do jogo (separados por vírgula)", fg=TEXT,
                 bg=SURFACE, font=(FONT, 9)).pack(anchor="w", pady=(12, 2))
        self.pat_var = tk.StringVar(value=S["game_patterns"])
        e = tk.Entry(f, textvariable=self.pat_var, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                     relief="flat", font=(FONT, 10))
        e.pack(fill="x", ipady=4)
        e.bind("<FocusOut>", self._set_patterns)
        e.bind("<Return>", self._set_patterns)
        bf = tk.Frame(f, bg=SURFACE)
        bf.pack(fill="x", pady=(12, 8))
        _btn(bf, "Restaurar teclas do perfil", self._reset_profile, bg=PANEL).pack(side="left")
        tk.Label(f, justify="left", fg=MUTED, bg=SURFACE, font=(FONT, 9),
                 text="F8 ou Scroll Lock: liga/desliga   |   Pause: mouse livre (menus)\n"
                      "F12: a pé/carro   |   Ctrl direito: caminhar   |   Enter/Esc: sai do chat"
                 ).pack(anchor="w")

    # ------------------------------------------------------- controle virtual
    def _build_pad_canvas(self, parent):
        c = tk.Canvas(parent, width=400, height=252, bg=PANEL, highlightthickness=0)
        c.pack()
        self.pad_cv = c
        it = self.pad_items = {}
        c.create_polygon(78, 96, 322, 96, 356, 134, 364, 206, 334, 236, 302, 214, 262, 182,
                         138, 182, 98, 214, 66, 236, 36, 206, 44, 134, smooth=True,
                         fill=PANEL2, outline=EDGE, width=2)
        # gatilhos
        for name, x in (("LT", 34), ("RT", 334)):
            c.create_rectangle(x, 8, x + 32, 58, outline=EDGE, fill=PANEL)
            it[name + "_fill"] = c.create_rectangle(x + 1, 57, x + 31, 57, fill=VIOLET, outline="")
            c.create_text(x + 16, 68, text=name, fill=MUTED, font=(FONT, 8))
        it["LB"] = c.create_rectangle(32, 78, 112, 94, fill=PANEL, outline=EDGE)
        it["RB"] = c.create_rectangle(288, 78, 368, 94, fill=PANEL, outline=EDGE)
        c.create_text(72, 86, text="LB", fill=MUTED, font=(FONT, 8))
        c.create_text(328, 86, text="RB", fill=MUTED, font=(FONT, 8))
        # analógicos
        it["L3"] = c.create_oval(86, 118, 138, 170, fill=PANEL, outline=EDGE, width=3)
        it["R3"] = c.create_oval(222, 156, 274, 208, fill=PANEL, outline=EDGE, width=3)
        it["LS_dot"] = c.create_oval(104, 136, 120, 152, fill=TEAL, outline="")
        it["RS_dot"] = c.create_oval(240, 174, 256, 190, fill=AMBER, outline="")
        # d-pad
        for name, (dx, dy) in (("DPAD_UP", (0, -17)), ("DPAD_DOWN", (0, 17)),
                               ("DPAD_LEFT", (-17, 0)), ("DPAD_RIGHT", (17, 0))):
            cx, cy = 168 + dx, 190 + dy
            it[name] = c.create_rectangle(cx - 8, cy - 8, cx + 8, cy + 8, fill=PANEL, outline=EDGE)
        # botões de face
        self._face = {"Y": ("#d9b536", 292, 118), "A": ("#4aa66a", 292, 160),
                      "X": ("#4f7fd6", 270, 139), "B": ("#d9564b", 314, 139)}
        for name, (col, cx, cy) in self._face.items():
            it[name] = c.create_oval(cx - 11, cy - 11, cx + 11, cy + 11, fill=PANEL, outline=col, width=2)
            c.create_text(cx, cy, text=name, fill=col, font=(FONT, 9, "bold"))
        it["BACK"] = c.create_oval(176, 132, 188, 144, fill=PANEL, outline=EDGE)
        it["START"] = c.create_oval(214, 132, 226, 144, fill=PANEL, outline=EDGE)
        it["GUIDE"] = c.create_oval(192, 106, 210, 124, fill=PANEL, outline=EDGE, width=2)

    def _update_pad(self):
        snap = self.eng.pad.snapshot()
        sig = (frozenset(snap["buttons"]), round(snap["lt"], 2), round(snap["rt"], 2),
               tuple(round(v, 2) for v in snap["ls"]), tuple(round(v, 2) for v in snap["rs"]))
        if sig == self._pad_sig:
            return
        self._pad_sig = sig
        c, it, B = self.pad_cv, self.pad_items, snap["buttons"]
        for name, (col, _, _) in self._face.items():
            c.itemconfig(it[name], fill=col if name in B else PANEL)
        for name in ("LB", "RB", "BACK", "START", "GUIDE", "DPAD_UP", "DPAD_DOWN",
                     "DPAD_LEFT", "DPAD_RIGHT"):
            c.itemconfig(it[name], fill=AMBER if name in B else PANEL)
        for name in ("L3", "R3"):
            c.itemconfig(it[name], outline=AMBER if name in B else EDGE)
        for name, v, x in (("LT", snap["lt"], 34), ("RT", snap["rt"], 334)):
            c.coords(it[name + "_fill"], x + 1, 57 - 49 * v, x + 31, 57)
        lx, ly = snap["ls"]
        rx, ry = snap["rs"]
        c.coords(it["LS_dot"], 104 + 17 * lx, 136 - 17 * ly, 120 + 17 * lx, 152 - 17 * ly)
        c.coords(it["RS_dot"], 240 + 17 * rx, 174 - 17 * ry, 256 + 17 * rx, 190 - 17 * ry)

    # ------------------------------------------------------------- callbacks
    def _toggle_emu(self):
        self.eng.toggle_emulation()

    def _toggle_mode(self):
        self.eng.toggle_mode()

    def _toggle_menu(self):
        self.eng.toggle_menu_mode()

    def _save(self):
        if save_config():
            log("[config] salvo em " + os.path.basename(CONFIG_PATH))

    def _on_profile(self, _e=None):
        pid = PROFILE_BY_LABEL.get(self.profile_var.get())
        if pid and pid != S["profile"]:
            self.eng.release_everything()
            S["profile"] = pid
            self._sig = None
            log(f"[perfil] {PROFILES[pid]['label']} — {PROFILES[pid]['note']}")

    def _on_curve(self, _e=None):
        for code, label in CURVE_LABELS.items():
            if label == self.curve_var.get():
                S["RESPONSE"] = code
                log(f"[câmera] curva: {label}")

    def _set_opt(self, key):
        S[key] = bool(self.opt_vars[key].get())
        if key == "smart_capture" and not S[key] and state["mouse_captured"]:
            self.eng.stop_capture()
        if key == "typing_pause" and not S[key]:
            self.eng.set_typing(False)

    def _set_patterns(self, _e=None):
        S["game_patterns"] = self.pat_var.get().strip().lower()

    def _reset_profile(self):
        clear_overrides()
        self._sig = None
        log("[perfil] teclas restauradas para o padrão")

    # ------------------------------------------------------------- editor
    def _edit_key(self, norm, label):
        self._open_editor("key", norm, f"tecla {label}")

    def _edit_mouse(self, name, label):
        self._open_editor("mouse", name, label)

    def _open_editor(self, kind, name, title):
        top = tk.Toplevel(self.root)
        top.title(f"Editar {title}")
        top.configure(bg=PANEL2)
        top.resizable(False, False)
        try:
            top.transient(self.root)
            top.attributes("-topmost", True)
        except Exception:
            pass
        mode_var = tk.StringVar(value=MODE_LABELS[state["mode"]])
        act_var = tk.StringVar()
        labels = [action_label(c) for c in ACTION_ORDER]

        def cur_mode():
            return "car" if mode_var.get() == MODE_LABELS["car"] else "foot"

        def load(_e=None):
            act_var.set(action_label(get_action(kind, name, cur_mode())))

        def commit(code):
            set_override(kind, cur_mode(), name, code)
            self._sig = None
            log(f"[mapa] {title} ({MODE_LABELS[cur_mode()]}) → {action_label(code)}")
            top.destroy()

        def apply():
            lab = act_var.get()
            commit(ACTION_ORDER[labels.index(lab)] if lab in labels else "")

        tk.Label(top, text=f"Função de {title}", font=(FONT, 12, "bold"), fg=TEXT,
                 bg=PANEL2).pack(padx=18, pady=(16, 8), anchor="w")
        row = tk.Frame(top, bg=PANEL2)
        row.pack(fill="x", padx=18, pady=4)
        tk.Label(row, text="Quando", fg=MUTED, bg=PANEL2, width=8, anchor="w",
                 font=(FONT, 10)).pack(side="left")
        mc = ttk.Combobox(row, textvariable=mode_var, state="readonly", width=34,
                          values=list(MODE_LABELS.values()), font=(FONT, 10))
        mc.pack(side="left")
        mc.bind("<<ComboboxSelected>>", load)
        row = tk.Frame(top, bg=PANEL2)
        row.pack(fill="x", padx=18, pady=4)
        tk.Label(row, text="Função", fg=MUTED, bg=PANEL2, width=8, anchor="w",
                 font=(FONT, 10)).pack(side="left")
        ac = ttk.Combobox(row, textvariable=act_var, state="readonly", width=34,
                          values=labels, height=16, font=(FONT, 10))
        ac.pack(side="left")
        load()
        bf = tk.Frame(top, bg=PANEL2)
        bf.pack(fill="x", padx=18, pady=(12, 16))
        _btn(bf, "Aplicar", apply, bg=INDIGO).pack(side="left")
        _btn(bf, "Sem função", lambda: commit(""), bg=PANEL).pack(side="left", padx=8)
        _btn(bf, "Cancelar", top.destroy, bg=PANEL).pack(side="left")

    # ------------------------------------------------------------ atualização
    def _chip(self, key, text, bg):
        self.chips[key].config(text=text, bg=bg)

    def update_ui(self):
        try:
            self._refresh()
        except Exception as e:                      # a GUI nunca pode parar
            log(f"[erro] gui: {e}")
        self.root.after(50, self.update_ui)

    def _refresh(self):
        eng = self.eng
        # --- chips
        emu = state["emulation"]
        self._chip("emu", "Emulação ligada" if emu else "Emulação desligada", TEAL if emu else CORAL)
        self._chip("mode", "A pé" if state["mode"] == "foot" else "No carro",
                   OLIVE if state["mode"] == "foot" else BRONZE)
        if state["mouse_captured"]:
            r = state["capture_rect"]
            self._chip("mouse", f"Mouse capturado {r[2] - r[0]}x{r[3] - r[1]}", INDIGO)
        else:
            self._chip("mouse", "Mouse livre", MUTED)
        self._chip("game", "Jogo em foco" if state["game_focus"] else "Jogo fora de foco",
                   TEAL if state["game_focus"] else MUTED)
        if eng.menu_active():
            self._chip("input", "Menu: mouse livre", AMBER)
        elif state["typing"]:
            self._chip("input", "Digitando no chat", AMBER)
        elif state["walk"]:
            self._chip("input", "Caminhando", AMBER)
        else:
            self._chip("input", "Entrada normal", MUTED)
        self.btn_emu.config(text="Desligar emulação" if emu else "Ligar emulação")
        self.btn_mode.config(text="Modo: " + MODE_LABELS[state["mode"]])
        self.btn_menu.config(text="Voltar ao jogo" if state["menu_mode"] else "Mouse livre")

        # --- mapa (muda com modo / perfil / edição)
        pid = S["profile"]
        sig = (state["mode"], pid, json.dumps(S["overrides"].get(pid, {}), sort_keys=True))
        if sig != self._sig:
            self._sig = sig
            for norm, (rect, _t1, t2) in self.key_items.items():
                act = get_action("key", norm)
                self.kb.itemconfig(t2, text=action_short(act))
            self._key_fill = {}
            for name, b in self.mouse_btns.items():
                act = get_action("mouse", name)
                b.config(text=action_label(act))
        # --- cor das teclas
        for norm, (rect, _t1, _t2) in self.key_items.items():
            if norm in pressed:
                fill = AMBER
            else:
                fill = CAT_COLORS[action_category(get_action("key", norm))]
            if self._key_fill.get(norm) != fill:
                self._key_fill[norm] = fill
                self.kb.itemconfig(rect, fill=fill)

        self._update_pad()

        # --- log
        if self._log_seen != log_version[0]:
            self._log_seen = log_version[0]
            with log_lock:
                lines = list(log_lines)
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", "\n".join(lines))
            self.log_text.config(state="disabled")
            self.log_text.see("end")

    def on_close(self):
        save_config()
        self.eng.shutdown()
        for lst in getattr(self, "listeners", []):
            try:
                lst.stop()
            except Exception:
                pass
        self.root.destroy()


# ======================================================================== main
def _fatal(msg):
    import tkinter.messagebox as mb
    r = tk.Tk()
    r.withdraw()
    mb.showerror(APP_TITLE, msg)
    r.destroy()


def main():
    if not IS_WINDOWS:
        _fatal("Este programa só funciona no Windows (driver ViGEmBus).")
        return
    if vg is None:
        _fatal("vgamepad não instalado.\nRode: pip install vgamepad")
        return
    if keyboard is None:
        _fatal("pynput não instalado.\nRode: pip install pynput")
        return

    load_config()
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)       # sleep() de 1 ms: loop realmente a 120 Hz
        atexit.register(lambda: ctypes.windll.winmm.timeEndPeriod(1))
    except Exception:
        pass

    try:
        gamepad = vg.VX360Gamepad()
    except Exception as e:
        _fatal(f"Não foi possível criar o controle virtual.\n"
               f"Instale o driver ViGEmBus e reinicie.\n\n{e}")
        return
    X = vg.XUSB_BUTTON
    codes = {
        "A": X.XUSB_GAMEPAD_A, "B": X.XUSB_GAMEPAD_B,
        "X": X.XUSB_GAMEPAD_X, "Y": X.XUSB_GAMEPAD_Y,
        "LB": X.XUSB_GAMEPAD_LEFT_SHOULDER, "RB": X.XUSB_GAMEPAD_RIGHT_SHOULDER,
        "L3": X.XUSB_GAMEPAD_LEFT_THUMB, "R3": X.XUSB_GAMEPAD_RIGHT_THUMB,
        "START": X.XUSB_GAMEPAD_START, "BACK": X.XUSB_GAMEPAD_BACK,
        "GUIDE": X.XUSB_GAMEPAD_GUIDE,
        "DPAD_UP": X.XUSB_GAMEPAD_DPAD_UP, "DPAD_DOWN": X.XUSB_GAMEPAD_DPAD_DOWN,
        "DPAD_LEFT": X.XUSB_GAMEPAD_DPAD_LEFT, "DPAD_RIGHT": X.XUSB_GAMEPAD_DPAD_RIGHT,
    }
    pad = VirtualPad(gamepad, codes)
    eng = Engine(pad)
    log("[debug] VirtualPad criado")
    log("[debug] Engine criado")
    log("[debug] Iniciando output_loop...")
    
    threading.Thread(target=eng.output_loop, daemon=True).start()
    log("[debug] output_loop iniciado")
    

    def guard(fn):
        n = len(inspect.signature(fn).parameters)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args[:n])
            except Exception as e:
                log(f"[erro] {fn.__name__}: {e}")
        return wrapper

    kb_l = keyboard.Listener(on_press=guard(eng.on_key_press), on_release=guard(eng.on_key_release))
    ms_l = mouse.Listener(on_move=guard(eng.on_mouse_move), on_click=guard(eng.on_mouse_click),
                          on_scroll=guard(eng.on_mouse_scroll))
    kb_l.start()
    ms_l.start()

    root = tk.Tk()
    app = App(root, eng)
    app.listeners = [kb_l, ms_l]
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    log(f"[perfil] {PROFILES[S['profile']]['label']} — {PROFILES[S['profile']]['note']}")
    log("[debug] App criado, iniciando mainloop...")
    
    log("F8 ou Scroll Lock liga e desliga · Pause libera o mouse para menus")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        eng.shutdown()
        unclip_cursor()
        for lst in (kb_l, ms_l):
            try:
                lst.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()