# PAD RP — Xbox Controller Studio

> **PT-BR** | [English below](#english)

---

## O que é

Emulador de controle Xbox 360 virtual para jogar **GTA V / FiveM / GTA VI via Xbox Remote Play** no Windows, usando apenas **teclado e mouse com a mão direita**. Feito para jogadores com mobilidade reduzida na mão esquerda (one-hand).

O programa cria um controle Xbox 360 virtual via **ViGEmBus** e mapeia teclado + mouse para os botões e analógicos em tempo real, com captura inteligente de cursor e perfil otimizado para roleplay.

## Requisitos

- Windows 10/11 (64-bit)
- Python 3.10+
- [ViGEmBus](https://github.com/ViGEm/ViGEmBus/releases) instalado
- Xbox Remote Play (ou app Xbox) instalado e configurado

```bash
pip install -r requirements.txt
```

## Como usar

```bash
python gta6-gui.py
```

1. Abra o Xbox Remote Play e conecte ao console.
2. Rode o script — a GUI abre com a emulação **ativa por padrão**.
3. Clique na janela do Remote Play para focar nela.
4. Use **F8 / Scroll Lock / LWin** para ligar/desligar a emulação e o confinamento do cursor.

## Mapeamento de teclas

### A pé (`F12` ou `Tab` para alternar modos)

| Tecla | Botão Xbox | Ação |
|-------|-----------|------|
| W / A / S / D | LS | Movimento |
| LShift / RShift | L3 | Correr |
| Mouse | RS | Câmera |
| LMB | RT | Atirar |
| RMB | LT | Mirar |
| Space | A | Pular |
| B | B | Soco |
| F | Y | Entrar/sair de veículo |
| G / R | X | Arrombar / recarregar |
| Q | RB | Cobertura |
| C | LB | Roda de armas |
| Z | R3 | Agachar |
| E / T | D-Pad → | Interagir |
| I / P / F2 | BACK | Inventário / mapa |
| 1 / 2 / 3 / 4 | D-Pad | D-Pad |
| Esc / O | START | Menu de pausa |

### No carro

| Tecla | Ação |
|-------|------|
| W | Acelerar (RT) |
| S | Frear (LT) |
| A / D | Virar (LS) |
| V | Meia aceleração |

### Teclas especiais

| Tecla | Função |
|-------|--------|
| F8 / Scroll Lock / LWin | Liga/desliga emulação + captura do cursor |
| F12 / Tab | Alterna modo: a pé / no carro |
| Pause | Mouse livre (menus) |
| Ctrl direito | Caminhar |
| T ou / | Pausa teclado no chat |
| Enter / Esc | Sai do chat |
| LCtrl | Precisão (câmera mais lenta) |

## Configuração (GUI)

- **FRICTION** — suavidade da câmera
- **SENS X / SENS Y** — sensibilidade
- **DEADZONE RS** — zona morta do analógico direito
- **DIRECT MODE** — posição do mouse = posição do stick (ideal para lockpick)
- **RESPONSE** — curva: linear ou progressiva

O status **LIVE** (ponto teal) aparece quando a emulação está ligada **e** o jogo está em foco.

## Melhorias desta versão

- Visual **PAD RP** (night-garage: ink / amber / teal / coral)
- Indicador **LIVE** em tempo real
- Detecção de foco com **debounce** (menos oscilação no Remote Play)
- Confinamento de cursor com **tolerância** (evita re-captura por 1–2 px)
- Log menos verboso e salvo ao lado do script
- Padrões de janela expandindo Xbox Remote Play / Xbox PC App

## Dependências

| Pacote | Uso |
|--------|-----|
| `vgamepad` | Controle Xbox 360 virtual via ViGEmBus |
| `pynput` | Captura de teclado e mouse |

## License

MIT

---

<a name="english"></a>
# PAD RP — Xbox Controller Studio

## What it is

A virtual Xbox 360 controller emulator for playing **GTA V / FiveM / GTA VI via Xbox Remote Play** on Windows using only **keyboard and mouse with the right hand**. Built for players with limited left-hand mobility.

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- [ViGEmBus](https://github.com/ViGEm/ViGEmBus/releases) installed
- Xbox Remote Play installed

```bash
pip install -r requirements.txt
```

## Usage

```bash
python gta6-gui.py
```

Press **F8 / Scroll Lock / LWin** to toggle emulation and cursor capture.

## License

MIT
