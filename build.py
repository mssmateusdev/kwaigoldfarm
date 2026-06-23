# -*- coding: utf-8 -*-
"""
Script de build para gerar o KwaiBot.exe
Usa PyInstaller para empacotar tudo em um único executável.

Uso:
  python build.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def build():
    print("=" * 55)
    print("  KWAI BOT - Build do Executavel (.exe)")
    print("=" * 55)

    # Limpa builds anteriores
    for folder in ["build", "dist"]:
        p = SCRIPT_DIR / folder
        if p.exists():
            print(f"Limpando {folder}/...")
            shutil.rmtree(p)

    spec_file = SCRIPT_DIR / "KwaiBot.spec"
    if spec_file.exists():
        spec_file.unlink()

    # Encontra o caminho do customtkinter
    import customtkinter
    ctk_path = Path(customtkinter.__path__[0])

    # Ícone
    icon_path = SCRIPT_DIR / "kwai_bot.ico"
    icon_arg = f"--icon={icon_path}" if icon_path.exists() else ""

    # Monta o comando do PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",

        # Um único arquivo .exe
        "--onedir",

        # Sem console (é uma GUI)
        "--windowed",

        # Nome do executável
        "--name=KwaiBot",

        # Ícone
        icon_arg,

        # Incluir CustomTkinter como data (necessário para os assets/temas)
        f"--add-data={ctk_path};customtkinter/",

        # Incluir o módulo do bot
        f"--add-data={SCRIPT_DIR / 'kwai_bot.py'};.",

        # Imports ocultos que o PyInstaller pode não detectar
        "--hidden-import=customtkinter",
        "--hidden-import=PIL",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=darkdetect",

        # Sem confirmações
        "--noconfirm",

        # Limpar cache
        "--clean",

        # Arquivo principal
        str(SCRIPT_DIR / "kwai_gui.py"),
    ]

    # Remove args vazios
    cmd = [c for c in cmd if c]

    print("\nComando PyInstaller:")
    print(" ".join(cmd))
    print("\nCompilando... (isso pode levar 1-3 minutos)\n")

    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))

    if result.returncode != 0:
        print("\n[ERRO] Build falhou!")
        return False

    # Copia adb.exe e DLLs para a pasta de distribuição
    dist_dir = SCRIPT_DIR / "dist" / "KwaiBot"
    if dist_dir.exists():
        print("\nCopiando ADB e DLLs para a pasta de distribuicao...")
        for filename in ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]:
            src = SCRIPT_DIR / filename
            if src.exists():
                dst = dist_dir / filename
                shutil.copy2(str(src), str(dst))
                print(f"  Copiado: {filename}")
            else:
                print(f"  [!] Nao encontrado: {filename}")

        # Copia o ícone
        icon_src = SCRIPT_DIR / "kwai_bot.ico"
        if icon_src.exists():
            shutil.copy2(str(icon_src), str(dist_dir / "kwai_bot.ico"))

        print("\n" + "=" * 55)
        print("  BUILD CONCLUIDO COM SUCESSO!")
        print("=" * 55)
        print(f"\n  Executavel: {dist_dir / 'KwaiBot.exe'}")
        print(f"  Pasta:      {dist_dir}")
        print(f"\n  Para distribuir, copie a pasta inteira 'dist/KwaiBot/'")
        print(f"  que contem o .exe, adb.exe e todas as dependencias.")
        print("=" * 55)
        return True
    else:
        print("\n[ERRO] Pasta dist/KwaiBot nao encontrada!")
        return False


if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
