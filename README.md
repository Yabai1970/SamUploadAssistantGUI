# UploadAssistantApp

UploadAssistantApp é uma interface gráfica (GUI) criada para tornar o uso do [Upload-Assistant](https://github.com/Audionut/Upload-Assistant) acessível a qualquer pessoa. O aplicativo cuida da instalação de dependências, prepara o ambiente e oferece um assistente de configuração completo para que os fluxos de upload sejam executados com poucos cliques.

## Principais recursos
- Interface moderna construída com CustomTkinter (com fallback automático para Tkinter puro).
- Verificação e instalação automática do FFmpeg, FFprobe e MediaInfo, usando pacotes offline incluídos ou download online com barra de progresso.
- Assistente guiado para geração do `config.py`, incluindo campos para trackers, clientes torrent e integrações como Discord e Zipline.
- Ponte entre as perguntas interativas do Upload-Assistant e a GUI (PromptBridge), traduzindo prompts, exibindo estados e armazenando logs.
- Integração com uma cópia modificada do Upload-Assistant localizada em `third_party/Upload-Assistant`, garantindo compatibilidade com o fluxo em português.

## Relação com o Upload-Assistant original
Este projeto depende de alterações locais no Upload-Assistant. A pasta `third_party/Upload-Assistant` contém uma versão adaptada com:
- Mensagens e prompts traduzidos para português, além de defaults ajustados para a comunidade Samaritano.
- Uso intensivo da variável de ambiente `UA_BASE_DIR` para que a GUI controle diretórios de trabalho, cache e configuração em `%LOCALAPPDATA%/UploadAssistant` (Windows) ou `~/.local/share/UploadAssistant` (Linux/macOS).
- Ajustes em `upload.py` e módulos auxiliares para conviver com a ponte gráfica (tratamento de `cli_ui`, modo automático, atualização de hosts de imagem, etc.).
- Pequenas correções para rodar em modo unattended, atualizar imagens, garantir compatibilidade com dependências empacotadas e operar dentro do bundle PyInstaller.

Se você atualizar o Upload-Assistant a partir do repositório oficial, será necessário replicar esses ajustes para manter a integração com a GUI.

## Pré-requisitos
- Python 3.10 ou superior (testado com 3.11 e 3.12).
- Pip e venv disponíveis no PATH.
- Windows 10+ ou Linux/macOS com suporte a Tkinter. (A interface foi desenvolvida prioritariamente no Windows.)
- Opcional: [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter); caso não esteja instalado, o app recorre ao Tkinter padrão.

## Instalação
1. Clone o repositório:
   ```bash
   git clone https://github.com/<seu-usuario>/UploadAssistantApp.git
   cd UploadAssistantApp
   ```
2. Crie e ative um ambiente virtual:
   - Windows:
     ```powershell
     py -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - Linux/macOS:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
3. Instale as dependências Python usadas pela GUI *e* pelo Upload-Assistant adaptado:
   ```bash
   pip install -r requirements.txt
   ```
4. Verifique se a pasta `third_party/Upload-Assistant` está presente. Ela já vem com as modificações necessárias. Caso substitua por outra cópia, aplique os patches mencionados em [Relação com o Upload-Assistant original](#relação-com-o-upload-assistant-original).

## Uso
### Iniciando a GUI
- Com o ambiente virtual ativo, execute:
  ```bash
  python ua_gui.py
  ```
- Na primeira execução a aplicação cria os diretórios em `.appdata` (modo desenvolvimento) ou `%LOCALAPPDATA%/UploadAssistant` (modo empacotado) e verifica a existência do `config.py`.

### Primeiro acesso
- O botão “Assistente de Configuração” abre um wizard que orienta o preenchimento dos campos essenciais do `config.py` (TMDb, hosts de imagem, trackers padrão, credenciais do qBittorrent, avatar, etc.).
- É possível editar o arquivo completo via editor embutido ou apontar para um `config.py` existente (por exemplo, gerado pelo `example-config.py`).

### Executando uploads
- A aba principal permite selecionar pastas para upload, acompanhar logs em tempo real e responder prompts que antes só existiam no terminal.
- Os estados de FFmpeg, FFprobe e MediaInfo aparecem no cabeçalho; se algum binário estiver ausente, o aplicativo oferece instalação automática.
- Logs detalhados são gravados em `logs/ua_gui.log` (GUI) e `logs/upload-assistant.log` (execuções do script principal).

## Gestão automática de dependências
- **Offline first:** se os binários existirem em `resources/ffmpeg` e `resources/mediainfo`, eles são registrados e copiados para `APP_DIR/bin`.
- **Fallback online:** caso não sejam encontrados, o app baixa automaticamente a distribuição correta (Gyan.dev para Windows, John Van Sickle para Linux, MediaArea para MediaInfo), mostrando progresso e validando o conteúdo antes de instalar.
- Os caminhos resultantes são exportados via variáveis como `FFMPEG_BIN`, `FFPROBE_BIN` e `MEDIAINFO_BIN`, garantindo que o Upload-Assistant os encontre sem configuração manual.

## Estrutura de diretórios
| Caminho | Descrição |
| --- | --- |
| `ua_gui.py` | Código principal da interface gráfica. |
| `requirements.txt` | Dependências compartilhadas entre a GUI e o Upload-Assistant customizado. |
| `resources/` | Ícones e, opcionalmente, pacotes offline de FFmpeg/MediaInfo. |
| `third_party/Upload-Assistant/` | Cópia do Upload-Assistant com ajustes locais exigidos pela GUI. |
| `.appdata/` | Ambiente de execução quando rodando via fonte (equivalente a `%LOCALAPPDATA%/UploadAssistant`). |
| `logs/` | Arquivos de log gerados pela GUI e pelo Upload-Assistant. |
| `pyi_hooks/` | Hooks extras usados na geração do executável com PyInstaller. |
| `ua_gui.spec` | Especificação PyInstaller pronta para gerar um executável Windows. |

## Empacotando um executável
O projeto inclui uma spec pronta para PyInstaller 6.x:
```bash
pyinstaller ua_gui.spec
```
O build gera uma pasta `dist/SamUploadAssistant` com a aplicação, o Upload-Assistant modificado e os recursos necessários. Caso adicione novas dependências Python, ajuste `requirements.txt` e, se preciso, atualize a lista de pacotes em `ua_gui.spec`.

## Diagnóstico e suporte
- Use o menu “Abrir pasta de logs” na GUI para acessar rapidamente os arquivos gerados.
- Em caso de falhas durante a instalação automática de FFmpeg/MediaInfo, cheque `logs/ua_gui.log`.
- Para problemas ligados ao Upload-Assistant em si, valide o `config.py` no diretório de dados e compare com `example-config.py`.