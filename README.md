# Kwai Gold Farm Bot (KwaiBot)

KwaiBot é um bot automatizado de fazenda de Kwai Golds, desenvolvido em Python utilizando comunicação via ADB (Android Debug Bridge) para interagir diretamente com dispositivos Android. Ele possui uma interface gráfica moderna (CustomTkinter) e rotinas sofisticadas de evasão anti-detecção.

## 🚀 Funcionalidades

### 📺 Modos de Execução
*   **Modo Vídeos:** Assiste ao feed principal do Kwai, realizando scrolls automáticos, pausas dinâmicas e interações para acumular Kwai Golds de forma contínua.
*   **Modo Anúncios (Kwai Gold):** Focado puramente na visualização de anúncios dentro da tela do Kwai Gold. O bot assume que o dispositivo já está na tela de recompensas e interage de forma otimizada para assistir a anúncios repetidamente, detectando automaticamente o fechamento ("sair") dos anúncios ao término.

### 🛡️ Sistema Avançado de Evasão (Anti-Ban)
Para evitar detecção e comportamento repetitivo, o bot executa:
*   **Simulação de Comentários:** Abre e rola a aba de comentários ocasionalmente para simular comportamento humano.
*   **Interações de Tela:** Toques curtos de engajamento na tela de forma randômica.
*   **Evasão Física:** Ajuste aleatório de brilho do dispositivo e swipes horizontais (exploração de perfil).
*   **Ações de Rede/Dispositivo:** Alternância temporária do Wi-Fi para renovar a conectividade e limpeza periódica do cache do aplicativo Kwai.
*   **Tempos Dinâmicos:** Intervalos de tempo e velocidades de scroll gerados de forma randômica para cada sessão.

### 🧩 Detecção Inteligente
*   **Detecção de Lives:** Identifica se o feed entrou em uma transmissão ao vivo. Caso positivo, realiza uma evasão rápida (botão voltar + scroll) ou reinicia o aplicativo se persistir por muitas vezes seguidas (apenas no modo Vídeos).
*   **Fechamento de Popups:** Detecta automaticamente popups com botões de fechar ("X") mapeando a hierarquia do layout XML e clica neles de forma proativa.

---

## 🛠️ Pré-requisitos

1.  **Python 3.10+** instalado em sua máquina.
2.  **Dispositivo Android** com:
    *   *Depuração USB* ativada nas Opções do Desenvolvedor.
    *   Conectado ao computador via cabo USB e autorizado para depuração.
3.  **Dependências Python**:
    ```bash
    pip install customtkinter pillow darkdetect
    ```
4.  **ADB (Android Debug Bridge)** configurado e os arquivos executáveis (`adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll`) presentes na raiz do projeto.

---

## 💻 Como Usar

### Executando com Interface Gráfica
Para abrir o painel de controle do bot, execute:
```bash
python kwai_gui.py
```

### Executando em Linha de Comando (Modo Direto)
Se preferir rodar o bot diretamente pelo terminal:
```bash
python kwai_bot.py
```

---

## 📦 Compilação / Geração do Executável

O projeto inclui um script automatizado de build para gerar uma versão executável portátil (empacotada em `.exe` com todas as dependências do CustomTkinter e o ADB).

Para gerar o build:
```powershell
python build.py
```
O executável final e seus recursos serão gerados no diretório `dist/KwaiBot/`. Para distribuir, copie a pasta `KwaiBot/` completa.

---

## 📝 Licença e Termos
Este projeto foi desenvolvido estritamente para fins de estudos e automação pessoal. O uso de bots pode violar os termos de serviço do aplicativo Kwai. Use por sua própria conta e risco.
