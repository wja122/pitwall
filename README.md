# Pitwall

Modular LED matrix display system for Raspberry Pi 4. Drives a 128×192 RGB LED matrix (6× WatangTech 64×64 panels in a 2×3 grid) and exposes a Flask web interface for control. An E-ink display (Heltec Vision Master E213) shows status info over USB serial.

---

## Running

```bash
# Dev machine (no LED hardware — browser preview at http://localhost:5000)
uv run python main.py

# Pi (needs root for GPIO)
sudo .venv/bin/python main.py
```

Config is loaded from `config.json`, falling back to `config.example.json`. Copy the example and fill in your values:

```bash
cp config.example.json config.json
```

---

## Project state

### Built

| Layer | File(s) | Notes |
|---|---|---|
| Display driver | `display/driver.py` | Wraps `rgbmatrix`; stubs to `_StubMatrix` on dev machines |
| Fonts | `display/fonts.py` | F57 (5×7, advance 6px) and F35 (3×5, advance 4px) |
| Renderer | `display/renderer.py` | Drawing utilities — see API below |
| Frame buffer | `display/buffer.py` | Thread-safe capture for preview + FPS tracking |
| Module base | `modules/base.py` | `BaseModule` ABC |
| Registry | `modules/registry.py` | `@register` decorator + `discover()` auto-import |
| Clock module | `modules/clock/module.py` | Local (12hr) + UTC (24hr) + OpenWeatherMap current conditions |
| Entry point | `main.py` | Wires driver + registry + Flask preview server |

### Not yet built

- F1 timing (`modules/f1_timing/`)
- F1 countdown (`modules/f1_countdown/`)
- F1 standings (`modules/f1_standings/`)
- Weather standalone module (`modules/weather/`)
- NFL scores (`modules/nfl/`)
- Full web UI (`web/`)
- E-ink serial push (`eink/`)
- Provisioning / AP mode (`provisioning/`)
- MultiViewer auto-switch watcher

---

## Writing a module

### 1. File structure

```
modules/your_module/
├── __init__.py    # must import the class to trigger @register
└── module.py      # the implementation
```

### 2. Minimal template

```python
# modules/your_module/module.py
from __future__ import annotations
from typing import Any
from modules.base import BaseModule
from modules.registry import register
from display.fonts import F57, F35
from display.renderer import draw_text_centered, fill_rect, WIDTH, HEIGHT

@register
class YourModule(BaseModule):
    name        = 'your_module'      # must be unique; used as the config key
    description = 'What it does'
    default_fps = 10

    def __init__(self, config: dict[str, Any]) -> None:
        # Read your settings out of config here
        pass

    def start(self) -> None:
        # Start background threads, open connections, etc.
        pass

    def stop(self) -> None:
        # Signal background threads to exit (don't join — just set an event)
        pass

    def render(self, canvas: Any) -> None:
        # Called from the display thread at default_fps.
        # canvas.Fill(0, 0, 0) is already called before render() — you get a black slate.
        draw_text_centered(canvas, F57, WIDTH // 2, 90, 255, 255, 255, 'HELLO')

    def get_config(self) -> dict[str, Any]:
        return {}   # return current settings for the web UI

    def set_config(self, cfg: dict[str, Any]) -> None:
        pass        # apply settings pushed from the web UI

    def get_status(self) -> dict[str, Any]:
        return {}   # health info shown in the web UI dashboard
```

```python
# modules/your_module/__init__.py
from modules.your_module.module import YourModule
__all__ = ['YourModule']
```

### 3. Register in config.example.json

Add an entry under `modules`:
```json
"your_module": {
  "fps": 10
}
```

### 4. Thread safety

`render()` is called from the **display thread**. Everything else — `start()`, `stop()`, `set_config()`, `get_status()` — may be called from **Flask threads**. Protect shared state with `threading.Lock()`.

---

## Renderer API

All functions live in `display/renderer.py`. Import what you need:

```python
from display.renderer import (
    WIDTH, HEIGHT,          # 128, 192
    Canvas,                 # Protocol type for type hints
    fill_rect,
    draw_hline, draw_vline, draw_line,
    draw_text,
    draw_text_centered,
    draw_text_scaled,           # pixel-doubling/tripling
    draw_text_centered_scaled,
    text_width,
    text_width_scaled,
)
from display.fonts import F57, F35
```

### Primitives

```python
fill_rect(canvas, x, y, w, h, r, g, b)
draw_hline(canvas, x, y, w, r, g, b)
draw_vline(canvas, x, y, h, r, g, b)
draw_line(canvas, x1, y1, x2, y2, r, g, b)   # Bresenham
```

### Text — normal size

```python
# Returns x position after last character
x_end = draw_text(canvas, F57, x, y, r, g, b, "HELLO")
x_end = draw_text_centered(canvas, F57, cx, y, r, g, b, "HELLO")

# Width in pixels (without trailing advance gap)
w = text_width(F57, "HELLO")   # → 29px for F57
```

Text is automatically uppercased before lookup. Unknown characters are skipped (advance still applied).

### Text — scaled (2× or 3×)

```python
# scale=2 → each source pixel becomes a 2×2 block; scale=3 → 3×3, etc.
draw_text_scaled(canvas, F57, x, y, r, g, b, "72°F", scale=3)
draw_text_centered_scaled(canvas, F57, cx, y, r, g, b, "72°F", scale=3)

w = text_width_scaled(F57, "12:34", scale=3)   # → 87px
```

### Fonts

| Font | Char size | Advance | Use for |
|---|---|---|---|
| `F57` | 5×7 px | 6 px | All primary text |
| `F35` | 3×5 px | 4 px | Headers, labels, secondary info |

Characters: A–Z, 0–9, `. : - + / ! < > # % ( ) * ? ° space`

---

## Canvas API (direct pixel access)

The canvas object passed to `render()` satisfies this interface:

```python
canvas.SetPixel(x, y, r, g, b)   # 0 ≤ x < 128, 0 ≤ y < 192, 0 ≤ r/g/b ≤ 255
canvas.Fill(r, g, b)              # fill entire canvas with one color
```

The display driver calls `canvas.Fill(0, 0, 0)` before every `render()` call, so you always start from a clean black slate.

---

## Display dimensions

```
 x=0           x=127
  ┌─────────────┐  y=0
  │             │
  │  128 × 192  │
  │             │
  └─────────────┘  y=191
```

Origin is top-left. All coordinates are in pixels.

---

## Clock module config

```json
{
  "modules": {
    "clock": {
      "fps": 1,
      "api_key": "your_openweathermap_key",
      "location": "Pittsburgh, PA",
      "units": "imperial"
    }
  }
}
```

`api_key` is from [openweathermap.org](https://openweathermap.org/api). Free tier is sufficient. **New keys take up to 2 hours to activate** — the display will show `KEY INACTIVE` until then, and the full error is printed to the console.
