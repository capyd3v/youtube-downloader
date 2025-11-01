import os
import yt_dlp
import requests
from flask import Flask, render_template, request, jsonify, send_file
import tempfile
import threading
import time
import re
import random
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

# Configuración global para yt-dlp
YDLP_OPTS = {
    'quiet': True,
    'no_warnings': False,
    'ignoreerrors': False,
    'extract_flat': False,
    'restrictfilenames': True,
    'socket_timeout': 30,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
            'player_skip': ['configs', 'webpage'],
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
}

def extract_video_id(url):
    """Extraer ID del video de forma robusta"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)',
        r'youtube\.com\/embed\/([^&?\n]+)',
        r'youtube\.com\/v\/([^&?\n]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_info_with_retry(url, max_retries=3):
    """Obtener información del video con múltiples estrategias"""
    strategies = [
        # Estrategia 1: Normal
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        },
        # Estrategia 2: Minimalista
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        },
        # Estrategia 3: Sin extractor args
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
    ]
    
    for attempt in range(max_retries):
        try:
            strategy = strategies[attempt % len(strategies)]
            ydl_opts = YDLP_OPTS.copy()
            ydl_opts.update(strategy)
            
            # Rotar User-Agent
            ydl_opts['http_headers']['User-Agent'] = get_random_user_agent()
            
            print(f"🔍 Intento {attempt + 1} con estrategia {attempt % len(strategies) + 1}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                print(f"✅ Información obtenida exitosamente")
                return info
                
        except yt_dlp.DownloadError as e:
            error_msg = str(e)
            print(f"❌ Intento {attempt + 1} falló: {error_msg}")
            
            if "400" in error_msg:
                print("🔄 Error 400, cambiando estrategia...")
            elif "429" in error_msg:
                print("🚫 Rate limit detectado, esperando...")
                time.sleep(10)
            elif "403" in error_msg:
                print("🔒 Error 403, intentando con configuración diferente...")
            
            if attempt == max_retries - 1:
                raise e
                
            time.sleep(2 ** attempt)  # Backoff exponencial
            
        except Exception as e:
            print(f"❌ Intento {attempt + 1} falló con error inesperado: {str(e)}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(2 ** attempt)
    
    return None

def get_random_user_agent():
    """Generar User-Agent aleatorio"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    return random.choice(user_agents)

def get_thumbnail_url(video_id):
    """Obtener URL de miniatura"""
    qualities = ['maxresdefault', 'hqdefault', 'mqdefault', 'default']
    for quality in qualities:
        url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
        try:
            if requests.head(url, timeout=5).status_code == 200:
                return url
        except:
            continue
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

class DownloadThread(threading.Thread):
    def __init__(self, url, format_id, download_id):
        threading.Thread.__init__(self)
        self.url = url
        self.format_id = format_id
        self.download_id = download_id
        self.filename = None
        self.error = None

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            progress = d.get('_percent_str', '0%').strip()
            progress_clean = re.sub(r'\x1b\[[0-9;]*m', '', progress)
            
            try:
                progress_value = float(progress_clean.strip('%'))
                download_progress[self.download_id] = {
                    'progress': progress_value,
                    'speed': d.get('_speed_str', 'N/A'),
                    'eta': d.get('_eta_str', 'N/A'),
                    'status': 'downloading'
                }
            except ValueError:
                download_progress[self.download_id] = {
                    'progress': 0,
                    'status': 'downloading'
                }
                
        elif d['status'] == 'finished':
            download_progress[self.download_id] = {
                'progress': 100,
                'status': 'processing',
                'filename': d.get('filename', '')
            }

    def run(self):
        try:
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'iniciando',
                'error': None
            }
            
            # Crear directorio temporal
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Configuración de descarga
            ydl_opts = YDLP_OPTS.copy()
            ydl_opts.update({
                'outtmpl': os.path.join(download_folder, '%(title).100s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
            })
            
            # Configurar formato según selección
            if self.format_id == 'best':
                ydl_opts['format'] = 'best[height<=720]'
            elif self.format_id == 'worst':
                ydl_opts['format'] = 'worst'
            elif self.format_id.startswith('audio'):
                ydl_opts['format'] = 'bestaudio'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            else:
                # Formato específico de video
                ydl_opts['format'] = 'best[height<=720]'
            
            # Rotar User-Agent para descarga
            ydl_opts['http_headers']['User-Agent'] = get_random_user_agent()
            
            print(f"📥 Iniciando descarga con formato: {self.format_id}")
            
            # Intentar descarga con reintentos
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(self.url, download=True)
                        self.filename = ydl.prepare_filename(info)
                        
                        # Actualizar progreso a completado
                        download_progress[self.download_id] = {
                            'progress': 100,
                            'status': 'completed',
                            'filename': os.path.basename(self.filename),
                            'title': info.get('title', 'video')
                        }
                        print(f"✅ Descarga completada: {self.filename}")
                        break
                        
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"🔄 Reintentando descarga... ({attempt + 1})")
                        time.sleep(3)
                        continue
                    else:
                        raise e
                
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error en descarga: {error_msg}")
            
            if "400" in error_msg:
                self.error = "Error de solicitud. La URL puede ser inválida o el video no está disponible."
            elif "429" in error_msg:
                self.error = "YouTube está bloqueando solicitudes. Espera unos minutos e intenta nuevamente."
            elif "403" in error_msg:
                self.error = "Acceso denegado. El video puede tener restricciones."
            elif "Private" in error_msg:
                self.error = "Este video es privado y no se puede descargar."
            elif "Unavailable" in error_msg:
                self.error = "El video no está disponible o fue eliminado."
            else:
                self.error = f"Error en la descarga: {error_msg}"
            
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'error',
                'error': self.error
            }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/video_info', methods=['POST'])
