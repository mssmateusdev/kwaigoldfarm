# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                    KWAI BOT - Auto Gold                      ║
║          Automação ADB para assistir vídeos no Kwai          ║
║              e acumular Kwai Golds passivamente              ║
╚══════════════════════════════════════════════════════════════╝

Requisitos:
  - Python 3.8+
  - Dispositivo Android conectado via USB (com Depuração USB ativada)
  - adb.exe no mesmo diretório (ou no PATH)
  - App Kwai instalado no dispositivo

Uso CLI:
  python kwai_bot.py                     # Roda com config padrão
  python kwai_bot.py --videos 200        # Assiste 200 vídeos
  python kwai_bot.py --tempo-min 20      # Mínimo 20s por vídeo
  python kwai_bot.py --tempo-max 45      # Máximo 45s por vídeo
  python kwai_bot.py --pausas            # Ativa pausas longas periódicas

Uso GUI:
  python kwai_gui.py
"""

import subprocess
import time
import random
import argparse
import sys
import re
import os
import logging
import uiautomator2 as u2
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# Configuração
# ─────────────────────────────────────────────────────────────

def _get_base_dir() -> Path:
    """Retorna o diretório base: o diretório do .exe ou do .py."""
    if getattr(sys, "frozen", False):
        # Rodando como .exe (PyInstaller)
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()

SCRIPT_DIR = _get_base_dir()
ADB_PATH = str(SCRIPT_DIR / "adb.exe")


KWAI_PACKAGES = [
    "com.kwai.video",
    "com.smile.gifmaker",
]

KWAI_ACTIVITIES = [
    "com.yxcorp.gifshow.HomeActivity",
    "com.kwai.video.HomeActivity",
]


# ─────────────────────────────────────────────────────────────
# Logger com cores no terminal
# ─────────────────────────────────────────────────────────────

class ColorFormatter(logging.Formatter):
    """Formatter com cores ANSI para o terminal."""

    COLORS = {
        logging.DEBUG: "\033[90m",
        logging.INFO: "\033[96m",
        logging.WARNING: "\033[93m",
        logging.ERROR: "\033[91m",
        logging.CRITICAL: "\033[95m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        timestamp = datetime.now().strftime("%H:%M:%S")
        icons = {
            logging.DEBUG: ">>",
            logging.INFO: "[i]",
            logging.WARNING: "[!]",
            logging.ERROR: "[X]",
            logging.CRITICAL: "[!!]",
        }
        icon = icons.get(record.levelno, "")
        return f"{color}[{timestamp}] {icon} {record.getMessage()}{self.RESET}"


def setup_logger():
    """Configura o logger principal."""
    logger = logging.getLogger("kwaibot")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(ColorFormatter())
        logger.addHandler(console)

        log_file = SCRIPT_DIR / "kwai_bot.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(file_handler)

    return logger


log = setup_logger()


# ─────────────────────────────────────────────────────────────
# Classe principal do Bot
# ─────────────────────────────────────────────────────────────

class KwaiBot:
    """Automação ADB para assistir vídeos no Kwai.

    Callbacks opcionais (para GUI):
        on_log(level: str, message: str)     – chamado a cada log
        on_stats(stats: dict)                – chamado quando stats mudam
        on_status(status: str)               – "running", "paused", "stopped", "finished"
        on_progress(current: int, total: int)– progresso do vídeo atual
        on_device_info(info: dict)           – info do dispositivo conectado
    """

    def __init__(self, config: dict, callbacks: dict | None = None):
        self.config = config
        self.adb = ADB_PATH
        self.device_id = None
        self.d = None  # Instância do uiautomator2
        self.screen_width = 0
        self.screen_height = 0
        self.kwai_package = None
        self.kwai_activity = None

        # Controle de execução
        self._running = False
        self._paused = False

        # Callbacks
        cb = callbacks or {}
        self._on_log = cb.get("on_log")
        self._on_stats = cb.get("on_stats")
        self._on_status = cb.get("on_status")
        self._on_progress = cb.get("on_progress")
        self._on_device_info = cb.get("on_device_info")

        # Estatísticas
        self.stats = {
            "videos_assistidos": 0,
            "tempo_total": 0,
            "inicio": None,
            "erros": 0,
            "swipes": 0,
        }

        # Estado de evasão anti-detecção
        self._sessao_inicio = None
        self._velocidade_sessao = 1.0  # Fator de velocidade da sessão (varia ao longo do tempo)
        self._ultimo_ajuste_brilho = 0
        self._ultima_troca_rede = 0
        self._ultimo_cache_clear = 0
        self._evasoes_executadas = 0

    # ─── Helpers ──────────────────────────────────────────

    def _emit_log(self, level: str, msg: str):
        """Emite log para o logger padrão e para o callback."""
        getattr(log, level, log.info)(msg)
        if self._on_log:
            self._on_log(level, msg)

    def _emit_stats(self):
        if self._on_stats:
            self._on_stats(dict(self.stats))

    def _emit_status(self, status: str):
        if self._on_status:
            self._on_status(status)

    def _sleep(self, seconds: float):
        """Sleep interruptível que respeita _running e _paused."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not self._running:
                return
            while self._paused and self._running:
                time.sleep(0.2)
            time.sleep(min(0.25, end - time.monotonic()))

    # ─── Controle externo ─────────────────────────────────

    def parar(self):
        """Para o bot de forma segura."""
        self._running = False
        self._paused = False

    def pausar(self):
        """Pausa/retoma o bot."""
        self._paused = not self._paused
        status = "paused" if self._paused else "running"
        self._emit_status(status)
        self._emit_log("info", "Bot PAUSADO" if self._paused else "Bot RETOMADO")

    @property
    def esta_rodando(self):
        return self._running

    @property
    def esta_pausado(self):
        return self._paused

    # ─── ADB Helpers ──────────────────────────────────────

    def adb_cmd(self, *args, timeout=15) -> str:
        cmd = [self.adb]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.extend(args)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode != 0 and result.stderr.strip():
                log.debug(f"ADB stderr: {result.stderr.strip()}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            self._emit_log("warning", f"Timeout no comando: {' '.join(args)}")
            return ""
        except FileNotFoundError:
            self._emit_log("error", f"adb.exe nao encontrado em: {self.adb}")
            return ""

    def adb_shell(self, *args, timeout=15) -> str:
        return self.adb_cmd("shell", *args, timeout=timeout)

    # ─── Inicialização ────────────────────────────────────

    def verificar_dispositivo(self) -> bool:
        self._emit_log("info", "Verificando dispositivos conectados...")

        # Se o device_id já veio da config (selecionado na GUI), usa direto
        pre_selected = self.config.get("device_id")
        if pre_selected:
            self.device_id = pre_selected
            self._emit_log("info", f"Usando dispositivo pre-selecionado: {self.device_id}")
        else:
            output = self.adb_cmd("devices")
            lines = [l for l in output.split("\n") if "\tdevice" in l]

            if not lines:
                self._emit_log("error", "Nenhum dispositivo encontrado!")
                self._emit_log("error", "Verifique: USB conectado, Depuracao USB ativada, computador autorizado")
                return False

            self.device_id = lines[0].split("\t")[0]

        modelo = self.adb_shell("getprop", "ro.product.model")
        marca = self.adb_shell("getprop", "ro.product.brand")
        android_ver = self.adb_shell("getprop", "ro.build.version.release")

        self._emit_log("info", f"Dispositivo: {marca} {modelo} (Android {android_ver})")
        self._emit_log("info", f"ID: {self.device_id}")

        if self._on_device_info:
            self._on_device_info({
                "id": self.device_id,
                "modelo": modelo,
                "marca": marca,
                "android": android_ver,
            })

        # Aplica o patch Anti-Emulador se habilitado na interface
        if self.config.get("anti_emulador", True):
            self._ocultar_emulador()

        # Inicializa o UIAutomator2
        self._emit_log("info", "Iniciando servidor UIAutomator2 no dispositivo...")
        try:
            self.d = u2.connect(self.device_id)
            self._emit_log("info", "UIAutomator2 conectado com sucesso!")
        except Exception as e:
            self._emit_log("error", f"Falha ao conectar UIAutomator2: {e}")
            return False

        return True

    def _ocultar_emulador(self):
        """Tenta modificar as propriedades do emulador no build.prop via ADB com root."""
        self._emit_log("info", "🔧 Aplicando patch Anti-Emulador avançado (modificando build.prop)...")
        # Remonta a partição system como leitura e escrita
        self.adb_shell("su", "-c", "mount -o rw,remount /system")
        
        import random
        perfis_dispositivos = [
            {
                "nome": "Samsung Galaxy A04e",
                "props": {
                    "ro.product.brand": "samsung",
                    "ro.product.model": "SM-A042M",
                    "ro.product.name": "a04emx",
                    "ro.product.device": "a04e",
                    "ro.product.manufacturer": "samsung",
                    "ro.hardware": "mt6765",
                    "ro.product.board": "mt6765",
                    "ro.boot.hardware": "mt6765"
                }
            },
            {
                "nome": "Xiaomi Poco X5 Pro 5G",
                "props": {
                    "ro.product.brand": "POCO",
                    "ro.product.model": "22101320G",
                    "ro.product.name": "redwood",
                    "ro.product.device": "redwood",
                    "ro.product.manufacturer": "Xiaomi",
                    "ro.hardware": "qcom",
                    "ro.product.board": "sm7325",
                    "ro.boot.hardware": "qcom"
                }
            },
            {
                "nome": "Samsung Galaxy M52 5G",
                "props": {
                    "ro.product.brand": "samsung",
                    "ro.product.model": "SM-M526BR",
                    "ro.product.name": "m52xsq",
                    "ro.product.device": "m52x",
                    "ro.product.manufacturer": "samsung",
                    "ro.hardware": "qcom",
                    "ro.product.board": "lahaina",
                    "ro.boot.hardware": "qcom"
                }
            },
            {
                "nome": "Samsung Galaxy S23",
                "props": {
                    "ro.product.brand": "samsung",
                    "ro.product.model": "SM-S911B",
                    "ro.product.name": "kalama",
                    "ro.product.device": "kalama",
                    "ro.product.manufacturer": "samsung",
                    "ro.hardware": "qcom",
                    "ro.product.board": "kalama",
                    "ro.boot.hardware": "qcom"
                }
            },
            {
                "nome": "Samsung Galaxy S24 Ultra",
                "props": {
                    "ro.product.brand": "samsung",
                    "ro.product.model": "SM-S928B",
                    "ro.product.name": "pineapple",
                    "ro.product.device": "pineapple",
                    "ro.product.manufacturer": "samsung",
                    "ro.hardware": "qcom",
                    "ro.product.board": "pineapple",
                    "ro.boot.hardware": "qcom"
                }
            },
            {
                "nome": "Motorola Edge 30",
                "props": {
                    "ro.product.brand": "motorola",
                    "ro.product.model": "motorola edge 30",
                    "ro.product.name": "dubai_g",
                    "ro.product.device": "dubai",
                    "ro.product.manufacturer": "motorola",
                    "ro.hardware": "qcom",
                    "ro.product.board": "lito",
                    "ro.boot.hardware": "qcom"
                }
            }
        ]
        
        perfil_escolhido = random.choice(perfis_dispositivos)
        self._emit_log("info", f"📱 Perfil de hardware selecionado: {perfil_escolhido['nome']}")
        
        # Propriedades genéricas de evasão aplicadas a todos
        props_evasao = {
            "ro.kernel.qemu": "0",
            "ro.build.tags": "release-keys",
            "ro.build.type": "user",
            "ro.build.characteristics": "default"
        }
        
        # Junta as propriedades específicas do dispositivo escolhido com as genéricas
        todas_props = {**props_evasao, **perfil_escolhido["props"]}
        
        for key, value in todas_props.items():
            # Substitui se já existir
            cmd_sed = f"sed -i 's/^{key}=.*/{key}={value}/g' /system/build.prop"
            self.adb_shell("su", "-c", cmd_sed)
            
            # Adiciona no final se não existir
            cmd_grep = f"grep -q '^{key}=' /system/build.prop || echo '{key}={value}' >> /system/build.prop"
            self.adb_shell("su", "-c", cmd_grep)

            # Tenta alterar em tempo de execução (usando aspas para valores com espaços)
            self.adb_shell("su", "-c", f"setprop {key} '{value}'")

        self._emit_log("info", "✅ Patch Anti-Emulador avançado aplicado com sucesso.")

    def obter_resolucao(self):
        output = self.adb_shell("wm", "size")
        if "Physical size:" in output:
            size = output.split("Physical size:")[-1].strip()
        elif "Override size:" in output:
            size = output.split("Override size:")[-1].strip()
        else:
            size = "1080x1920"
            self._emit_log("warning", f"Resolucao nao detectada. Usando padrao: {size}")

        parts = size.split("x")
        self.screen_width = int(parts[0])
        self.screen_height = int(parts[1])
        self._emit_log("info", f"Resolucao: {self.screen_width}x{self.screen_height}")

    def detectar_kwai(self) -> bool:
        self._emit_log("info", "Procurando Kwai instalado...")
        packages = self.adb_shell("pm", "list", "packages")
        for pkg in KWAI_PACKAGES:
            if f"package:{pkg}" in packages:
                self.kwai_package = pkg
                self._emit_log("info", f"Kwai encontrado: {pkg}")
                return True
        self._emit_log("error", "Kwai nao encontrado no dispositivo!")
        return False

    # ─── Controle do App ──────────────────────────────────

    def abrir_kwai(self):
        self._emit_log("info", "Abrindo o Kwai...")
        self.adb_shell(
            "monkey", "-p", self.kwai_package,
            "-c", "android.intent.category.LAUNCHER", "1"
        )
        tempo_carga = random.uniform(4, 7)
        self._emit_log("info", f"Aguardando {tempo_carga:.1f}s para carregar...")
        self._sleep(tempo_carga)

    def verificar_kwai_aberto(self) -> bool:
        if not self.kwai_package:
            return False
        # Faz até 2 tentativas para evitar falso-positivo devido a lentidão do ADB
        for attempt in range(2):
            output = self.adb_shell("dumpsys", "window", "displays", timeout=8)
            if output.strip():
                return self.kwai_package in output
            self._sleep(0.5)
        return False

    def fechar_kwai(self):
        self._emit_log("info", "Fechando o Kwai...")
        self.adb_shell("am", "force-stop", self.kwai_package)

    def manter_tela_ligada(self):
        output = self.adb_shell("dumpsys", "power")
        if "mWakefulness=Asleep" in output or "Display Power: state=OFF" in output:
            self._emit_log("info", "Tela desligada. Ligando...")
            self.adb_shell("input", "keyevent", "KEYCODE_WAKEUP")
            self._sleep(1)
            self.swipe(
                self.screen_width // 2, int(self.screen_height * 0.8),
                self.screen_width // 2, int(self.screen_height * 0.2), 300
            )
            self._sleep(2)

    # ─── Análise de Tela ──────────────────────────────────

    def obter_xml_tela(self) -> str:
        """Obtém o dump da hierarquia atual da tela, priorizando o uiautomator2."""
        try:
            if self.d:
                # Retorna a hierarquia XML inteira de forma quase instantânea
                return self.d.dump_hierarchy()
            else:
                self.adb_shell("uiautomator", "dump", "/data/local/tmp/uidump.xml", timeout=6)
                return self.adb_shell("cat", "/data/local/tmp/uidump.xml", timeout=6)
        except Exception as e:
            self._emit_log("error", f"Falha ao ler XML da tela: {e}")
            return ""

    # ─── Gestos ───────────────────────────────────────────

    def tap(self, x: int, y: int):
        x += random.randint(-5, 5)
        y += random.randint(-5, 5)
        try:
            if self.d:
                self.d.click(x, y)
            else:
                self.adb_shell("input", "tap", str(x), str(y))
        except Exception as e:
            self._emit_log("warning", f"Erro no u2.click: {e}. Usando fallback ADB...")
            self.adb_shell("input", "tap", str(x), str(y))

    def swipe(self, x1, y1, x2, y2, duracao=300):
        x1 += random.randint(-10, 10)
        y1 += random.randint(-10, 10)
        x2 += random.randint(-10, 10)
        y2 += random.randint(-10, 10)
        duracao += random.randint(-50, 100)
        
        # O uiautomator2 usa duração em float (segundos). 300ms = 0.3s
        duracao_segundos = max(0.05, duracao / 1000.0)
        
        try:
            if self.d:
                self.d.swipe(x1, y1, x2, y2, duracao_segundos)
            else:
                self.adb_shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(int(duracao)))
        except Exception as e:
            self._emit_log("warning", f"Erro no u2.swipe: {e}. Usando fallback ADB...")
            self.adb_shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(int(duracao)))

    def swipe_proximo_video(self):
        center_x = self.screen_width // 2
        start_y = int(self.screen_height * random.uniform(0.70, 0.80))
        end_y = int(self.screen_height * random.uniform(0.15, 0.25))
        duracao = random.randint(200, 500)
        self.swipe(center_x, start_y, center_x, end_y, duracao)
        self.stats["swipes"] += 1

    def simular_interacao_humana(self):
        """Protocolo de evasão e humanização: executa eventos aleatórios para evitar detecção.
        Usa velocidade variável da sessão para modular tempos de espera."""
        fator = getattr(self, '_velocidade_sessao', 1.0)

        eventos = [
            {"type": "TOQUE_ALEATORIO", "peso": 10},
            {"type": "SCROLL_VERT", "peso": 12},
            {"type": "VERIFICAR_TELA", "peso": 5},
            {"type": "SWIPE_HORIZONTAL", "peso": 4},
            {"type": "NOTIFICACAO", "peso": 3},
            {"type": "COMENTAR_DESISTIR", "peso": 3},
            {"type": "NENHUM", "peso": 63}
        ]
        
        escolha = random.choices([e["type"] for e in eventos], weights=[e["peso"] for e in eventos])[0]
        
        if escolha == "TOQUE_ALEATORIO":
            self._emit_log("info", "🤖 [Evasão] Simulando toque aleatório inofensivo...")
            # Limita a largura entre 30% e 70% para evitar clicar no FAB (botão de bônus) nas laterais
            x = random.randint(int(self.screen_width * 0.3), int(self.screen_width * 0.7))
            y = random.randint(int(self.screen_height * 0.3), int(self.screen_height * 0.7))
            self.tap(x, y)
            self._sleep(random.uniform(0.5, 1.2) * fator)
            
            # Chance de apertar voltar caso clique em algo acidental
            if random.random() < 0.3:
                self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                self._sleep(0.5)
                
        elif escolha == "SCROLL_VERT":
            self._emit_log("info", "🤖 [Evasão] Simulando scroll vertical leve (comportamento humano)...")
            center_x = self.screen_width // 2 + random.randint(-50, 50)
            start_y = int(self.screen_height * random.uniform(0.3, 0.7))
            duracao = random.randint(400, 700)
            end_y = start_y + random.choice([-1, 1]) * random.randint(40, 150)
            self.swipe(center_x, start_y, center_x, end_y, duracao)
            self._sleep(random.uniform(0.8, 1.5) * fator)
            
        elif escolha == "VERIFICAR_TELA":
            self._emit_log("info", "🤖 [Evasão] Simulando verificação de tela (pausa longa)...")
            self._sleep(random.uniform(3.0, 5.2) * fator)
            self.tap(self.screen_width // 2, int(self.screen_height * 0.05))  # Toca no topo inofensivo

        elif escolha == "SWIPE_HORIZONTAL":
            self.swipe_horizontal_aleatorio()

        elif escolha == "NOTIFICACAO":
            self.simular_notificacao()

        elif escolha == "COMENTAR_DESISTIR":
            self.simular_digitacao_aleatoria()

    def curtir_video_aleatorio(self):
        """Simula o duplo clique na tela para curtir o vídeo (12% de chance)."""
        if random.random() < 0.12:
            self._emit_log("info", "❤️ Curtindo o vídeo aleatoriamente (Duplo Clique)...")
            center_x = self.screen_width // 2
            center_y = self.screen_height // 2
            x = center_x + random.randint(-80, 80)
            y = center_y + random.randint(-80, 80)
            self.tap(x, y)
            time.sleep(random.uniform(0.08, 0.15))
            self.tap(x + random.randint(-8, 8), y + random.randint(-8, 8))
            self._sleep(random.uniform(1.0, 2.0))

    def pausar_retomar_video_aleatorio(self):
        """Simula pausar e retomar o vídeo tocando no meio da tela (4% de chance)."""
        if random.random() < 0.04:
            self._emit_log("info", "⏸️ Pausando o vídeo temporariamente...")
            center_x = self.screen_width // 2
            center_y = self.screen_height // 2
            self.tap(center_x, center_y)
            self._sleep(random.uniform(2.0, 5.0))
            self._emit_log("info", "▶️ Retomando o vídeo...")
            self.tap(center_x + random.randint(-15, 15), center_y + random.randint(-15, 15))
            self._sleep(random.uniform(0.8, 1.5))

    def micro_swipe(self):
        """Faz um leve ajuste na tela/micro-rolagem (15% de chance)."""
        if random.random() < 0.15:
            self._emit_log("info", "☝️ Fazendo micro-rolagem de ajuste...")
            center_x = self.screen_width // 2
            start_y = int(self.screen_height * random.uniform(0.45, 0.55))
            end_y = start_y + random.choice([-1, 1]) * random.randint(40, 90)
            self.swipe(center_x, start_y, center_x, end_y, random.randint(150, 250))
            self._sleep(random.uniform(0.5, 1.2))

    # ─── Evasão Avançada ──────────────────────────────────

    def ajustar_brilho_por_horario(self):
        """Ajusta o brilho da tela com base na hora do dia para simular uso físico real."""
        agora = time.monotonic()
        # Só ajusta a cada 10 minutos no mínimo
        if agora - self._ultimo_ajuste_brilho < 600:
            return
        self._ultimo_ajuste_brilho = agora

        hora_atual = datetime.now().hour
        if hora_atual < 6 or hora_atual >= 22:  # Noite/madrugada
            brilho = random.randint(15, 40)
            periodo = "noite"
        elif hora_atual < 12:  # Manhã
            brilho = random.randint(120, 180)
            periodo = "manhã"
        elif hora_atual < 18:  # Tarde
            brilho = random.randint(140, 200)
            periodo = "tarde"
        else:  # Anoitecer
            brilho = random.randint(60, 110)
            periodo = "anoitecer"

        self._emit_log("info", f"🔆 [Evasão] Ajustando brilho para {brilho}/255 ({periodo})")
        self.adb_shell("settings", "put", "system", "screen_brightness", str(brilho))
        self._evasoes_executadas += 1

    def simular_troca_rede(self):
        """Simula breve troca de rede (WiFi off/on) para evitar padrão de conexão estática."""
        agora = time.monotonic()
        # Só troca a cada 20 minutos e com 15% de chance
        if agora - self._ultima_troca_rede < 1200 or random.random() > 0.15:
            return
        self._ultima_troca_rede = agora

        self._emit_log("info", "📡 [Evasão] Simulando breve troca de rede WiFi...")
        self.adb_shell("svc", "wifi", "disable")
        self._sleep(random.uniform(2.0, 4.0))
        self.adb_shell("svc", "wifi", "enable")
        self._sleep(random.uniform(3.0, 6.0))
        self._evasoes_executadas += 1

    def simular_notificacao(self):
        """Simula abrir e fechar a barra de notificações como um humano faria."""
        self._emit_log("info", "🔔 [Evasão] Simulando verificação de notificações...")
        # Puxa a barra de notificações pra baixo
        self.swipe(
            self.screen_width // 2, 0,
            self.screen_width // 2, int(self.screen_height * 0.6),
            random.randint(250, 400)
        )
        self._sleep(random.uniform(1.5, 4.0))

        # Fecha a barra de notificações
        self.swipe(
            self.screen_width // 2, int(self.screen_height * 0.6),
            self.screen_width // 2, 0,
            random.randint(200, 350)
        )
        self._sleep(random.uniform(0.5, 1.5))
        self._evasoes_executadas += 1

    def swipe_horizontal_aleatorio(self):
        """Simula um swipe horizontal leve (como se estivesse explorando)."""
        self._emit_log("info", "👈 [Evasão] Simulando swipe horizontal exploratório...")
        center_y = int(self.screen_height * random.uniform(0.3, 0.7))
        # Ajustado para começar um pouco menos à direita e não arrastar acidentalmente o FAB
        start_x = int(self.screen_width * random.uniform(0.55, 0.75))
        end_x = int(self.screen_width * random.uniform(0.15, 0.4))
        duracao = random.randint(300, 600)
        self.swipe(start_x, center_y, end_x, center_y, duracao)
        self._sleep(random.uniform(1.0, 2.5))

        # Volta com swipe contrário
        if random.random() < 0.7:
            self.swipe(end_x, center_y, start_x, center_y, random.randint(300, 500))
            self._sleep(random.uniform(0.5, 1.5))
        self._evasoes_executadas += 1

    def limpar_cache_periodico(self):
        """Limpa cache do Kwai periodicamente para evitar acúmulo de dados de rastreamento."""
        agora = time.monotonic()
        # Só limpa a cada 30 minutos
        if agora - self._ultimo_cache_clear < 1800:
            return
        self._ultimo_cache_clear = agora

        self._emit_log("info", "🧹 [Evasão] Limpando cache do Kwai para evitar rastreamento...")
        if self.kwai_package:
            self.adb_shell("pm", "clear", "--cache-only", self.kwai_package)
        self._evasoes_executadas += 1

    def variar_velocidade_sessao(self):
        """Varia a velocidade de interação ao longo da sessão para parecer mais humano.
        No início a pessoa é mais rápida, no meio desacelera, e no final volta a acelerar."""
        if not self._sessao_inicio:
            self._sessao_inicio = time.monotonic()

        tempo_decorrido = time.monotonic() - self._sessao_inicio
        minutos = tempo_decorrido / 60

        if minutos < 5:
            # Início: interação normal/rápida (curioso)
            self._velocidade_sessao = random.uniform(0.8, 1.0)
        elif minutos < 20:
            # Meio: desacelera (entediado/distraído)
            self._velocidade_sessao = random.uniform(1.1, 1.6)
        elif minutos < 40:
            # Continuação: mais lento ainda
            self._velocidade_sessao = random.uniform(1.3, 2.0)
        else:
            # Final: volta a acelerar (quer terminar)
            self._velocidade_sessao = random.uniform(0.7, 1.1)

    def simular_digitacao_aleatoria(self):
        """Simula abertura e fechamento rápido do teclado (como se fosse escrever um comentário e desistir)."""
        self._emit_log("info", "⌨️ [Evasão] Simulando intenção de comentar (abrir/fechar teclado)...")
        # Toca na área de comentários (parte inferior da tela)
        self.tap(int(self.screen_width * 0.5), int(self.screen_height * 0.92))
        self._sleep(random.uniform(1.5, 3.0))

        # Desiste e fecha o teclado
        self.adb_shell("input", "keyevent", "KEYCODE_BACK")
        self._sleep(random.uniform(0.5, 1.2))
        self._evasoes_executadas += 1

    def executar_evasao_periodica(self, video_idx: int):
        """Executa protocolo de evasão periódica baseado no número de vídeos processados."""
        if not self._running:
            return

        # Varia velocidade da sessão
        self.variar_velocidade_sessao()

        # A cada 5 vídeos: ajuste de brilho
        if video_idx % 5 == 0:
            self.ajustar_brilho_por_horario()

        # A cada 8 vídeos: chance de verificar notificações
        if video_idx % 8 == 0 and random.random() < 0.25:
            self.simular_notificacao()

        # A cada 12 vídeos: chance de swipe horizontal
        if video_idx % 12 == 0 and random.random() < 0.20:
            self.swipe_horizontal_aleatorio()

        # A cada 20 vídeos: chance de simular comentário
        if video_idx % 20 == 0 and random.random() < 0.15:
            self.simular_digitacao_aleatoria()

        # A cada 25 vídeos: troca de rede
        if video_idx % 25 == 0:
            self.simular_troca_rede()

        # Limpa cache periodicamente
        self.limpar_cache_periodico()

    def protocolo_evasao_inicial(self):
        """Protocolo de evasão executado no início da sessão para parecer uso orgânico."""
        self._emit_log("info", "🛡️ [Evasão] Iniciando protocolo de evasão pré-sessão...")
        self._sessao_inicio = time.monotonic()
        self._ultimo_ajuste_brilho = 0
        self._ultima_troca_rede = time.monotonic()
        self._ultimo_cache_clear = time.monotonic()

        # 1. Ajusta brilho de acordo com horário
        self.ajustar_brilho_por_horario()

        # 2. Pausa inicial variável (humano não abre e começa imediatamente)
        pausa_inicial = random.uniform(2.0, 6.0)
        self._emit_log("info", f"🛡️ [Evasão] Pausa inicial de {pausa_inicial:.1f}s (simulando abertura humana)...")
        self._sleep(pausa_inicial)

        # 3. Chance de verificar notificações antes de começar
        if random.random() < 0.30:
            self.simular_notificacao()

        # 4. Scroll exploratório leve
        if random.random() < 0.40:
            self._emit_log("info", "🛡️ [Evasão] Scroll exploratório inicial...")
            center_x = self.screen_width // 2
            start_y = int(self.screen_height * 0.6)
            end_y = int(self.screen_height * 0.3)
            self.swipe(center_x, start_y, center_x, end_y, random.randint(400, 700))
            self._sleep(random.uniform(1.5, 3.0))

        self._emit_log("info", f"🛡️ [Evasão] Protocolo inicial concluído. Evasões executadas: {self._evasoes_executadas}")

    def protocolo_evasao_final(self):
        """Protocolo de evasão executado ao final da sessão para parecer saída natural."""
        self._emit_log("info", "🛡️ [Evasão] Iniciando protocolo de saída natural...")

        # 1. Pausa final como se estivesse pensando se sai
        self._sleep(random.uniform(2.0, 5.0))

        # 2. Chance de scroll rápido final (como se desse uma última olhada)
        if random.random() < 0.35:
            self._emit_log("info", "🛡️ [Evasão] Última olhada no feed antes de sair...")
            for _ in range(random.randint(1, 3)):
                self.swipe_proximo_video()
                self._sleep(random.uniform(0.8, 2.0))

        # 3. Desliga tela no final (simula colocar o celular de lado)
        if random.random() < 0.25:
            self._emit_log("info", "🛡️ [Evasão] Simulando desligamento de tela (celular de lado)...")
            self.adb_shell("input", "keyevent", "KEYCODE_POWER")
            self._sleep(random.uniform(2.0, 5.0))
            self.adb_shell("input", "keyevent", "KEYCODE_WAKEUP")
            self._sleep(1)

        self._emit_log("info", f"🛡️ [Evasão] Sessão encerrada. Total de evasões: {self._evasoes_executadas}")

    # ─── Navegação ────────────────────────────────────────

    def ir_para_feed(self):
        self._emit_log("info", "Navegando para o feed de videos...")
        home_x = int(self.screen_width * 0.10)
        home_y = int(self.screen_height * 0.96)
        self.tap(home_x, home_y)
        self._sleep(2)
        self.swipe_proximo_video()
        self._sleep(1)

    def clicar_x_popup(self, xml_content: str) -> bool:
        """Tenta encontrar um botão/ícone de fechar (X) ou 'sair' no XML da tela e clica nele."""
        import re
        
        # Padrões comuns para botão de fechar no resource-id ou content-desc ou text
        id_patterns = ["close", "dismiss", "cancel", "exit", "btn_close", "close_btn", "close_button", "iv_close", "img_close"]
        desc_patterns = ["fechar", "close", "cancelar", "descartar", "cancel", "dismiss", "sair"]
        text_patterns = ["x", "✕", "×", "fechar", "close", "sair"]
        
        for match in re.finditer(r'<node[^>]*>', xml_content):
            node_str = match.group(0)
            
            res_id_match = re.search(r'resource-id="([^"]*)"', node_str)
            desc_match = re.search(r'content-desc="([^"]*)"', node_str)
            text_match = re.search(r'text="([^"]*)"', node_str)
            
            res_id = res_id_match.group(1).lower().strip() if res_id_match else ""
            desc = desc_match.group(1).lower().strip() if desc_match else ""
            text = text_match.group(1).lower().strip() if text_match else ""
            
            # IGNORA campos de edição de texto (inputs, editores de comentários)
            if "editor" in res_id or "edit" in res_id or "input" in res_id or "search" in res_id:
                continue
                
            found = False
            
            # 1. Verifica se o resource-id contem padrões de fechar
            for pattern in id_patterns:
                if pattern in res_id:
                    found = True
                    break
                    
            # 2. Verifica se o content-desc contem padrões de fechar
            if not found:
                for pattern in desc_patterns:
                    if pattern in desc:
                        found = True
                        break
                        
            # 3. Verifica se o text é exatamente ou contem os caracteres de "X" ou fechar
            if not found:
                if text in text_patterns:
                    found = True
                    
            if found:
                bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node_str)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                        continue
                    
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    
                    if hasattr(self, 'screen_width') and self.screen_width > 0:
                        # Ignora o "X" do bônus Kwai Golds no canto esquerdo da tela (independente da altura Y)
                        if center_x < (self.screen_width * 0.38):
                            continue
                    
                    self._emit_log("info", f"🎯 [Popup] Botão de fechar detectado: id='{res_id}', desc='{desc}', text='{text}' em ({center_x}, {center_y})")
                    self.tap(center_x, center_y)
                    return True
                    
        return False

    def fechar_popups(self):
        self._emit_log("info", "Verificando e fechando popups...")
        xml_content = self.obter_xml_tela()
        
        if xml_content and "xml" in xml_content:
            if self.clicar_x_popup(xml_content):
                self._sleep(1.5)
                return  # Clicou com sucesso no X do popup
                
        # Caso contrário, usa o KEYCODE_BACK como fallback
        self._emit_log("info", "Nenhum botão 'X' detectado. Usando KEYCODE_BACK de forma segura...")
        self.adb_shell("input", "keyevent", "KEYCODE_BACK")
        self._sleep(0.8)
        
        # Se fechar o aplicativo com esse único voltar, nós o reabrimos
        if not self.verificar_kwai_aberto():
            self._emit_log("warning", "Kwai fechou ao tentar fechar popups. Reabrendo...")
            self.abrir_kwai()

    def detectar_live(self, xml_content: str = None) -> bool:
        """Detecta se o vídeo atual é uma transmissão ao vivo (Live)."""
        try:
            # 1. Verifica pela atividade atual focada (apenas nomes de classes específicos de live)
            focus_output = self.adb_shell("dumpsys", "window", "displays", timeout=5).lower()
            activities_live = ["liveplayactivity", "liveroomactivity", "liveactivity"]
            for act in activities_live:
                if act in focus_output:
                    return True

            # 2. Verifica pela hierarquia da tela (XML)
            if xml_content is None:
                xml_content = self.obter_xml_tela()
                
            if not xml_content or "xml" not in xml_content:
                return False
            
            content_lower = xml_content.lower()
            
            # Padrões específicos para identificar live (evitando qualquer palavra "live" avulsa)
            padroes = [
                'text="ao vivo"',
                'text="entrando em live"',
                'content-desc="ao vivo"',
                'content-desc="entrando em live"',
                'entrando em live'
            ]
            for padrao in padroes:
                if padrao in content_lower:
                    return True
                    
            return False
        except Exception:
            return False

    def _click_node(self, xml_content: str, text_to_find: str, exato=False) -> bool:
        """Procura um nó no XML com o texto ou content-desc dado e clica nele."""
        import re
        text_lower = text_to_find.lower().strip()
        
        for match in re.finditer(r'<node[^>]*>', xml_content):
            node_str = match.group(0)
            
            text_match = re.search(r'text="([^"]*)"', node_str)
            desc_match = re.search(r'content-desc="([^"]*)"', node_str)
            
            node_text = text_match.group(1).lower().strip() if text_match else ""
            node_desc = desc_match.group(1).lower().strip() if desc_match else ""
            
            found = False
            if exato:
                if node_text == text_lower or node_desc == text_lower:
                    found = True
            else:
                if text_lower in node_text or text_lower in node_desc:
                    found = True
            
            if found:
                bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node_str)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                        continue
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    self.tap(center_x, center_y)
                    return True
        return False

    def _clicar_botao_comentarios(self, xml_content: str) -> bool:
        """Procura especificamente o botão de comentários do Kwai.
        Filtra apenas botões do lado direito da tela para evitar clicar na descrição do vídeo ou perfil."""
        import re
        for match in re.finditer(r'<node[^>]*>', xml_content):
            node_str = match.group(0)
            
            res_id_match = re.search(r'resource-id="([^"]*)"', node_str)
            desc_match = re.search(r'content-desc="([^"]*)"', node_str)
            text_match = re.search(r'text="([^"]*)"', node_str)
            class_match = re.search(r'class="([^"]*)"', node_str)
            
            res_id = res_id_match.group(1).lower() if res_id_match else ""
            desc = desc_match.group(1).lower() if desc_match else ""
            text = text_match.group(1).lower() if text_match else ""
            class_name = class_match.group(1).lower() if class_match else ""
            
            is_comment_node = False
            if "comment" in res_id:
                is_comment_node = True
            elif ("comentá" in desc or "comenta" in desc) and "textview" not in class_name:
                is_comment_node = True
                
            if is_comment_node:
                bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node_str)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    
                    # O painel de botões do Kwai fica no canto direito (x > 70%)
                    if hasattr(self, 'screen_width') and self.screen_width > 0:
                        if center_x < (self.screen_width * 0.70):
                            continue
                            
                    self._emit_log("info", f"💬 [Comentários] Botão de comentários encontrado via XML em ({center_x}, {center_y})")
                    self.tap(center_x, center_y)
                    return True
                    
        # Fallback posicional se o XML falhar (geralmente acima de compartilhar, na direita)
        if hasattr(self, 'screen_width') and self.screen_width > 0:
            fallback_x = int(self.screen_width * 0.92)
            fallback_y = int(self.screen_height * 0.65)
            self._emit_log("info", f"💬 [Comentários] Botão não detectado no XML. Usando fallback posicional em ({fallback_x}, {fallback_y})")
            self.tap(fallback_x, fallback_y)
            return True
            
        return False

    def _clicar_botao_sair(self, xml_content: str = None) -> bool:
        """Tenta encontrar e clicar no botão 'Sair' usando múltiplas estratégias.
        
        Estratégia 1: Usa a API nativa do uiautomator2 para buscar o elemento por texto.
        Estratégia 2: Faz busca flexível no XML por variações de 'sair'.
        Estratégia 3: Se detectar o popup de 'Ganhar mais'/'Assista mais um', 
                       clica na posição inferior onde 'Sair' costuma ficar.
        """
        import re
        
        # --- Estratégia 1: API nativa do uiautomator2 ---
        try:
            if self.d:
                for texto_sair in ["Sair", "sair", "SAIR"]:
                    el = self.d(text=texto_sair)
                    if el.exists(timeout=1):
                        self._emit_log("info", f"🚪 [u2] Botão '{texto_sair}' encontrado via API nativa! Clicando...")
                        el.click()
                        return True
                        
                # Busca por textContains (caso tenha espaços extras)
                el = self.d(textContains="air")
                if el.exists(timeout=0.5):
                    info = el.info
                    text_val = info.get("text", "")
                    if text_val.strip().lower() == "sair":
                        self._emit_log("info", f"🚪 [u2] Botão 'Sair' encontrado (textContains)! Clicando...")
                        el.click()
                        return True
        except Exception as e:
            self._emit_log("debug", f"Busca u2 por 'Sair' falhou: {e}")
        
        # --- Estratégia 2: Busca flexível no XML ---
        if xml_content:
            for match in re.finditer(r'<node[^>]*>', xml_content):
                node_str = match.group(0)
                
                text_match = re.search(r'text="([^"]*)"', node_str)
                desc_match = re.search(r'content-desc="([^"]*)"', node_str)
                
                node_text = text_match.group(1).strip().lower() if text_match else ""
                node_desc = desc_match.group(1).strip().lower() if desc_match else ""
                
                if node_text == "sair" or node_desc == "sair":
                    bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node_str)
                    if bounds_match:
                        x1, y1, x2, y2 = map(int, bounds_match.groups())
                        if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                            continue
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2
                        self._emit_log("info", f"🚪 [XML] Botão 'Sair' detectado em ({center_x}, {center_y}). Clicando...")
                        self.tap(center_x, center_y)
                        return True
        
        # --- Estratégia 3: Detecção do popup por contexto e clique posicional ---
        xml_to_check = xml_content or ""
        content_lower = xml_to_check.lower()
        popup_indicators = [
            "assista mais um para ganhar",
            "ganhar mais",
            "assista mais um",
            "assista um para ganhar",
        ]
        
        for indicator in popup_indicators:
            if indicator in content_lower:
                sair_x = self.screen_width // 2
                sair_y = int(self.screen_height * 0.78)
                self._emit_log("info", f"🚪 [Posicional] Popup de 'ganhar mais' detectado. Clicando em 'Sair' na posição ({sair_x}, {sair_y})...")
                self.tap(sair_x, sair_y)
                return True
        
        return False

    # ─── Loop Principal ───────────────────────────────────

    def assistir_video(self, numero: int):
        if not self._running:
            return

        tempo_min = self.config["tempo_min"]
        tempo_max = self.config["tempo_max"]
        tempo = random.uniform(tempo_min, tempo_max)

        if random.random() < 0.15:
            tempo *= random.uniform(1.3, 2.0)
            self._emit_log("info", f"Video #{numero} interessante! Mais tempo...")

        self._emit_log("info", f"Video #{numero} - Assistindo por {tempo:.1f}s...")

        # Ações humanizadas durante o vídeo
        self.curtir_video_aleatorio()
        self.pausar_retomar_video_aleatorio()
        self.micro_swipe()

        tempo_restante = tempo
        while tempo_restante > 0 and self._running:
            while self._paused and self._running:
                time.sleep(0.2)
                
            # Verifica se algum popup surgiu enquanto assistia o vídeo
            xml_content = self.obter_xml_tela()
            if xml_content and "xml" in xml_content:
                if self.clicar_x_popup(xml_content):
                    self._emit_log("info", "🎯 Popup interrompido fechado no meio do vídeo!")
                    
            intervalo = min(tempo_restante, 4.0)
            self._sleep(intervalo)
            tempo_restante -= intervalo
            if tempo_restante > 5 and random.random() < 0.1:
                self.manter_tela_ligada()

        self.stats["videos_assistidos"] += 1
        self.stats["tempo_total"] += tempo
        self._emit_stats()
        self.simular_interacao_humana()

    def _verificar_tela_kwai_golds(self, xml_content: str) -> bool:
        """Verifica se a tela atual é a tela do Kwai Golds analisando o XML."""
        if not xml_content:
            return False
        content_lower = xml_content.lower()
        # Padrões que indicam estar na tela de Kwai Golds
        indicadores = [
            "assistir a anúncios",
            "assistir a anuncios",
            "kwai golds",
            "saldo",
            "ganhe golds",
            "moedas de ouro",
        ]
        matches = sum(1 for ind in indicadores if ind in content_lower)
        return matches >= 2  # Precisa de pelo menos 2 indicadores para ter certeza

    def _detectar_tela_inicial_kwai(self, xml_content: str) -> bool:
        """Detecta se estamos na tela inicial/principal do Kwai (feed de vídeos)."""
        if not xml_content:
            return False
        content_lower = xml_content.lower()
        # Indicadores da tela inicial do Kwai (barra inferior com abas)
        indicadores = [
            "seguindo",
            "descobrir",
            "para você",
            "para voce",
            "camera",
            "câmera",
            "notificações",
            "notificacoes",
            "perfil",
            "me",
        ]
        matches = sum(1 for ind in indicadores if ind in content_lower)
        return matches >= 2

    def _clicar_botao_rosa_kwai_golds(self, xml_content: str) -> bool:
        """Detecta e clica no botão rosa flutuante (FAB) que leva à tela de Kwai Golds.
        
        O botão é redondo, rosa/gradiente, flutuante, e geralmente exibe um timer
        e quantidade de Kwai Golds. Fica posicionado na lateral direita ou inferior da tela.
        """
        import re
        
        for match in re.finditer(r'<node[^>]*>', xml_content):
            node_str = match.group(0)
            
            res_id_match = re.search(r'resource-id="([^"]*)"', node_str)
            desc_match = re.search(r'content-desc="([^"]*)"', node_str)
            text_match = re.search(r'text="([^"]*)"', node_str)
            class_match = re.search(r'class="([^"]*)"', node_str)
            
            res_id = res_id_match.group(1).lower().strip() if res_id_match else ""
            desc = desc_match.group(1).lower().strip() if desc_match else ""
            text = text_match.group(1).lower().strip() if text_match else ""
            node_class = class_match.group(1).lower().strip() if class_match else ""
            
            # Padrões para o botão flutuante de Kwai Golds
            # Pode ter resource-id com "gold", "reward", "float", "fab", "bonus"
            # Pode ter content-desc ou text com referência a golds/moedas
            id_patterns = ["gold", "reward", "float", "fab", "bonus", "incentive", "bubble", "earning"]
            desc_text_patterns = ["gold", "golds", "moeda", "ganhar", "recompensa", "reward"]
            
            found = False
            
            for pattern in id_patterns:
                if pattern in res_id:
                    found = True
                    break
            
            if not found:
                for pattern in desc_text_patterns:
                    if pattern in desc or pattern in text:
                        found = True
                        break
            
            if found:
                bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node_str)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                        continue
                    
                    # O botão é redondo/pequeno, então verificamos que não é um elemento muito grande
                    largura = x2 - x1
                    altura = y2 - y1
                    if largura > self.screen_width * 0.5 or altura > self.screen_height * 0.3:
                        continue  # Elemento muito grande, não é o FAB
                    
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    
                    self._emit_log("info", f"🩷 [FAB] Botão rosa de Kwai Golds detectado: id='{res_id}', desc='{desc}', text='{text}' em ({center_x}, {center_y})")
                    self.tap(center_x, center_y)
                    return True
        
        # Fallback: tenta procurar um elemento clicável pequeno e redondo na área da lateral direita
        # (o FAB geralmente fica na parte inferior-direita ou central-direita da tela)
        for match in re.finditer(r'<node[^>]*>', xml_content):
            node_str = match.group(0)
            
            clickable_match = re.search(r'clickable="([^"]*)"', node_str)
            if not clickable_match or clickable_match.group(1) != "true":
                continue
                
            bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node_str)
            if not bounds_match:
                continue
                
            x1, y1, x2, y2 = map(int, bounds_match.groups())
            largura = x2 - x1
            altura = y2 - y1
            center_x = (x1 + x2) // 2
            
            # Procura um elemento quadrado/redondo (proporção ~1:1) na metade direita da tela
            if largura < 10 or altura < 10:
                continue
            proporcao = largura / altura if altura > 0 else 0
            
            # Botão redondo: proporção entre 0.7 e 1.4, tamanho entre 50-200px, na lateral direita
            if (0.7 <= proporcao <= 1.4 
                and 50 <= largura <= 250 
                and center_x > self.screen_width * 0.6):
                
                # Verifica se contém alguma referência a golds no texto/desc
                text_match = re.search(r'text="([^"]*)"', node_str)
                desc_match = re.search(r'content-desc="([^"]*)"', node_str)
                text = text_match.group(1).strip() if text_match else ""
                desc = desc_match.group(1).strip() if desc_match else ""
                
                # Se o texto contém números (timer ou contagem de golds), é um bom candidato
                if text and any(c.isdigit() for c in text):
                    center_y = (y1 + y2) // 2
                    self._emit_log("info", f"🩷 [FAB Fallback] Possível botão rosa detectado: text='{text}', desc='{desc}' em ({center_x}, {center_y})")
                    self.tap(center_x, center_y)
                    return True
        
        return False

    def executar_modo_anuncios(self):
        self._emit_log("info", "=== FASE 3: Assistindo Anúncios ===")
        self._emit_log("info", "Aguardando na tela do Kwai Golds (posicionada pelo usuário)...")
        
        self.stats["inicio"] = datetime.now()
        videos_processados = 0
        total_videos = self.config["total_videos"]
        
        TIMEOUT_ANUNCIO = 40
        TIMEOUT_NAVEGANDO = 30  # Tempo máximo tentando voltar ao Kwai Golds antes de reiniciar
        inicio_anuncio = time.monotonic()
        inicio_navegando = time.monotonic()
        tentativas_reinicio = 0
        estado = "NoKwaiGolds"  # Assume que o usuário já está na tela do Kwai Golds
        
        try:
            while videos_processados < total_videos and self._running:
                if self._on_progress:
                    self._on_progress(videos_processados + 1, total_videos)
                    
                if not self.verificar_kwai_aberto():
                    self._emit_log("warning", "⚠️ Kwai não está em foco. Tentando recuperar com BACK...")
                    self.stats["erros"] += 1
                    self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                    self._sleep(3)
                    continue

                xml_content = self.obter_xml_tela()
                
                if not xml_content or "xml" not in xml_content:
                    self._sleep(2)
                    continue
                
                # Detecta se a tela do Kwai Golds está ativa e sincroniza o estado
                if self._verificar_tela_kwai_golds(xml_content):
                    if estado != "NoKwaiGolds":
                        self._emit_log("info", "🧭 Tela do Kwai Golds detectada! Estado sincronizado para 'NoKwaiGolds'.")
                        estado = "NoKwaiGolds"
                        tentativas_reinicio = 0
                
                # Na tela de Kwai Golds, verifica e fecha popups com "X" ou botão "Sair"
                if estado == "NoKwaiGolds":
                    if self.clicar_x_popup(xml_content):
                        self._sleep(2)
                        continue
                
                content_lower = xml_content.lower()
                
                if estado == "NoKwaiGolds":
                    if self._click_node(xml_content, "assistir a anúncios", exato=False):
                        self._emit_log("info", "📺 Iniciando anúncio...")
                        self._sleep(6)
                        estado = "Assistindo"
                        inicio_anuncio = time.monotonic()
                    else:
                        if "receba" in content_lower and "golds agora" in content_lower:
                            if self._click_node(xml_content, "receba", exato=False):
                                self._emit_log("info", "🎁 Popup de recompensa! Assistindo anúncio...")
                                self._sleep(5)
                                estado = "Assistindo"
                                inicio_anuncio = time.monotonic()
                        elif "continue ganhando" in content_lower or "continuar ganhando" in content_lower:
                            if self._click_node(xml_content, "continue ganhando", exato=False):
                                self._emit_log("info", "🎁 Popup 'Continue ganhando Kwai Golds'! Clicando...")
                                self._sleep(5)
                                estado = "Assistindo"
                                inicio_anuncio = time.monotonic()
                        else:
                            self._emit_log("warning", "Não encontrou 'Assistir a anúncios'. Entrando em modo de navegação...")
                            estado = "Navegando"
                            inicio_navegando = time.monotonic()
                            
                elif estado == "Assistindo":
                    if "este vídeo não está mais aqui" in content_lower or "faça uma pausa" in content_lower:
                        self._emit_log("warning", "🚨 [SHADOWBAN DETECTADO] O Kwai bloqueou os anúncios para esta conta/aparelho!")
                        self._emit_log("warning", "👉 Dica: Troque o IP (reinicie roteador/dados móveis) e limpe os dados do Kwai.")
                        if self._clicar_botao_sair(xml_content):
                            self._sleep(3)
                        else:
                            self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                            self._sleep(2)
                        
                        # Retorna para o feed normal para dar uma pausa
                        estado = "Navegando"
                        inicio_navegando = time.monotonic()
                        continue

                    # --- Detectar botão "Sair" após anúncio terminar ---
                    if self._clicar_botao_sair(xml_content):
                        self._emit_log("info", "🚪 Botão 'Sair' detectado! Clicando para voltar ao Kwai Golds...")
                        self._sleep(3)
                        # Verifica se voltou para a tela do Kwai Golds
                        xml_pos_sair = self.obter_xml_tela()
                        if xml_pos_sair and self._verificar_tela_kwai_golds(xml_pos_sair):
                            self._emit_log("info", "✅ Voltou para a tela do Kwai Golds com sucesso.")
                            estado = "NoKwaiGolds"
                        else:
                            estado = "Navegando"
                            inicio_navegando = time.monotonic()
                        videos_processados += 1
                        self.stats["videos_assistidos"] += 1
                        self._emit_stats()
                        inicio_anuncio = time.monotonic()
                        continue


                    if "continuar para obter moedas" in content_lower:
                        self._emit_log("info", "💰 Anúncio finalizado! Coletando recompensa...")
                        if not self._click_node(xml_content, "continuar para obter moedas"):
                            self.tap(self.screen_width // 2, int(self.screen_height * 0.85))
                        self._sleep(4)
                        videos_processados += 1
                        self.stats["videos_assistidos"] += 1
                        self._emit_stats()
                        inicio_anuncio = time.monotonic()
                        continue
                        
                    if "receba" in content_lower and "golds agora" in content_lower:
                        self._emit_log("info", "🎁 Popup de novo anúncio detectado! Iniciando próximo...")
                        if not self._click_node(xml_content, "receba"):
                            self.tap(self.screen_width // 2, int(self.screen_height * 0.65))
                        self._sleep(5)
                        inicio_anuncio = time.monotonic()
                        continue
                        
                    if "já ganhou" in content_lower or "ja ganhou" in content_lower:
                        self._emit_log("info", "🎁 Mensagem 'Já ganhou' detectada! Fechando anúncio e voltando...")
                        self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                        self._sleep(3)
                        estado = "NoKwaiGolds"
                        continue

                    tempo_decorrido = time.monotonic() - inicio_anuncio
                    if tempo_decorrido > TIMEOUT_ANUNCIO:
                        if tempo_decorrido > TIMEOUT_ANUNCIO + 20:
                            self._emit_log("warning", "🚨 Muito tempo preso no anúncio. Voltando em vez de fechar o app...")
                            self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                            self._sleep(3)
                            estado = "Navegando"
                            inicio_navegando = time.monotonic()
                            continue
                            
                        self._emit_log("info", f"⏳ Timeout ({TIMEOUT_ANUNCIO}s). Apertando <- para tentar pular...")
                        self.tap(int(self.screen_width * 0.08), int(self.screen_height * 0.08))
                        self._sleep(3)
                        continue
                        
                    self._sleep(2)
                
                else:  # estado == "Navegando"
                    tempo_navegando = time.monotonic() - inicio_navegando
                    
                    # 1. Tenta fechar popups (X ou Sair) que estejam no caminho
                    if self.clicar_x_popup(xml_content):
                        self._emit_log("info", "🧭 [Navegando] Popup fechado. Verificando tela...")
                        self._sleep(2)
                        continue
                    
                    # 2. Se estiver na tela inicial do Kwai, procura o botão rosa flutuante
                    if self._detectar_tela_inicial_kwai(xml_content):
                        self._emit_log("info", "🏠 [Navegando] Tela inicial do Kwai detectada! Procurando botão rosa de Kwai Golds...")
                        if self._clicar_botao_rosa_kwai_golds(xml_content):
                            self._emit_log("info", "🩷 [Navegando] Botão rosa clicado! Aguardando tela de Kwai Golds...")
                            self._sleep(5)
                            continue
                        else:
                            self._emit_log("warning", "🩷 [Navegando] Botão rosa não encontrado no XML. Tentando BACK...")
                            self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                            self._sleep(3)
                            continue
                    
                    # 3. Se demorar demais (TIMEOUT_NAVEGANDO), reinicia o app e procura o botão rosa
                    if tempo_navegando > TIMEOUT_NAVEGANDO:
                        tentativas_reinicio += 1
                        self._emit_log("warning", f"🚨 [Navegando] Timeout de {TIMEOUT_NAVEGANDO}s! Reiniciando o app (tentativa {tentativas_reinicio})...")
                        self.fechar_kwai()
                        self._sleep(2)
                        self.manter_tela_ligada()
                        self.abrir_kwai()
                        self._sleep(4)
                        
                        # Fecha popups que aparecerem após abrir o app
                        for _ in range(3):
                            if not self._running:
                                break
                            xml_reopen = self.obter_xml_tela()
                            if xml_reopen and "xml" in xml_reopen:
                                # Se já voltou pro Kwai Golds, ótimo!
                                if self._verificar_tela_kwai_golds(xml_reopen):
                                    self._emit_log("info", "✅ [Navegando] Voltou para Kwai Golds após reinício!")
                                    estado = "NoKwaiGolds"
                                    tentativas_reinicio = 0
                                    break
                                # Tenta fechar popups
                                if self.clicar_x_popup(xml_reopen):
                                    self._sleep(2)
                                    continue
                                # Tenta clicar no botão rosa
                                if self._clicar_botao_rosa_kwai_golds(xml_reopen):
                                    self._emit_log("info", "🩷 [Navegando] Botão rosa clicado após reinício! Aguardando...")
                                    self._sleep(5)
                                    break
                            self._sleep(2)
                        
                        inicio_navegando = time.monotonic()
                        continue
                    
                    # 4. Fallback: tenta BACK genérico
                    self._emit_log("info", f"🧭 [Navegando] Tentando voltar para Kwai Golds ({tempo_navegando:.0f}s/{TIMEOUT_NAVEGANDO}s)...")
                    self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                    self._sleep(3)
                
        except Exception as e:
            self._emit_log("error", f"Erro inesperado no Modo Anúncios: {e}")
            self.stats["erros"] += 1

    def pausa_longa(self):
        duracao = random.uniform(30, 90)
        self._emit_log("info", f"Pausa longa de {duracao:.0f}s...")
        self._sleep(duracao)

    def executar(self):
        """Executa o loop principal do bot."""
        self._running = True
        self._paused = False
        total_videos = self.config["total_videos"]
        ativar_pausas = self.config["pausas"]

        self._emit_status("running")

        # Fase 1
        self._emit_log("info", "=== FASE 1: Inicialização e Protocolo de Evasão ===")
        self._emit_log("info", "🤖 [Evasão] Iniciando verificações avançadas de dispositivo...")
        if not self.verificar_dispositivo():
            self._emit_status("stopped")
            self._running = False
            return False

        self.obter_resolucao()
        if not self.detectar_kwai():
            self._emit_status("stopped")
            self._running = False
            return False

        # Fase 2
        self._emit_log("info", "=== FASE 2: Preparacao e Protocolo de Evasão ===")
        self.manter_tela_ligada()

        # Fase 3
        if self.config.get("modo") == "Anúncios":
            # No modo Anúncios, assume que o usuário já está na tela do Kwai Golds
            self._emit_log("info", "📢 Modo Anúncios: assumindo que já está na tela do Kwai Golds.")
            self.executar_modo_anuncios()
        else:
            # No modo Vídeos, faz o protocolo completo de inicialização
            self.protocolo_evasao_inicial()
            self.abrir_kwai()
            self._sleep(3)
            self.fechar_popups()
            self.ir_para_feed()
            self._sleep(2)

            self._emit_log("info", "=== FASE 3: Assistindo Videos ===")
            self._emit_log("info", f"Meta: {total_videos} videos")
            self._emit_log("info", f"Tempo por video: {self.config['tempo_min']}-{self.config['tempo_max']}s")

            self.stats["inicio"] = datetime.now()

            try:
                videos_processados = 0
                consecutivas_lives = 0
                while videos_processados < total_videos and self._running:
                    current_video_idx = videos_processados + 1
                    if self._on_progress:
                        self._on_progress(current_video_idx, total_videos)

                    # --- ANÁLISE CONSTANTE SE O APP ESTÁ ABERTO ---
                    if not self.verificar_kwai_aberto():
                        self._emit_log("warning", "⚠️ Kwai não está aberto/focado! Recuperando aplicativo...")
                        self.stats["erros"] += 1
                        self._emit_stats()
                        self.manter_tela_ligada()
                        self.abrir_kwai()
                        self._sleep(3)
                        self.fechar_popups()
                        self.ir_para_feed()
                        self._sleep(2)

                    # --- ANÁLISE CONSTANTE DE TELA (POPUPS E LIVES) ---
                    xml_content = self.obter_xml_tela()
                    
                    if xml_content and "xml" in xml_content:
                        if self.clicar_x_popup(xml_content):
                            self._sleep(2)
                            continue
                            
                        # Verifica se clicou acidentalmente no botão de Kwai Golds (FAB)
                        if self._verificar_tela_kwai_golds(xml_content):
                            self._emit_log("warning", "⚠️ Tela de Kwai Golds detectada acidentalmente! Voltando para os vídeos...")
                            self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                            self._sleep(2)
                            continue

                    # --- DETECÇÃO E PULO DE LIVES ---
                    if self.detectar_live(xml_content):
                        self._emit_log("warning", "🚨 Transmissão ao vivo (Live) detectada! Reiniciando o aplicativo...")
                        self.fechar_kwai()
                        self._sleep(2.5)
                        self.manter_tela_ligada()
                        self.abrir_kwai()
                        self._sleep(4.5)
                        self.fechar_popups()
                        self.ir_para_feed()
                        self._sleep(2)
                        continue

                    if current_video_idx % 15 == 0:
                        self.manter_tela_ligada()

                    # --- VERIFICAR SE ESTÁ NA TELA/ABA 'PARA VOCÊ' ---
                    esta_na_for_you = False
                    para_voce_match = re.search(r'<node[^>]*text="Para você"[^>]*selected="([^"]+)"', xml_content, re.IGNORECASE)
                    if para_voce_match:
                        is_selected = para_voce_match.group(1).lower() == "true"
                        if is_selected:
                            esta_na_for_you = True
                        else:
                            self._emit_log("info", "🔄 Detectado aba incorreta. Tentando clicar em 'Para você'...")
                            self._click_node(xml_content, "Para você", exato=False)
                            self._sleep(2.5)
                            xml_content = self.obter_xml_tela()
                            if xml_content:
                                match_nov = re.search(r'<node[^>]*text="Para você"[^>]*selected="([^"]+)"', xml_content, re.IGNORECASE)
                                if match_nov and match_nov.group(1).lower() == "true":
                                    esta_na_for_you = True

                    if not esta_na_for_you:
                        self._emit_log("warning", "⚠️ Fora da tela principal 'Para você'! Tentando recuperação rápida...")
                        
                        # Tenta voltar usando KEYCODE_BACK
                        self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                        self._sleep(2.0)
                        xml_content = self.obter_xml_tela()
                        if xml_content:
                            match_nov = re.search(r'<node[^>]*text="Para você"[^>]*selected="([^"]+)"', xml_content, re.IGNORECASE)
                            if match_nov and match_nov.group(1).lower() == "true":
                                self._emit_log("info", "✅ Recuperado com sucesso via botão voltar.")
                                continue
                                
                        # Tenta ir para o feed clicando no botão Início
                        self._emit_log("info", "🔄 Tentando ir para o feed via botão de Início...")
                        self.ir_para_feed()
                        self._sleep(2.0)
                        xml_content = self.obter_xml_tela()
                        if xml_content:
                            match_nov = re.search(r'<node[^>]*text="Para você"[^>]*selected="([^"]+)"', xml_content, re.IGNORECASE)
                            if match_nov and match_nov.group(1).lower() == "true":
                                self._emit_log("info", "✅ Recuperado com sucesso via botão Início.")
                                continue

                        # Se tudo falhar, aí sim reinicia o aplicativo
                        self._emit_log("warning", "🚨 Falha na recuperação rápida! Reiniciando o Kwai...")
                        self.fechar_kwai()
                        self._sleep(2.5)
                        self.manter_tela_ligada()
                        self.abrir_kwai()
                        self._sleep(4.5)
                        self.fechar_popups()
                        self.ir_para_feed()
                        self._sleep(2)
                        consecutivas_lives = 0
                        continue # Volta para o início do loop para reavaliar a tela

                    # --- ABRIR COMENTÁRIOS ALEATORIAMENTE (Aprox 5% de chance) ---
                    if random.random() < 0.05:
                        self._emit_log("info", "💬 Simulando humano: Abrindo e lendo comentários...")
                        if self._clicar_botao_comentarios(xml_content):
                            self._sleep(2.5)
                            # Desliza para baixo nos comentários (apenas rola a lista)
                            self.swipe_proximo_video() 
                            self._sleep(random.uniform(3.0, 5.0))
                            # Fecha os comentários apertando o botão voltar (como solicitado)
                            self._emit_log("info", "💬 Fechando comentários apertando Voltar...")
                            self.adb_shell("input", "keyevent", "KEYCODE_BACK")
                            self._sleep(2.0)
                            # Re-carrega o XML da tela pois fechamos os comentários
                            xml_content = self.obter_xml_tela()
                            if xml_content:
                                match_nov = re.search(r'<node[^>]*text="Para você"[^>]*selected="([^"]+)"', xml_content, re.IGNORECASE)
                                if match_nov and match_nov.group(1).lower() == "true":
                                    esta_na_for_you = True



                    # --- EVASÃO PERIÓDICA AVANÇADA ---
                    self.executar_evasao_periodica(current_video_idx)

                    self.assistir_video(current_video_idx)

                    if not self._running:
                        break

                    videos_processados += 1

                    # --- REINÍCIO PERIÓDICO DO APLICATIVO A CADA 15 VÍDEOS ---
                    if videos_processados % 15 == 0:
                        self._emit_log("info", "🔄 Realizando reinício periódico do Kwai para limpar cache e otimizar...")
                        self.fechar_kwai()
                        self._sleep(2)
                        self.manter_tela_ligada()
                        self.abrir_kwai()
                        self._sleep(3)
                        self.fechar_popups()
                        self.ir_para_feed()
                        self._sleep(2)
                    else:
                        # Rolar normal: Ocasionalmente volta para o vídeo anterior, senão passa para o próximo
                        if random.random() < 0.04 and videos_processados > 1:
                            self._emit_log("info", "🔄 Voltando temporariamente para o vídeo anterior...")
                            center_x = self.screen_width // 2
                            start_y = int(self.screen_height * random.uniform(0.15, 0.25))
                            end_y = int(self.screen_height * random.uniform(0.70, 0.80))
                            duracao = random.randint(300, 600)
                            self.swipe(center_x, start_y, center_x, end_y, duracao)
                            self._sleep(random.uniform(3.0, 6.0))
                            
                            self._emit_log("info", "Passando novamente para o próximo vídeo...")
                            self.swipe_proximo_video()
                        else:
                            self._emit_log("info", "Passando para o proximo video...")
                            self.swipe_proximo_video()
                        
                        self._sleep(random.uniform(1.0, 2.5))

                    if ativar_pausas and videos_processados % random.randint(25, 40) == 0:
                        self.pausa_longa()

                    if videos_processados % 10 == 0:
                        progresso = (videos_processados / total_videos) * 100
                        self._emit_log("info", f"Progresso: {videos_processados}/{total_videos} ({progresso:.1f}%)")

            except Exception as e:
                self._emit_log("error", f"Erro inesperado: {e}")
                self.stats["erros"] += 1

        # Fase 4
        self._emit_log("info", "=== FASE 4: Finalizacao e Protocolo de Saída ===")
        self.protocolo_evasao_final()
        self._emit_stats()

        final_status = "finished" if self._running else "stopped"
        self._running = False
        self._emit_status(final_status)
        self._emit_log("info", "Sessao finalizada!")
        return True


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Kwai Bot - Automacao ADB para ganhar Kwai Golds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  python kwai_bot.py                          # Configuracao padrao (100 videos)
  python kwai_bot.py --videos 300             # Assistir 300 videos
  python kwai_bot.py --tempo-min 15 --tempo-max 35
  python kwai_bot.py --videos 500 --pausas    # Com pausas longas
        """
    )
    parser.add_argument("--videos", type=int, default=100)
    parser.add_argument("--tempo-min", type=int, default=15)
    parser.add_argument("--tempo-max", type=int, default=35)
    parser.add_argument("--pausas", action="store_true")

    args = parser.parse_args()

    if args.tempo_min >= args.tempo_max:
        print("Erro: --tempo-min deve ser menor que --tempo-max")
        sys.exit(1)

    config = {
        "total_videos": args.videos,
        "tempo_min": args.tempo_min,
        "tempo_max": args.tempo_max,
        "pausas": args.pausas,
    }

    bot = KwaiBot(config)
    success = bot.executar()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
