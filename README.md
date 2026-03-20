# Conversor de Musicas e Videos

Aplicacao web para baixar videos e musicas do YouTube em MP4 e MP3, com escolha de qualidade.

## Funcionalidades

- Download de videos em MP4 (360p ate 4K)
- Download de musicas em MP3 (64 a 320 kbps)
- Preview do video ao colar o link (thumbnail, titulo e canal)
- Deteccao automatica das qualidades disponiveis
- Barra de progresso durante o download
- Audio em AAC (compativel com Windows Media Player)
- Interface responsiva (funciona no celular)

## Estrutura do Projeto

```
CarolBaixar/
├── index.html              # Frontend (pagina web)
├── README.md
└── backend/
    ├── app.py              # Servidor Python (Flask + yt-dlp)
    ├── requirements.txt    # Dependencias Python
    └── Dockerfile          # Para deploy em producao
```

## Pre-requisitos

- [Python 3.10+](https://www.python.org/downloads/)
- [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) (para conversao de audio/video)
- [Deno](https://deno.land/) (runtime JS necessario para o yt-dlp resolver challenges do YouTube)

## Instalacao

### 1. Clonar o repositorio

```bash
git clone https://github.com/seu-usuario/CarolBaixar.git
cd CarolBaixar
```

### 2. Instalar FFmpeg e Deno

**Windows (winget):**
```bash
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

Copie o `ffmpeg.exe`, `ffprobe.exe` e `deno.exe` para uma pasta no PATH (ex: `C:\ffmpeg`).

**Linux/Mac:**
```bash
# FFmpeg
sudo apt install ffmpeg        # Ubuntu/Debian
brew install ffmpeg             # macOS

# Deno
curl -fsSL https://deno.land/install.sh | sh
```

### 3. Instalar dependencias Python

```bash
cd backend
pip install -r requirements.txt
```

### 4. Iniciar o backend

```bash
python app.py
```

O servidor inicia em `http://localhost:5000`.

### 5. Abrir o frontend

Abra o `index.html` no navegador (ou use o Live Server do VS Code).

## Configuracao

### Backend URL

No `index.html`, a variavel `BACKEND_URL` aponta para o backend:

```javascript
const BACKEND_URL = 'http://localhost:5000';
```

Para producao, altere para a URL do seu servidor.

### Caminho do FFmpeg/Deno

No `backend/app.py`, a variavel `TOOLS_DIR` define onde estao o ffmpeg e deno:

```python
TOOLS_DIR = r"C:\ffmpeg"
```

Ajuste conforme o seu sistema.

## Deploy em Producao

### Frontend - GitHub Pages

1. Suba o `index.html` para um repositorio no GitHub
2. Va em Settings > Pages > selecione a branch `main`
3. Altere `BACKEND_URL` para a URL do backend em producao

### Backend - Render.com (gratuito)

1. Crie uma conta em [render.com](https://render.com)
2. New > Web Service > conecte o repositorio
3. Configure:
   - **Root Directory:** `backend`
   - **Environment:** Docker
   - **Instance Type:** Free
4. O Dockerfile ja inclui ffmpeg. A URL gerada sera algo como `https://seu-app.onrender.com`

## API do Backend

### `GET /`
Health check. Retorna `{"status": "ok"}`.

### `GET /api/info?url=URL_DO_YOUTUBE`
Retorna informacoes do video:
```json
{
  "title": "Nome do Video",
  "channel": "Nome do Canal",
  "thumbnail": "https://...",
  "duration": 213,
  "qualities": [360, 480, 720, 1080, 1440, 2160]
}
```

### `GET /api/download?url=URL&format=mp4&quality=720`
Baixa e retorna o arquivo como stream.

**Parametros:**
| Parametro | Valores | Padrao |
|-----------|---------|--------|
| `url` | URL do YouTube | obrigatorio |
| `format` | `mp4`, `mp3` | `mp4` |
| `quality` | `360`, `480`, `720`, `1080`, `1440`, `2160` (video) ou `64`, `128`, `192`, `256`, `320` (audio) | `720` |

## Tecnologias

- **Frontend:** HTML, CSS, JavaScript (vanilla)
- **Backend:** Python, Flask, yt-dlp
- **Ferramentas:** FFmpeg (conversao), Deno (JS runtime para yt-dlp)
