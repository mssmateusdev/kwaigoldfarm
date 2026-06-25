# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              KWAI BOT - Interface Gráfica                    ║
║        GUI moderna com CustomTkinter para o Kwai Bot         ║
╚══════════════════════════════════════════════════════════════╝
"""

import sys
import os
import threading
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

# Resolve diretório base (compatível com .exe do PyInstaller)
if getattr(sys, "frozen", False):
    SCRIPT_DIR = Path(sys.executable).parent.resolve()
else:
    SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from kwai_bot import KwaiBot, ADB_PATH

# ─────────────────────────────────────────────────────────────
# Tema & Constantes
# ─────────────────────────────────────────────────────────────

# Paleta de cores premium
COLORS = {
    "bg_dark":       "#0D0F14",
    "bg_card":       "#161922",
    "bg_card_hover": "#1C2030",
    "bg_input":      "#1A1D28",
    "accent":        "#FF6B2C",     # Laranja Kwai
    "accent_hover":  "#FF8548",
    "accent_dark":   "#CC5623",
    "accent2":       "#FFB800",     # Dourado (gold)
    "accent2_dark":  "#CC9300",
    "green":         "#22C55E",
    "green_dark":    "#16A34A",
    "red":           "#EF4444",
    "red_dark":      "#DC2626",
    "yellow":        "#FACC15",
    "blue":          "#3B82F6",
    "purple":        "#A855F7",
    "text_primary":  "#F1F5F9",
    "text_secondary":"#94A3B8",
    "text_dim":      "#64748B",
    "border":        "#2A2F3E",
    "border_light":  "#3A4055",
    "transparent":   "transparent",
}

FONT_FAMILY = "Segoe UI"
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 720


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def create_app_icon() -> str:
    """Cria um ícone simples para a janela do app."""
    icon_path = SCRIPT_DIR / "icon.png"
    if icon_path.exists():
        return str(icon_path)

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Círculo de fundo gradiente (laranja)
    draw.ellipse([2, 2, size - 2, size - 2], fill="#FF6B2C")
    # Moeda interior
    draw.ellipse([12, 12, size - 12, size - 12], fill="#FFB800")
    # K no centro
    try:
        font = ImageFont.truetype("segoeui.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    draw.text((size // 2, size // 2), "K", fill="#0D0F14", font=font, anchor="mm")

    img.save(str(icon_path))
    return str(icon_path)


def list_adb_devices() -> list[dict]:
    """Lista dispositivos ADB conectados com informações básicas."""
    try:
        result = subprocess.run(
            [ADB_PATH, "devices", "-l"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        output = result.stdout.strip()
    except Exception:
        return []

    devices = []
    for line in output.split("\n"):
        if "\tdevice" in line or " device " in line:
            parts = line.split()
            serial = parts[0]
            # Parse extra info like model:xxx
            model = serial
            for p in parts:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]

            devices.append({"serial": serial, "model": model, "status": "Online"})
    return devices


# ─────────────────────────────────────────────────────────────
# Widget: Device Dropdown (botão compacto + popup flutuante)
# ─────────────────────────────────────────────────────────────

class DeviceDropdown(ctk.CTkFrame):
    """Botão compacto de seleção de dispositivo com dropdown popup."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._selected_serial: str | None = None
        self._selected_model: str | None = None
        self._devices: list[dict] = []
        self._popup_window = None

        # ── Botão principal (mostra dispositivo selecionado) ──
        self.device_btn = ctk.CTkButton(
            self,
            text="📱  Selecionar dispositivo  ▾",
            width=220, height=36,
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["bg_input"],
            hover_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            border_width=1, border_color=COLORS["border"],
            corner_radius=8,
            anchor="w",
            command=self._toggle_popup,
        )
        self.device_btn.pack(fill="x")

        # Auto-scan on init
        self.after(500, self._auto_scan)

    def _auto_scan(self):
        """Busca dispositivos na inicialização sem abrir popup."""
        self._devices = list_adb_devices()
        if self._devices:
            self._select_device(self._devices[0])

    def _select_device(self, device: dict):
        """Seleciona um dispositivo e atualiza o botão."""
        self._selected_serial = device["serial"]
        self._selected_model = device["model"]
        self.device_btn.configure(
            text=f"  ● {device['model']}  —  {device['serial']}  ▾",
            text_color=COLORS["text_primary"],
        )

    def _toggle_popup(self):
        """Abre/fecha o popup de dispositivos."""
        if self._popup_window and self._popup_window.winfo_exists():
            self._close_popup()
            return
        self._open_popup()

    def _open_popup(self):
        """Abre o popup com a lista de dispositivos."""
        # Refresh devices
        self._devices = list_adb_devices()

        # Calcula posição do popup abaixo do botão
        btn_x = self.device_btn.winfo_rootx()
        btn_y = self.device_btn.winfo_rooty() + self.device_btn.winfo_height() + 4
        popup_width = max(self.device_btn.winfo_width(), 360)

        # Cria toplevel sem borda
        self._popup_window = ctk.CTkToplevel(self)
        self._popup_window.withdraw()  # Esconde até posicionar
        self._popup_window.overrideredirect(True)
        self._popup_window.configure(fg_color=COLORS["bg_card"])
        self._popup_window.attributes("-topmost", True)

        # Frame com borda arredondada
        popup_frame = ctk.CTkFrame(
            self._popup_window,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border_light"],
        )
        popup_frame.pack(fill="both", expand=True, padx=1, pady=1)

        # Header do popup
        header = ctk.CTkFrame(popup_frame, fg_color="transparent", height=36)
        header.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            header, text="Instâncias",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        # Botão refresh
        ctk.CTkButton(
            header, text="⟳", width=28, height=28,
            font=(FONT_FAMILY, 14),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            corner_radius=6,
            command=lambda: self._refresh_popup(popup_frame),
        ).pack(side="right")

        # Lista de dispositivos
        self._render_device_list(popup_frame)

        # Calcula altura do popup
        n_devices = max(len(self._devices), 1)
        popup_height = 48 + (n_devices * 62) + 12  # header + cards + padding
        popup_height = min(popup_height, 300)  # max height

        self._popup_window.geometry(f"{popup_width}x{popup_height}+{btn_x}+{btn_y}")
        self._popup_window.deiconify()

        # Fecha popup ao clicar fora
        self._popup_window.bind("<FocusOut>", self._on_focus_out)
        self._popup_window.focus_force()

    def _render_device_list(self, popup_frame):
        """Renderiza os cards de dispositivo dentro do popup."""
        # Remove cards antigos (se existir re-render)
        for widget in popup_frame.winfo_children():
            if isinstance(widget, ctk.CTkFrame) and hasattr(widget, "_is_device_card"):
                widget.destroy()

        if not self._devices:
            empty = ctk.CTkFrame(popup_frame, fg_color="transparent", height=50)
            empty._is_device_card = True
            empty.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(
                empty,
                text="Nenhum dispositivo encontrado.\nConecte via USB e clique ⟳",
                font=(FONT_FAMILY, 11),
                text_color=COLORS["text_dim"],
                justify="center",
            ).pack(expand=True)
            return

        for dev in self._devices:
            is_sel = dev["serial"] == self._selected_serial
            card = self._create_device_card(popup_frame, dev, is_sel)
            card._is_device_card = True
            card.pack(fill="x", padx=10, pady=(0, 4))

    def _create_device_card(self, parent, device: dict, is_selected: bool) -> ctk.CTkFrame:
        """Cria um card de dispositivo para o popup."""
        border_color = COLORS["green"] if is_selected else COLORS["border"]
        card = ctk.CTkFrame(
            parent, fg_color=COLORS["bg_dark"], corner_radius=10,
            border_width=1, border_color=border_color, height=54,
            cursor="hand2",
        )
        card.pack_propagate(False)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=6)
        inner.grid_columnconfigure(1, weight=1)

        # Checkmark
        check_text = "✓" if is_selected else " "
        check_color = COLORS["green"] if is_selected else COLORS["text_dim"]
        check = ctk.CTkLabel(
            inner, text=check_text, width=18,
            font=(FONT_FAMILY, 13, "bold"),
            text_color=check_color,
        )
        check.grid(row=0, column=0, rowspan=2, padx=(0, 8), sticky="w")

        # Model
        model_lbl = ctk.CTkLabel(
            inner, text=device.get("model", "Unknown"),
            font=(FONT_FAMILY, 12, "bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        model_lbl.grid(row=0, column=1, sticky="w")

        # Serial
        serial_lbl = ctk.CTkLabel(
            inner, text=device.get("serial", ""),
            font=(FONT_FAMILY, 9),
            text_color=COLORS["text_dim"],
            anchor="w",
        )
        serial_lbl.grid(row=1, column=1, sticky="w")

        # Status
        status = device.get("status", "Online")
        status_color = COLORS["green"] if status == "Online" else COLORS["red"]
        status_lbl = ctk.CTkLabel(
            inner, text=status,
            font=(FONT_FAMILY, 10, "bold"),
            text_color=status_color,
        )
        status_lbl.grid(row=0, column=2, rowspan=2, padx=(8, 0), sticky="e")

        # Bind click
        def on_click(e=None, d=device):
            self._select_device(d)
            self._close_popup()

        for widget in [card, inner, check, model_lbl, serial_lbl, status_lbl]:
            widget.bind("<Button-1>", on_click)
            widget.configure(cursor="hand2")

        return card

    def _refresh_popup(self, popup_frame):
        """Atualiza a lista de dispositivos dentro do popup aberto."""
        self._devices = list_adb_devices()
        self._render_device_list(popup_frame)

        # Reajusta tamanho
        if self._popup_window and self._popup_window.winfo_exists():
            n_devices = max(len(self._devices), 1)
            popup_height = 48 + (n_devices * 62) + 12
            popup_height = min(popup_height, 300)
            current_geom = self._popup_window.geometry()
            # parse width from geometry
            w = int(current_geom.split("x")[0])
            x_y = current_geom.split("+", 1)[1]
            self._popup_window.geometry(f"{w}x{popup_height}+{x_y}")

    def _on_focus_out(self, event=None):
        """Fecha o popup quando perde o foco."""
        if self._popup_window and self._popup_window.winfo_exists():
            # Delay para verificar se o foco foi para um filho do popup ou se o mouse está dentro
            self._popup_window.after(150, self._check_focus)

    def _check_focus(self):
        """Verifica se o foco saiu realmente do popup."""
        if not self._popup_window or not self._popup_window.winfo_exists():
            return
        try:
            # 1. Se o foco ainda está em algum elemento filho do popup, não fecha
            focused = self._popup_window.focus_get()
            if focused and str(focused).startswith(str(self._popup_window)):
                return

            # 2. Se o mouse está dentro dos limites do popup, não fecha
            mouse_x = self._popup_window.winfo_pointerx()
            mouse_y = self._popup_window.winfo_pointery()

            popup_x = self._popup_window.winfo_rootx()
            popup_y = self._popup_window.winfo_rooty()
            popup_w = self._popup_window.winfo_width()
            popup_h = self._popup_window.winfo_height()

            if (popup_x <= mouse_x <= popup_x + popup_w) and (popup_y <= mouse_y <= popup_y + popup_h):
                return

            # 3. Se o mouse está sobre o botão de dropdown, deixa o toggle do botão cuidar do fechamento
            btn_x = self.device_btn.winfo_rootx()
            btn_y = self.device_btn.winfo_rooty()
            btn_w = self.device_btn.winfo_width()
            btn_h = self.device_btn.winfo_height()

            if (btn_x <= mouse_x <= btn_x + btn_w) and (btn_y <= mouse_y <= btn_y + btn_h):
                return

            self._close_popup()
        except Exception:
            self._close_popup()

    def _close_popup(self):
        """Fecha o popup."""
        if self._popup_window and self._popup_window.winfo_exists():
            self._popup_window.destroy()
        self._popup_window = None

    @property
    def selected_device(self) -> str | None:
        return self._selected_serial


# ─────────────────────────────────────────────────────────────
# Widget: Stat Card
# ─────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    """Card de estatística individual com ícone, valor e label."""

    def __init__(self, parent, icon_text: str, label: str, value: str = "0",
                 accent_color: str = COLORS["accent"], **kwargs):
        super().__init__(parent, fg_color=COLORS["bg_card"], corner_radius=14,
                         border_width=1, border_color=COLORS["border"], **kwargs)

        self.grid_columnconfigure(0, weight=1)

        # Ícone
        self.icon_label = ctk.CTkLabel(
            self, text=icon_text,
            font=(FONT_FAMILY, 22),
            text_color=accent_color,
        )
        self.icon_label.grid(row=0, column=0, pady=(14, 2))

        # Valor
        self.value_label = ctk.CTkLabel(
            self, text=value,
            font=(FONT_FAMILY, 28, "bold"),
            text_color=COLORS["text_primary"],
        )
        self.value_label.grid(row=1, column=0, pady=(0, 2))

        # Label
        self.name_label = ctk.CTkLabel(
            self, text=label,
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_dim"],
        )
        self.name_label.grid(row=2, column=0, pady=(0, 14))

    def set_value(self, value: str):
        self.value_label.configure(text=value)


# ─────────────────────────────────────────────────────────────
# Widget: Log Console
# ─────────────────────────────────────────────────────────────

class LogConsole(ctk.CTkFrame):
    """Console de log estilizado com scroll e cores por nível."""

    TAG_COLORS = {
        "info":    COLORS["blue"],
        "warning": COLORS["yellow"],
        "error":   COLORS["red"],
        "debug":   COLORS["text_dim"],
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=COLORS["bg_card"], corner_radius=14,
                         border_width=1, border_color=COLORS["border"], **kwargs)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent", height=36)
        header.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(
            header, text="Console",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left")

        self.clear_btn = ctk.CTkButton(
            header, text="Limpar", width=60, height=26,
            font=(FONT_FAMILY, 11),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            text_color=COLORS["text_dim"],
            corner_radius=6,
            command=self.clear,
        )
        self.clear_btn.pack(side="right")

        # Textbox
        self.textbox = ctk.CTkTextbox(
            self,
            font=("Consolas", 12),
            fg_color=COLORS["bg_dark"],
            text_color=COLORS["text_secondary"],
            corner_radius=10,
            border_width=0,
            wrap="word",
            state="disabled",
            activate_scrollbars=True,
        )
        self.textbox.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        # Configura tags de cor
        for tag, color in self.TAG_COLORS.items():
            self.textbox._textbox.tag_config(tag, foreground=color)

    def append(self, level: str, message: str):
        """Adiciona uma linha ao log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = level.lower() if level.lower() in self.TAG_COLORS else "info"

        prefixes = {
            "info": "[i]",
            "warning": "[!]",
            "error": "[X]",
            "debug": ">>",
        }
        prefix = prefixes.get(tag, "[i]")

        self.textbox.configure(state="normal")
        line = f"[{timestamp}] {prefix} {message}\n"
        self.textbox._textbox.insert("end", line, tag)
        self.textbox._textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self):
        self.textbox.configure(state="normal")
        self.textbox._textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")


# ─────────────────────────────────────────────────────────────
# App Principal
# ─────────────────────────────────────────────────────────────

class KwaiBotGUI(ctk.CTk):
    """Janela principal do Kwai Bot."""

    def __init__(self):
        super().__init__()

        # ── Configuração da janela ──
        self.title("Kwai Bot - Auto Gold")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(820, 640)
        self.configure(fg_color=COLORS["bg_dark"])

        # Ícone
        try:
            icon_path = create_app_icon()
            self.iconbitmap(default="")
            icon_image = ctk.CTkImage(
                light_image=Image.open(icon_path),
                dark_image=Image.open(icon_path),
                size=(32, 32),
            )
        except Exception:
            icon_image = None

        ctk.set_appearance_mode("dark")

        # ── Estado ──
        self.bot: KwaiBot | None = None
        self.bot_thread: threading.Thread | None = None
        self._status = "idle"
        self._start_time = None

        # ── Layout principal ──
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # Log pega espaço restante

        self._build_header(icon_image)
        self._build_controls()
        self._build_stats_bar()
        self._build_log_console()
        self._build_footer()

        # Timer para atualizar tempo decorrido
        self._tick()

        # Fechar corretamente
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── Header ───────────────────────────────────────────

    def _build_header(self, icon_image):
        header = ctk.CTkFrame(self, fg_color="transparent", height=70)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))
        header.grid_columnconfigure(1, weight=1)

        # Logo / Título
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="w")

        if icon_image:
            ctk.CTkLabel(title_frame, text="", image=icon_image).pack(side="left", padx=(0, 10))

        title_text = ctk.CTkFrame(title_frame, fg_color="transparent")
        title_text.pack(side="left")

        ctk.CTkLabel(
            title_text, text="KWAI BOT",
            font=(FONT_FAMILY, 24, "bold"),
            text_color=COLORS["accent"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_text, text="Auto Gold  |  Assista videos automaticamente",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w")

        # Status badge
        self.status_frame = ctk.CTkFrame(header, fg_color=COLORS["bg_card"],
                                          corner_radius=20, border_width=1,
                                          border_color=COLORS["border"])
        self.status_frame.grid(row=0, column=1, sticky="e")

        self.status_dot = ctk.CTkLabel(
            self.status_frame, text="\u2B24", width=12,
            font=(FONT_FAMILY, 8),
            text_color=COLORS["text_dim"],
        )
        self.status_dot.pack(side="left", padx=(14, 4), pady=8)

        self.status_label = ctk.CTkLabel(
            self.status_frame, text="PARADO",
            font=(FONT_FAMILY, 11, "bold"),
            text_color=COLORS["text_dim"],
        )
        self.status_label.pack(side="left", padx=(0, 14), pady=8)

    # ─── Controles ────────────────────────────────────────

    def _build_controls(self):
        controls = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=14,
                                 border_width=1, border_color=COLORS["border"])
        controls.grid(row=1, column=0, sticky="ew", padx=20, pady=(12, 0))

        # Linha 1: Inputs + Botões
        row1 = ctk.CTkFrame(controls, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(12, 0))
        row1.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        pad_opts = {"padx": 6, "pady": 0}

        # ── Coluna 0: Modo ──
        col0 = ctk.CTkFrame(row1, fg_color="transparent")
        col0.grid(row=0, column=0, sticky="ew", **pad_opts)

        ctk.CTkLabel(col0, text="Modo", font=(FONT_FAMILY, 11),
                     text_color=COLORS["text_dim"]).pack(anchor="w")

        self.modo_var = ctk.StringVar(value="Vídeos")
        self.modo_dropdown = ctk.CTkOptionMenu(
            col0, variable=self.modo_var, values=["Vídeos", "Anúncios"],
            width=110, height=36, font=(FONT_FAMILY, 12), corner_radius=8,
            fg_color=COLORS["bg_input"], button_color=COLORS["border"],
            button_hover_color=COLORS["accent"], text_color=COLORS["text_primary"],
            dropdown_font=(FONT_FAMILY, 12), dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["border"], dropdown_text_color=COLORS["text_primary"]
        )
        self.modo_dropdown.pack(anchor="w", pady=(4, 0))

        # ── Coluna 1: Videos ──
        col1 = ctk.CTkFrame(row1, fg_color="transparent")
        col1.grid(row=0, column=1, sticky="ew", **pad_opts)

        ctk.CTkLabel(col1, text="Videos", font=(FONT_FAMILY, 11),
                     text_color=COLORS["text_dim"]).pack(anchor="w")

        self.videos_var = ctk.StringVar(value="100")
        self.videos_entry = ctk.CTkEntry(
            col1, textvariable=self.videos_var, width=90, height=36,
            font=(FONT_FAMILY, 13), corner_radius=8,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        )
        self.videos_entry.pack(anchor="w", pady=(4, 0))

        # ── Coluna 2: Tempo Min ──
        col2 = ctk.CTkFrame(row1, fg_color="transparent")
        col2.grid(row=0, column=2, sticky="ew", **pad_opts)

        ctk.CTkLabel(col2, text="Tempo Min (s)", font=(FONT_FAMILY, 11),
                     text_color=COLORS["text_dim"]).pack(anchor="w")

        self.tempo_min_var = ctk.StringVar(value="15")
        self.tempo_min_entry = ctk.CTkEntry(
            col2, textvariable=self.tempo_min_var, width=90, height=36,
            font=(FONT_FAMILY, 13), corner_radius=8,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        )
        self.tempo_min_entry.pack(anchor="w", pady=(4, 0))

        # ── Coluna 3: Tempo Max ──
        col3 = ctk.CTkFrame(row1, fg_color="transparent")
        col3.grid(row=0, column=3, sticky="ew", **pad_opts)

        ctk.CTkLabel(col3, text="Tempo Max (s)", font=(FONT_FAMILY, 11),
                     text_color=COLORS["text_dim"]).pack(anchor="w")

        self.tempo_max_var = ctk.StringVar(value="35")
        self.tempo_max_entry = ctk.CTkEntry(
            col3, textvariable=self.tempo_max_var, width=90, height=36,
            font=(FONT_FAMILY, 13), corner_radius=8,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        )
        self.tempo_max_entry.pack(anchor="w", pady=(4, 0))

        # ── Coluna 4: Toggle + Botões ──
        col4 = ctk.CTkFrame(row1, fg_color="transparent")
        col4.grid(row=0, column=4, sticky="ew", **pad_opts)

        # Pausas toggle
        self.pausas_var = ctk.BooleanVar(value=False)
        self.pausas_check = ctk.CTkSwitch(
            col4, text="Pausas longas",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_dim"],
            variable=self.pausas_var,
            progress_color=COLORS["accent"],
            button_color=COLORS["text_secondary"],
            button_hover_color=COLORS["accent_hover"],
        )
        self.pausas_check.pack(anchor="w", pady=(0, 4))

        # Anti-Emulador toggle
        self.anti_emulador_var = ctk.BooleanVar(value=True)
        self.anti_emulador_check = ctk.CTkSwitch(
            col4, text="Anti-Emulador",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_dim"],
            variable=self.anti_emulador_var,
            progress_color=COLORS["accent"],
            button_color=COLORS["text_secondary"],
            button_hover_color=COLORS["accent_hover"],
        )
        self.anti_emulador_check.pack(anchor="w", pady=(0, 8))
        # Botões
        btn_frame = ctk.CTkFrame(col4, fg_color="transparent")
        btn_frame.pack(anchor="w")

        self.start_btn = ctk.CTkButton(
            btn_frame, text="\u25B6  Iniciar", width=110, height=36,
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color="#FFFFFF", corner_radius=10,
            command=self._on_start,
        )
        self.start_btn.pack(side="left", padx=(0, 6))

        self.pause_btn = ctk.CTkButton(
            btn_frame, text="\u23F8", width=36, height=36,
            font=(FONT_FAMILY, 14),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            text_color=COLORS["text_secondary"], corner_radius=10,
            command=self._on_pause,
            state="disabled",
        )
        self.pause_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            btn_frame, text="\u25A0", width=36, height=36,
            font=(FONT_FAMILY, 14),
            fg_color=COLORS["bg_input"], hover_color=COLORS["red_dark"],
            text_color=COLORS["text_secondary"], corner_radius=10,
            command=self._on_stop,
            state="disabled",
        )
        self.stop_btn.pack(side="left")

        # ── Linha 2: Device Dropdown (compacto, integrado no card) ──
        separator = ctk.CTkFrame(controls, fg_color=COLORS["border"], height=1)
        separator.pack(fill="x", padx=16, pady=(10, 0))

        row2 = ctk.CTkFrame(controls, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(8, 12))
        row2.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row2, text="Dispositivo",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_dim"],
        ).grid(row=0, column=0, sticky="w", padx=(6, 10))

        self.device_dropdown = DeviceDropdown(row2)
        self.device_dropdown.grid(row=0, column=1, sticky="ew")

    # ─── Stats Bar ────────────────────────────────────────

    def _build_stats_bar(self):
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.grid(row=2, column=0, sticky="new", padx=20, pady=(12, 0))
        stats_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.stat_videos = StatCard(stats_frame, "\U0001F3AC", "Videos",
                                     accent_color=COLORS["accent"])
        self.stat_videos.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.stat_swipes = StatCard(stats_frame, "\u2B06", "Swipes",
                                     accent_color=COLORS["blue"])
        self.stat_swipes.grid(row=0, column=1, sticky="ew", padx=6)

        self.stat_tempo = StatCard(stats_frame, "\u23F1", "Tempo",
                                    accent_color=COLORS["purple"])
        self.stat_tempo.grid(row=0, column=2, sticky="ew", padx=6)

        self.stat_golds = StatCard(stats_frame, "\U0001FA99", "Golds Est.",
                                    accent_color=COLORS["accent2"])
        self.stat_golds.grid(row=0, column=3, sticky="ew", padx=6)

        self.stat_erros = StatCard(stats_frame, "\u26A0", "Erros",
                                    accent_color=COLORS["red"])
        self.stat_erros.grid(row=0, column=4, sticky="ew", padx=(6, 0))

    # ─── Log Console ──────────────────────────────────────

    def _build_log_console(self):
        self.log_console = LogConsole(self)
        self.log_console.grid(row=3, column=0, sticky="nsew", padx=20, pady=(12, 0))
        self.grid_rowconfigure(3, weight=1)

    # ─── Footer ───────────────────────────────────────────

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="transparent", height=32)
        footer.grid(row=4, column=0, sticky="ew", padx=20, pady=(6, 10))
        footer.grid_columnconfigure(1, weight=1)

        # Progresso
        self.progress_bar = ctk.CTkProgressBar(
            footer, height=6, corner_radius=3,
            fg_color=COLORS["bg_card"],
            progress_color=COLORS["accent"],
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.progress_bar.set(0)
        footer.grid_columnconfigure(0, weight=1)

        self.progress_label = ctk.CTkLabel(
            footer, text="0 / 0",
            font=(FONT_FAMILY, 11),
            text_color=COLORS["text_dim"],
        )
        self.progress_label.grid(row=0, column=1, sticky="e")

        # Device info
        self.device_label = ctk.CTkLabel(
            footer, text="Nenhum dispositivo",
            font=(FONT_FAMILY, 10),
            text_color=COLORS["text_dim"],
        )
        self.device_label.grid(row=1, column=0, sticky="w", columnspan=2, pady=(2, 0))

    # ─── Ações ────────────────────────────────────────────

    def _on_start(self):
        """Inicia o bot."""
        # Validar dispositivo selecionado
        selected_device = self.device_dropdown.selected_device
        if not selected_device:
            self.log_console.append("error", "Selecione um dispositivo antes de iniciar!")
            return

        # Validar inputs
        try:
            total_videos = int(self.videos_var.get())
            tempo_min = int(self.tempo_min_var.get())
            tempo_max = int(self.tempo_max_var.get())
        except ValueError:
            self.log_console.append("error", "Valores invalidos! Use numeros inteiros.")
            return

        if tempo_min >= tempo_max:
            self.log_console.append("error", "Tempo Min deve ser menor que Tempo Max!")
            return

        if total_videos < 1:
            self.log_console.append("error", "Numero de videos deve ser pelo menos 1!")
            return

        config = {
            "total_videos": total_videos,
            "tempo_min": tempo_min,
            "tempo_max": tempo_max,
            "pausas": self.pausas_var.get(),
            "device_id": selected_device,
            "modo": self.modo_var.get(),
            "anti_emulador": self.anti_emulador_var.get(),
        }

        callbacks = {
            "on_log": self._cb_log,
            "on_stats": self._cb_stats,
            "on_status": self._cb_status,
            "on_progress": self._cb_progress,
            "on_device_info": self._cb_device_info,
        }

        self.bot = KwaiBot(config, callbacks)
        self._start_time = datetime.now()
        self.log_console.append("info", f"Dispositivo selecionado: {selected_device}")

        # Desabilitar controles
        self._set_controls_state(running=True)

        # Iniciar thread
        self.bot_thread = threading.Thread(target=self.bot.executar, daemon=True)
        self.bot_thread.start()

    def _on_pause(self):
        """Pausa/retoma o bot."""
        if self.bot and self.bot.esta_rodando:
            self.bot.pausar()
            if self.bot.esta_pausado:
                self.pause_btn.configure(text="\u25B6")
            else:
                self.pause_btn.configure(text="\u23F8")

    def _on_stop(self):
        """Para o bot."""
        if self.bot:
            self.bot.parar()
            self.log_console.append("warning", "Parando bot...")

    def _on_close(self):
        """Fecha a janela."""
        if self.bot and self.bot.esta_rodando:
            self.bot.parar()
            time.sleep(0.5)
        self.destroy()

    def _set_controls_state(self, running: bool):
        """Habilita/desabilita controles conforme estado."""
        state_input = "disabled" if running else "normal"
        state_btns = "normal" if running else "disabled"

        self.videos_entry.configure(state=state_input)
        self.tempo_min_entry.configure(state=state_input)
        self.tempo_max_entry.configure(state=state_input)
        self.pausas_check.configure(state=state_input)

        self.pause_btn.configure(state=state_btns)
        self.stop_btn.configure(state=state_btns)

        if running:
            self.start_btn.configure(state="disabled",
                                      fg_color=COLORS["text_dim"],
                                      text="\u25B6  Rodando...")
        else:
            self.start_btn.configure(state="normal",
                                      fg_color=COLORS["accent"],
                                      text="\u25B6  Iniciar")
            self.pause_btn.configure(text="\u23F8")

    # ─── Callbacks (chamados da thread do bot) ────────────

    def _cb_log(self, level: str, message: str):
        self.after(0, self.log_console.append, level, message)

    def _cb_stats(self, stats: dict):
        self.after(0, self._update_stats, stats)

    def _cb_status(self, status: str):
        self.after(0, self._update_status, status)

    def _cb_progress(self, current: int, total: int):
        self.after(0, self._update_progress, current, total)

    def _cb_device_info(self, info: dict):
        self.after(0, self._update_device, info)

    # ─── Atualizações de UI ───────────────────────────────

    def _update_stats(self, stats: dict):
        self.stat_videos.set_value(str(stats.get("videos_assistidos", 0)))
        self.stat_swipes.set_value(str(stats.get("swipes", 0)))
        self.stat_erros.set_value(str(stats.get("erros", 0)))

        # Tempo formatado
        total_s = stats.get("tempo_total", 0)
        mins = int(total_s) // 60
        secs = int(total_s) % 60
        self.stat_tempo.set_value(f"{mins}:{secs:02d}")

        # Golds estimados (aproximação)
        golds = stats.get("videos_assistidos", 0) * 10
        self.stat_golds.set_value(f"~{golds}")

    def _update_status(self, status: str):
        self._status = status

        status_map = {
            "running":  ("RODANDO",   COLORS["green"]),
            "paused":   ("PAUSADO",   COLORS["yellow"]),
            "stopped":  ("PARADO",    COLORS["red"]),
            "finished": ("FINALIZADO", COLORS["accent2"]),
            "idle":     ("PARADO",    COLORS["text_dim"]),
        }

        text, color = status_map.get(status, ("PARADO", COLORS["text_dim"]))
        self.status_label.configure(text=text, text_color=color)
        self.status_dot.configure(text_color=color)

        if status in ("stopped", "finished"):
            self._set_controls_state(running=False)

    def _update_progress(self, current: int, total: int):
        if total > 0:
            self.progress_bar.set(current / total)
        self.progress_label.configure(text=f"{current} / {total}")

    def _update_device(self, info: dict):
        marca = info.get("marca", "?")
        modelo = info.get("modelo", "?")
        android = info.get("android", "?")
        self.device_label.configure(
            text=f"{marca} {modelo}  |  Android {android}  |  ID: {info.get('id', '?')}",
            text_color=COLORS["green"],
        )

    # ─── Timer para tempo decorrido ───────────────────────

    def _tick(self):
        """Atualiza informações periódicas."""
        if self._status == "running" and self._start_time:
            elapsed = datetime.now() - self._start_time
            mins = int(elapsed.total_seconds()) // 60
            secs = int(elapsed.total_seconds()) % 60
            # Atualiza o stat de tempo com tempo real da sessão
            self.stat_tempo.set_value(f"{mins}:{secs:02d}")

        self.after(1000, self._tick)


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    app = KwaiBotGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
