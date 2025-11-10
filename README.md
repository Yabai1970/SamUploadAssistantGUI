# SamUploadAssistantGUI

> 🚀 **Release em destaque**
>
> [SamUploadAssistantGUI v1.0 – Primeira release publica](https://github.com/Yabai1970/SamUploadAssistantGUI/releases/latest)
>
> - ⬇️ Instalador oficial (Forge Installer) para configurar atalhos e dependencias automaticamente.
> - 📦 Build portatil (ZIP PyInstaller) para executar onde preferir, sem instalacao.
>
> Escolha o pacote ideal diretamente na pagina de releases do GitHub.

---

SamUploadAssistantGUI e uma interface grafica (GUI) criada para tornar o uso do [Upload-Assistant](https://github.com/Audionut/Upload-Assistant) acessivel a qualquer pessoa. O aplicativo cuida da instalacao de dependencias, prepara o ambiente e oferece um assistente completo para que os fluxos de upload rodem em poucos cliques.

## ✨ Principais recursos
- Interface moderna com CustomTkinter (fallback automatico para Tkinter puro).
- Verificacao e instalacao automatica de FFmpeg, FFprobe e MediaInfo, usando pacotes offline inclusos ou download com barra de progresso.
- Assistente guiado para criar o `config.py`, cobrindo trackers, clientes torrent, Discord, Zipline e muito mais.
- PromptBridge que traduz os prompts do Upload-Assistant original, exibe estados em tempo real e salva logs.
- Integracao transparente com a copia modificada do Upload-Assistant em `third_party/Upload-Assistant`, garantindo compatibilidade com o fluxo em portugues.

## 🤝 Relacao com o Upload-Assistant original
Este projeto depende de ajustes locais no Upload-Assistant. A pasta `third_party/Upload-Assistant` inclui:
- Mensagens traduzidas e valores padrao alinhados com a comunidade Samaritano.
- Uso da variavel de ambiente `UA_BASE_DIR` para a GUI controlar diretorios de trabalho, cache e configuracao em `%LOCALAPPDATA%/UploadAssistant` (Windows) ou `~/.local/share/UploadAssistant` (Linux/macOS).
- Mudancas em `upload.py` e modulos auxiliares para conviver com a camada grafica (tratamento de `cli_ui`, modo automatico, hosts de imagem, etc.).
- Correcoes para rodar em modo unattended, operar dentro do bundle PyInstaller e reaproveitar dependencias empacotadas.

Se atualizar o Upload-Assistant a partir do repositorio oficial, replique os ajustes acima para manter a compatibilidade com a GUI.

## 🧱 Pre-requisitos
- Python 3.10+ (validado com 3.11 e 3.12).
- Pip e venv disponiveis no PATH.
- Windows 10+ ou Linux/macOS com suporte a Tkinter (desenvolvimento focado no Windows).
- Opcional: [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter); caso contrario a app usa Tkinter puro.

## ⚙️ Instalacao para desenvolvimento
1. Clone o repositorio:
   ```bash
   git clone https://github.com/Yabai1970/SamUploadAssistantGUI.git
   cd SamUploadAssistantGUI
   ```
2. Crie e ative um ambiente virtual:
   - Windows
     ```powershell
     py -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - Linux/macOS
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
3. Instale as dependencias usadas pela GUI e pelo Upload-Assistant customizado:
   ```bash
   pip install -r requirements.txt
   ```
4. Confirme que `third_party/Upload-Assistant` esta presente. Caso substitua por outra copia, aplique os patches listados em [Relacao com o Upload-Assistant original](#-relacao-com-o-upload-assistant-original).

## ▶️ Uso rapido
### Iniciando a GUI
- Com o ambiente virtual ativo, execute:
  ```bash
  python ua_gui.py
  ```
- Na primeira execucao, a app cria os diretorios em `.appdata` (modo desenvolvimento) ou `%LOCALAPPDATA%/UploadAssistant` (modo empacotado) e valida o `config.py`.

### Primeiro acesso
- O botao **Assistente de Configuracao** abre um wizard que guia o preenchimento do `config.py` (TMDb, hosts de imagem, trackers padrao, credenciais do qBittorrent, avatar, etc.).
- Tambem e possivel editar o arquivo completo pelo editor embutido ou apontar para um `config.py` existente (ex.: `example-config.py`).

### Executando uploads
- A aba principal permite escolher pastas, acompanhar logs em tempo real e responder prompts que antes so existiam no terminal.
- FFmpeg, FFprobe e MediaInfo sao monitorados no cabecalho; se faltarem, basta clicar para instalar automaticamente.
- Logs detalhados ficam em `logs/ua_gui.log` (GUI) e `logs/upload-assistant.log` (execucoes do script principal).

## 🤖 Gestao automatica de dependencias
- **Offline first:** se os binarios estiverem em `resources/ffmpeg` e `resources/mediainfo`, sao copiados para `APP_DIR/bin`.
- **Fallback online:** caso faltem, o app baixa automaticamente a distribuicao correta (Gyan.dev para Windows, John Van Sickle para Linux, MediaArea para MediaInfo), valida o conteudo e instala.
- Os caminhos resultantes sao expostos via `FFMPEG_BIN`, `FFPROBE_BIN` e `MEDIAINFO_BIN`, garantindo que o Upload-Assistant encontre tudo sem configuracao manual.

## 🗂️ Estrutura de diretorios
| Caminho | Descricao |
| --- | --- |
| `ua_gui.py` | Codigo principal da interface grafica. |
| `requirements.txt` | Dependencias compartilhadas entre GUI e Upload-Assistant customizado. |
| `resources/` | Icones e pacotes opcionais de FFmpeg/MediaInfo. |
| `third_party/Upload-Assistant/` | Copia do Upload-Assistant com ajustes locais. |
| `.appdata/` | Ambiente de execucao em modo desenvolvimento (`%LOCALAPPDATA%/UploadAssistant` quando empacotado). |
| `logs/` | Logs da GUI e do Upload-Assistant. |
| `pyi_hooks/` | Hooks extras usados pelo PyInstaller. |
| `ua_gui.spec` | Spec pronta para gerar o executavel Windows. |

## 📦 Empacotando um executavel
O projeto inclui uma spec pronta para PyInstaller 6.x:

```bash
pyinstaller ua_gui.spec
```

O build gera `dist/SamUploadAssistant` com a aplicacao, o Upload-Assistant modificado e os recursos necessarios. Se adicionar novas dependencias Python, atualize `requirements.txt` e, se preciso, o `hiddenimports` em `ua_gui.spec`.

## 🆘 Diagnostico e suporte
- Use o menu **Abrir pasta de logs** para chegar rapidamente aos arquivos gerados.
- Falhas na instalacao automatica de FFmpeg/MediaInfo aparecem em `logs/ua_gui.log`.
- Para problemas ligados ao Upload-Assistant, valide o `config.py` no diretorio de dados e compare com `example-config.py`.