def get_video_info():
    """Obtener información del video"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    try:
        # Obtener información con reintentos
        video_info = get_video_info_with_retry(url)
        if not video_info:
            return jsonify({'success': False, 'error': 'No se pudo obtener información del video después de varios intentos'})
        
        # Procesar formatos disponibles
        available_formats = video_info.get('formats', [])
        video_formats = []
        audio_formats = []
        
        for fmt in available_formats:
            format_id = fmt.get('format_id', '')
            resolution = fmt.get('format_note', 'Unknown')
            ext = fmt.get('ext', 'unknown')
            filesize = fmt.get('filesize')
            vcodec = fmt.get('vcodec', 'none')
            acodec = fmt.get('acodec', 'none')
            
            # Filtrar formatos inválidos
            if not resolution or resolution.lower() == 'unknown':
                continue
            
            # Formato de video (con video)
            if vcodec != 'none' and vcodec is not None:
                size_text = f" - {filesize / (1024*1024):.1f} MB" if filesize else ""
                has_audio = acodec != 'none' and acodec is not None
                audio_indicator = " 🔊" if has_audio else " 🔇"
                
                video_formats.append({
                    'id': format_id,
                    'display': f"{resolution} ({ext.upper()}){size_text}{audio_indicator}",
                    'resolution': resolution,
                    'extension': ext,
                    'has_audio': has_audio,
                    'filesize': filesize
                })
            
            # Formatos de solo audio
            elif acodec != 'none' and vcodec == 'none':
                audio_formats.append({
                    'id': format_id,
                    'display': f"Audio only ({ext.upper()}) - {filesize / (1024*1024):.1f} MB" if filesize else f"Audio only ({ext.upper()})",
                    'extension': ext
                })
        
        # Ordenar formatos de video por resolución
        def get_resolution_value(res):
            try:
                if 'p' in res.lower():
                    return int(res.lower().replace('p', ''))
                elif 'x' in res:
                    return int(res.split('x')[1])
                return 0
            except:
                return 0
        
        video_formats.sort(key=lambda x: get_resolution_value(x['resolution']), reverse=True)
        
        # Agregar opciones predefinidas
        predefined_formats = [
            {'id': 'best', 'display': '🎯 Mejor calidad (hasta 720p)'},
            {'id': 'worst', 'display': '📉 Peor calidad (para evitar bloqueos)'},
            {'id': 'audio', 'display': '🔊 Solo audio (MP3)'}
        ]
        
        # Obtener miniatura
        thumbnail_url = get_thumbnail_url(video_id)
        
        return jsonify({
            'success': True,
            'title': video_info.get('title', 'Sin título'),
            'duration': video_info.get('duration', 0),
            'thumbnail': thumbnail_url,
            'description': video_info.get('description', '')[:500] + '...' if video_info.get('description') else 'Sin descripción',
            'formats': {
                'video': video_formats[:8],  # Limitar a 8 formatos máximo
                'audio': audio_formats[:4],  # Limitar a 4 formatos máximo
                'predefined': predefined_formats
            }
        })
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error general: {error_msg}")
        
        if "400" in error_msg:
            return jsonify({'success': False, 'error': 'Error de solicitud. Verifica que la URL sea correcta.'})
        elif "429" in error_msg:
            return jsonify({'success': False, 'error': 'YouTube está bloqueando solicitudes. Espera 10-15 minutos.'})
        elif "Unavailable" in error_msg:
            return jsonify({'success': False, 'error': 'El video no está disponible o fue eliminado.'})
        else:
            return jsonify({'success': False, 'error': f'Error al obtener información: {error_msg}'})

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'best')
    
    if not url or not format_id:
        return jsonify({'success': False, 'error': 'URL y formato requeridos'})
    
    download_id = f"dl_{int(time.time())}_{hash(url)}"
    
    download_thread = DownloadThread(url, format_id, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada'
    })

@app.route('/api/progress/<download_id>')
def get_progress(download_id):
    progress = download_progress.get(download_id, {
        'progress': 0,
        'status': 'unknown'
    })
    return jsonify(progress)

@app.route('/api/download/<download_id>')
def download_file(download_id):
    progress = download_progress.get(download_id, {})
    
    if progress.get('status') != 'completed':
        return jsonify({'success': False, 'error': 'Descarga no completada'})
    
    filename = progress.get('filename', '')
    if not filename:
        return jsonify({'success': False, 'error': 'Archivo no encontrado'})
    
    temp_dir = tempfile.gettempdir()
    download_folder = os.path.join(temp_dir, 'youtube_downloads')
    file_path = os.path.join(download_folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': 'Archivo no existe'})
    
    if download_id in download_progress:
        del download_progress[download_id]
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/cancel_download/<download_id>', methods=['POST'])
def cancel_download(download_id):
    if download_id in download_progress:
        del download_progress[download_id]
    return jsonify({'success': True, 'message': 'Descarga cancelada'})

@app.route('/api/status')
def get_status():
    return jsonify({
        'status': 'active',
        'message': '✅ Servicio funcionando con yt-dlp mejorado',
        'version': 'Configuración anti-bloqueos activada'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
