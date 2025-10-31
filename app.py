import os
import yt_dlp
import requests
from flask import Flask, render_template, request, jsonify, send_file, session
from io import BytesIO
import tempfile
import threading
import time
import re
import random
import urllib.parse
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

# Servicios alternativos para obtener información de videos
ALTERNATIVE_SERVICES = [
    'https://inv.riverside.rocks',
    'https://invidious.snopyta.org',
    'https://yewtu.be',
    'https://inv.tux.pizza'
]

def get_random_service():
    return random.choice(ALTERNATIVE_SERVICES)

def extract_video_id(url):
    """Extraer ID del video de la URL"""
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

def get_video_info_alternative(video_id):
    """Obtener información del video usando servicios alternativos"""
    for attempt in range(3):
        try:
            service = get_random_service()
            api_url = f"{service}/api/v1/videos/{video_id}"
            
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                # Formatear la información similar a yt-dlp
                formats = []
                for fmt in data.get('formatStreams', []):
                    if fmt.get('type', '').startswith('video'):
                        formats.append({
                            'format_id': f"{fmt.get('quality', 'unknown')}_{fmt.get('url', '').split('/')[-1]}",
                            'format_note': fmt.get('quality', 'unknown'),
                            'ext': 'mp4',
                            'filesize': None,
                            'vcodec': 'avc1.42001E',
                            'acodec': 'mp4a.40.2' if fmt.get('audio') else 'none'
                        })
                
                # Agregar formato de audio si está disponible
                if data.get('audioStreams'):
                    for audio in data.get('audioStreams', []):
                        formats.append({
                            'format_id': f"audio_{audio.get('url', '').split('/')[-1]}",
                            'format_note': 'audio',
                            'ext': 'm4a',
                            'filesize': None,
                            'vcodec': 'none',
                            'acodec': 'mp4a.40.2'
                        })
                
                return {
                    'title': data.get('title', 'Sin título'),
                    'duration': data.get('duration', 0),
                    'thumbnail': data.get('videoThumbnails', [{}])[0].get('url', ''),
                    'description': data.get('description', ''),
                    'formats': formats
                }
                
        except Exception as e:
            print(f"Servicio alternativo {service} falló: {e}")
            continue
    
    return None

def get_ydl_opts_aggressive():
    """Configuración más agresiva para yt-dlp"""
    return {
        'quiet': True,
        'no_warnings': False,
        'ignoreerrors': True,
        'extract_flat': False,
        'restrictfilenames': True,
        # Configuraciones agresivas para evitar bloqueos
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web_mobile'],
                'player_skip': ['configs', 'webpage', 'js'],
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        },
        # Forzar métodos de extracción específicos
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,
    }

