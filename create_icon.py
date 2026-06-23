# -*- coding: utf-8 -*-
"""Gera o ícone .ico para o executável do Kwai Bot."""

from PIL import Image, ImageDraw, ImageFont

def create_ico():
    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Círculo externo - laranja Kwai
        p = max(1, size // 32)
        draw.ellipse([p, p, size - p, size - p], fill="#FF6B2C")

        # Círculo interno - dourado (gold)
        inner = max(3, size // 6)
        draw.ellipse([inner, inner, size - inner, size - inner], fill="#FFB800")

        # Letra "K" no centro
        font_size = max(8, int(size * 0.45))
        try:
            font = ImageFont.truetype("segoeui.ttf", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

        draw.text((size // 2, size // 2), "K", fill="#0D0F14", font=font, anchor="mm")
        images.append(img)

    # Salva como .ico com múltiplos tamanhos
    images[-1].save(
        "kwai_bot.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    print("kwai_bot.ico criado com sucesso!")

if __name__ == "__main__":
    create_ico()
