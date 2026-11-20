# GTA 6 Controller — One-Hand Xbox Emulator

> **PT-BR** | [English below](#english)

---

## 🎮 O que é

Emulador de controle Xbox 360 virtual para jogar **GTA 6 via Xbox Remote Play** no Windows, usando apenas **teclado e mouse com a mão direita**. Desenvolvido para jogadores com mobilidade reduzida na mão esquerda.

O programa cria um controle Xbox 360 virtual via **ViGEmBus** e mapeia teclado + mouse para os botões e analógicos do controle em tempo real.

## ⚙️ Requisitos

- Windows 10/11 (64-bit)
- Python 3.10+
- [ViGEmBus](https://github.com/ViGEm/ViGEmBus/releases) instalado
- Xbox Remote Play instalado e configurado

```
pip install -r requirements.txt
```

## ▶️ Como usar

```
python gta6-gui.py
```

1. Abra o Xbox Remote Play e conecte ao seu console.
2. Rode o script — a GUI abre com o emulador **ativo por padrão**.
3. Clique na janela do Remote Play para focar nela.
4. Pressione **LWin** para ligar/desligar a emulação e o confinamento do cursor.

## ⌨️ Mapeamento de teclas

### A pé (`F12` ou `Tab` para alternar modos)

| Tecla | Botão Xbox | Ação |
|-------|-----------|------|
| W / A / S / D | LS | Movimento |
| LShift / RShift | L3 (clique) | Correr |
| Mouse | RS | Câmera |
| LMB | RT | Atirar |
| RMB | LT | Mirar |
| Space | A | Pular |
| B | B | Soco |
| F | Y | Entrar/sair de veículo |
| G | X | Arrombar |
| R | X | Recarregar |
| Q | RB | Cobertura |
| C | LB | Roda de armas |
| Z | R3 | Agachar |
| E / T | D-Pad → | Interagir |
| I | BACK | Inventário / mapa |
| 1 / 2 / 3 / 4 | D-Pad ↑↓←→ | D-Pad |
| Esc / O | START | Menu de pausa |
| P / F2 | BACK | Mapa |

### No carro (`F12` ou `Tab` para alternar)

| Tecla | Ação |
|-------|------|
| W | Acelerar (RT) |
| S | Frear (LT) |
| A / D | Virar (LS) |
| V | Meia aceleração |

### Teclas especiais

| Tecla | Função |
|-------|--------|
| LWin | Liga/desliga emulação + captura do cursor |
| F12 / Tab | Alterna modo: a pé / no carro |
| LCtrl | Precisão (câmera mais lenta) |

## 🛠️ Configuração (GUI)

A interface gráfica expõe os seguintes controles:

- **FRICTION** — suavidade da câmera (0.50 = para imediato, 0.98 = muito deslizante)
- **SENS X / SENS Y** — sensibilidade horizontal e vertical
- **DEADZONE RS** — zona morta do analógico direito
- **RESPONSE** — curva de resposta: `linear` ou `progressive` (exponente 0.65, similar ao FiveM)

## 📦 Dependências

| Pacote | Uso |
|--------|-----|
| `vgamepad` | Controle Xbox 360 virtual via ViGEmBus |
| `pynput` | Captura de teclado e mouse |

---

<a name="english"></a>
# GTA 6 Controller — One-Hand Xbox Emulator

## What it is

A virtual Xbox 360 controller emulator for playing **GTA 6 via Xbox Remote Play** on Windows using only **keyboard and mouse with the right hand**. Built for players with limited mobility in the left hand.

The script creates a virtual Xbox 360 gamepad via **ViGEmBus** and maps keyboard + mouse to controller buttons and analog sticks in real time.

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- [ViGEmBus](https://github.com/ViGEm/ViGEmBus/releases) installed
- Xbox Remote Play installed and configured

```
pip install -r requirements.txt
```

## Usage

```
python gta6-gui.py
```

1. Open Xbox Remote Play and connect to your console.
2. Run the script — the GUI opens with emulation **enabled by default**.
3. Click on the Remote Play window to focus it.
4. Press **LWin** to toggle emulation and cursor capture on/off.

## Key Bindings

### On foot (`F12` or `Tab` to switch modes)

| Key | Xbox Button | Action |
|-----|------------|--------|
| W / A / S / D | LS | Movement |
| LShift / RShift | L3 (click) | Sprint |
| Mouse | RS | Camera |
| LMB | RT | Shoot |
| RMB | LT | Aim |
| Space | A | Jump |
| B | B | Punch |
| F | Y | Enter/exit vehicle |
| G | X | Break in |
| R | X | Reload |
| Q | RB | Cover |
| C | LB | Weapon wheel |
| Z | R3 | Crouch |
| E / T | D-Pad → | Interact |
| I | BACK | Inventory / map |
| 1 / 2 / 3 / 4 | D-Pad ↑↓←→ | D-Pad |
| Esc / O | START | Pause menu |
| P / F2 | BACK | Map |

### In vehicle (`F12` or `Tab` to switch)

| Key | Action |
|-----|--------|
| W | Accelerate (RT) |
| S | Brake (LT) |
| A / D | Steer (LS) |
| V | Half throttle |

### Special keys

| Key | Function |
|-----|----------|
| LWin | Toggle emulation + cursor capture |
| F12 / Tab | Switch mode: on foot / in vehicle |
| LCtrl | Precision mode (slower camera) |

## GUI Settings

- **FRICTION** — camera smoothness (0.50 = stops instantly, 0.98 = very slidey)
- **SENS X / SENS Y** — horizontal and vertical sensitivity
- **DEADZONE RS** — right stick deadzone
- **RESPONSE** — response curve: `linear` or `progressive` (exponent 0.65, similar to FiveM)

## Dependencies

| Package | Purpose |
|---------|---------|
| `vgamepad` | Virtual Xbox 360 controller via ViGEmBus |
| `pynput` | Keyboard and mouse capture |

## License

MIT