class DownloadThread(threading.Thread):
    def __init__(self, url, format_id, download_id, use_direct=False):
        threading.Thread.__init__(self)
        self.url = url
        self.format_id = format_id
        self.download_id = download_id
        self.use_direct = use_direct
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

    def download_direct(self, video_id):
        """Descarga directa usando servicios alternativos"""
        try:
            service = get_random_service()
            download_url = f"{service}/latest_version?id={video_id}&itag=18&local=true"
            
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Nombre temporal para el archivo
            temp_filename = f"video_{video_id}.mp4"
            file_path = os.path.join(download_folder, temp_filename)
            
            # Descargar directamente
            response = requests.get(download_url, stream=True, timeout=30)
            total_size = int(response.headers.get('content-length', 0))
            
            with open(file_path, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            download_progress[self.download_id] = {
                                'progress': progress,
                                'status': 'downloading',
                                'speed': 'N/A',
                                'eta': 'N/A'
                            }
            
            self.filename = temp_filename
            return True
            
        except Exception as e:
            self.error = f"Error en descarga directa: {str(e)}"
            return False

    def run(self):
        try:
            if self.use_direct:
                video_id = extract_video_id(self.url)
                if video_id and self.download_direct(video_id):
                    download_progress[self.download_id] = {
                        'progress': 100,
                        'status': 'completed',
                        'filename': self.filename,
                        'title': 'video_descargado'
                    }
                    return
                else:
                    self.error = "No se pudo descargar directamente"

            # Método tradicional con yt-dlp
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            ydl_opts = get_ydl_opts_aggressive()
            ydl_opts.update({
                'outtmpl': os.path.join(download_folder, '%(title).80s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
            })
            
            # Formato simple para mayor compatibilidad
            if self.format_id == 'best':
                ydl_opts['format'] = 'worst[height<=360]'  # Calidad baja para evitar bloqueos
            else:
                ydl_opts['format'] = 'worst[height<=360]'
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
                self.filename = ydl.prepare_filename(info)
                
                download_progress[self.download_id] = {
                    'progress': 100,
                    'status': 'completed',
                    'filename': os.path.basename(self.filename),
                    'title': info.get('title', 'video')
                }
                
        except Exception as e:
            error_msg = str(e)
            if any(keyword in error_msg for keyword in ['bot', 'sign in', 'blocked', 'unavailable']):
                self.error = "YouTube ha bloqueado el acceso desde este servidor. Intenta con: 1) Videos menos populares, 2) Usar el modo directo, 3) Esperar unos minutos"
            else:
                self.error = f"Error: {error_msg}"
            
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
    """Obtener información del video usando métodos alternativos"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    # Primero intentar con servicios alternativos
    alternative_info = get_video_info_alternative(video_id)
    if alternative_info:
        # Procesar formatos para la interfaz
        video_formats = []
        audio_formats = []
        
        for fmt in alternative_info.get('formats', []):
            if fmt.get('vcodec', 'none') != 'none':
                video_formats.append({
                    'id': fmt['format_id'],
                    'display': f"{fmt['format_note']} (MP4)",
                    'resolution': fmt['format_note'],
                    'extension': 'mp4',
                    'has_audio': fmt.get('acodec', 'none') != 'none'
                })
            else:
                audio_formats.append({
                    'id': fmt['format_id'],
                    'display': f"Audio (M4A)",
                    'extension': 'm4a'
                })
        
        return jsonify({
            'success': True,
            'title': alternative_info['title'],
            'duration': alternative_info['duration'],
            'thumbnail': alternative_info['thumbnail'],
            'description': alternative_info['description'][:300] + '...' if alternative_info['description'] else 'Sin descripción',
            'video_id': video_id,
            'formats': {
                'video': video_formats,
                'audio': audio_formats,
                'predefined': [
                    {'id': 'best', 'display': '🎯 Calidad disponible (puede ser baja)'},
                    {'id': 'direct', 'display': '🚀 Descarga directa (experimental)'}
                ]
            },
            'method': 'alternative'
        })
    
    # Si los servicios alternativos fallan, intentar con yt-dlp
    try:
        ydl_opts = get_ydl_opts_aggressive()
        ydl_opts['skip_download'] = True
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            video_info = ydl.extract_info(url, download=False)
        
        # Procesar formatos (código anterior)
        available_formats = video_info.get('formats', [])
        video_formats = []
        audio_formats = []
        
        for fmt in available_formats:
            format_id = fmt.get('format_id', '')
            resolution = fmt.get('format_note', 'Unknown')
            ext = fmt.get('ext', 'unknown')
            vcodec = fmt.get('vcodec', 'none')
            acodec = fmt.get('acodec', 'none')
            
            if not resolution or resolution.lower() == 'unknown':
                continue
            
            if vcodec != 'none' and vcodec is not None:
                has_audio = acodec != 'none' and acodec is not None
                audio_indicator = " 🔊" if has_audio else " 🔇"
                
                video_formats.append({
                    'id': format_id,
                    'display': f"{resolution} ({ext.upper()}){audio_indicator}",
                    'resolution': resolution,
                    'extension': ext,
                    'has_audio': has_audio
                })
            
            elif acodec != 'none' and vcodec == 'none':
                audio_formats.append({
                    'id': format_id,
                    'display': f"Audio only ({ext.upper()})",
                    'extension': ext
                })
        
        predefined_formats = [
            {'id': 'best', 'display': '🎯 Mejor calidad disponible'},
            {'id': 'direct', 'display': '🚀 Descarga directa (alternativa)'}
        ]
        
        return jsonify({
            'success': True,
            'title': video_info.get('title', 'Sin título'),
            'duration': video_info.get('duration', 0),
            'thumbnail': video_info.get('thumbnail', ''),
            'description': video_info.get('description', '')[:300] + '...' if video_info.get('description') else 'Sin descripción',
            'video_id': video_id,
            'formats': {
                'video': video_formats,
                'audio': audio_formats,
                'predefined': predefined_formats
            },
            'method': 'yt-dlp'
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': 'No se pudo obtener información del video. YouTube está bloqueando el acceso. Intenta con videos menos populares o usa la descarga directa.'
        })

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', '')
    use_direct = data.get('use_direct', False)
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    download_id = f"dl_{int(time.time())}_{hash(url)}"
    
    # Determinar si usar método directo
    if format_id == 'direct':
        use_direct = True
        format_id = 'best'  # Placeholder
    
    download_thread = DownloadThread(url, format_id, download_id, use_direct)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada',
        'method': 'direct' if use_direct else 'standard'
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

@app.route('/api/tips')
def get_tips():
    return jsonify({
        'tips': [
            "🎯 Usa videos menos populares (menos vistas = menos bloqueos)",
            "🚀 Prueba la 'Descarga directa' en lugar del método estándar",
            "⏰ Los videos más antiguos suelen tener menos restricciones",
            "📹 Evita videos de canales muy grandes o trending",
            "🔧 Si falla, espera 5-10 minutos y reintenta",
            "💡 Los videos educativos y tutoriales suelen funcionar mejor"
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
