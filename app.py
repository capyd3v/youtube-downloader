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
import json
from urllib.request import urlopen
import xml.etree.ElementTree as ET

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

# Múltiples servicios alternativos
INVIDIOUS_INSTANCES = [
    'https://inv.riverside.rocks',
    'https://invidious.snopyta.org', 
    'https://yewtu.be',
    'https://inv.tux.pizza',
    'https://invidious.osi.kr',
    'https://vid.puffyan.us'
]

# APIs alternativas
ALTERNATIVE_APIS = [
    'https://noembed.com/embed?url=',
    'https://www.youtube.com/oembed?url=',
    'https://api.spencerwoo.com/ytb/video/'
]

def get_random_instance():
    return random.choice(INVIDIOUS_INSTANCES)

def extract_video_id(url):
    """Extraer ID del video de forma robusta"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)',
        r'youtube\.com\/embed\/([^&?\n]+)',
        r'youtube\.com\/v\/([^&?\n]+)',
        r'youtube\.com\/watch\?.+&v=([^&?\n]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_basic_info_from_oembed(url):
    """Obtener información básica usando oEmbed"""
    try:
        for api_base in ALTERNATIVE_APIS:
            try:
                api_url = f"{api_base}{urllib.parse.quote(url)}"
                if 'noembed' in api_base:
                    api_url += '&format=json'
                
                response = requests.get(api_url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        'title': data.get('title', 'Sin título'),
                        'thumbnail_url': data.get('thumbnail_url', ''),
                        'author_name': data.get('author_name', ''),
                        'success': True
                    }
            except:
                continue
    except:
        pass
    return None

def get_invidious_info(video_id):
    """Obtener información completa de Invidious"""
    for attempt in range(3):
        try:
            instance = get_random_instance()
            api_url = f"{instance}/api/v1/videos/{video_id}"
            
            response = requests.get(api_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                # Procesar formatos disponibles
                formats = []
                
                # Formatos de video
                for stream in data.get('formatStreams', []):
                    if stream.get('type', '').startswith('video'):
                        formats.append({
                            'format_id': f"video_{stream.get('quality', 'unknown')}",
                            'url': stream.get('url', ''),
                            'quality': stream.get('quality', 'unknown'),
                            'type': 'video',
                            'mimeType': stream.get('type', 'video/mp4')
                        })
                
                # Formatos de audio
                for audio in data.get('audioStreams', []):
                    formats.append({
                        'format_id': f"audio_{audio.get('quality', 'unknown')}",
                        'url': audio.get('url', ''),
                        'quality': audio.get('quality', 'unknown'),
                        'type': 'audio',
                        'mimeType': audio.get('type', 'audio/mp4')
                    })
                
                # Información básica del video
                video_info = {
                    'title': data.get('title', 'Sin título'),
                    'description': data.get('description', ''),
                    'duration': data.get('lengthSeconds', 0),
                    'viewCount': data.get('viewCount', 0),
                    'thumbnails': data.get('videoThumbnails', []),
                    'formats': formats,
                    'success': True
                }
                
                return video_info
                
        except Exception as e:
            print(f"Instancia {instance} falló: {e}")
            continue
    
    return None

def get_youtube_dl_info_with_proxy(url):
    """Intentar con yt-dlp usando configuraciones extremas"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'extract_flat': False,
            'restrictfilenames': True,
            'socket_timeout': 30,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_embedded', 'ios', 'web_mobile'],
                    'player_skip': ['configs', 'webpage', 'js'],
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.youtube.com/',
                'Origin': 'https://www.youtube.com',
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    except:
        return None

class DownloadThread(threading.Thread):
    def __init__(self, video_id, format_type, download_id, service_instance=None):
        threading.Thread.__init__(self)
        self.video_id = video_id
        self.format_type = format_type
        self.download_id = download_id
        self.service_instance = service_instance or get_random_instance()
        self.filename = None
        self.error = None

    def progress_hook(self, current, total):
        if total > 0:
            progress = (current / total) * 100
            download_progress[self.download_id] = {
                'progress': progress,
                'status': 'downloading',
                'downloaded': current,
                'total': total
            }

    def download_from_invidious(self):
        """Descargar usando Invidious"""
        try:
            # Obtener información del video primero
            info = get_invidious_info(self.video_id)
            if not info:
                return False
            
            # Determinar URL de descarga
            download_url = None
            for fmt in info.get('formats', []):
                if self.format_type == 'video' and fmt['type'] == 'video':
                    if fmt['quality'] in ['360p', '480p']:  # Priorizar calidades bajas
                        download_url = fmt['url']
                        break
                elif self.format_type == 'audio' and fmt['type'] == 'audio':
                    download_url = fmt['url']
                    break
            
            if not download_url:
                # Si no encontramos el formato específico, usar el primero disponible
                for fmt in info.get('formats', []):
                    if fmt['type'] == self.format_type:
                        download_url = fmt['url']
                        break
            
            if not download_url:
                return False
            
            # Crear directorio de descargas
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Nombre del archivo
            safe_title = re.sub(r'[^\w\s-]', '', info['title'])
            safe_title = re.sub(r'[-\s]+', '_', safe_title)
            file_ext = 'mp4' if self.format_type == 'video' else 'm4a'
            filename = f"{safe_title[:50]}.{file_ext}"
            file_path = os.path.join(download_folder, filename)
            
            # Descargar el archivo
            response = requests.get(download_url, stream=True, timeout=30)
            total_size = int(response.headers.get('content-length', 0))
            
            with open(file_path, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress_hook(downloaded, total_size)
            
            self.filename = filename
            return True
            
        except Exception as e:
            self.error = f"Error en descarga Invidious: {str(e)}"
            return False

    def run(self):
        try:
            # Siempre usar Invidious para descargar
            success = self.download_from_invidious()
            
            if success:
                download_progress[self.download_id] = {
                    'progress': 100,
                    'status': 'completed',
                    'filename': self.filename,
                    'title': 'video_descargado'
                }
            else:
                self.error = self.error or "No se pudo descargar el video"
                raise Exception(self.error)
                
        except Exception as e:
            error_msg = str(e)
            self.error = error_msg
            
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
    
    # Método 1: Usar Invidious (principal)
    invidious_info = get_invidious_info(video_id)
    if invidious_info:
        # Procesar formatos para la interfaz
        video_formats = []
        audio_formats = []
        
        # Agrupar por calidad
        video_qualities = set()
        for fmt in invidious_info.get('formats', []):
            if fmt['type'] == 'video':
                video_qualities.add(fmt['quality'])
            elif fmt['type'] == 'audio':
                audio_formats.append({
                    'id': f"audio_{fmt['quality']}",
                    'display': f"🎵 Audio ({fmt['quality']})",
                    'type': 'audio'
                })
        
        # Crear opciones de video
        for quality in sorted(video_qualities, key=lambda x: int(x.replace('p', '')) if 'p' in x else 0):
            video_formats.append({
                'id': f"video_{quality}",
                'display': f"🎥 Video {quality}",
                'type': 'video',
                'quality': quality
            })
        
        # Obtener miniatura
        thumbnail = ''
        if invidious_info.get('thumbnails'):
            # Buscar miniatura de calidad media
            for thumb in invidious_info['thumbnails']:
                if thumb.get('quality', '') == 'medium':
                    thumbnail = thumb.get('url', '')
                    break
            if not thumbnail and invidious_info['thumbnails']:
                thumbnail = invidious_info['thumbnails'][0].get('url', '')
        
        return jsonify({
            'success': True,
            'title': invidious_info['title'],
            'duration': invidious_info['duration'],
            'thumbnail': thumbnail,
            'description': invidious_info['description'][:200] + '...' if invidious_info['description'] else 'Sin descripción',
            'video_id': video_id,
            'view_count': invidious_info.get('viewCount', 0),
            'formats': {
                'video': video_formats,
                'audio': audio_formats
            },
            'method': 'invidious',
            'message': '✅ Usando servicio alternativo (Invidious)'
        })
    
    # Método 2: Información básica via oEmbed
    basic_info = get_basic_info_from_oembed(url)
    if basic_info:
        return jsonify({
            'success': True,
            'title': basic_info['title'],
            'duration': 0,
            'thumbnail': basic_info['thumbnail_url'],
            'description': f"Video de {basic_info.get('author_name', 'YouTube')}",
            'video_id': video_id,
            'formats': {
                'video': [{'id': 'video_default', 'display': '🎥 Video (calidad disponible)'}],
                'audio': [{'id': 'audio_default', 'display': '🎵 Audio'}]
            },
            'method': 'oembed',
            'message': '⚠️ Información limitada disponible'
        })
    
    # Método 3: Información mínima con solo el ID
    return jsonify({
        'success': True,
        'title': f"Video {video_id}",
        'duration': 0,
        'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
        'description': 'Información no disponible debido a restricciones de YouTube',
        'video_id': video_id,
        'formats': {
            'video': [{'id': 'video_auto', 'display': '🎥 Intentar descargar video'}],
            'audio': [{'id': 'audio_auto', 'display': '🎵 Intentar descargar audio'}]
        },
        'method': 'fallback',
        'message': '⚠️ Solo descarga disponible (sin información detallada)'
    })

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'video_360p')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    # Determinar tipo de formato
    format_type = 'video'
    if format_id.startswith('audio'):
        format_type = 'audio'
    
    download_id = f"dl_{int(time.time())}_{video_id}"
    
    download_thread = DownloadThread(video_id, format_type, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada usando servicio alternativo',
        'video_id': video_id
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
    """Endpoint para verificar el estado del servicio"""
    return jsonify({
        'status': 'active',
        'message': '✅ Servicio funcionando con métodos alternativos',
        'supported_methods': ['invidious', 'oembed', 'fallback'],
        'recommendation': 'Usa videos menos populares para mejor resultado'
    })

@app.route('/api/tips')
def get_tips():
    return jsonify({
        'tips': [
            "🎯 Funciona MEJOR con videos educativos/tutoriales",
            "📹 Videos con menos de 50,000 vistas funcionan mejor", 
            "⏰ Videos de 2+ años de antigüedad tienen menos bloqueos",
            "🚀 Usa calidad 360p o 480p para mayor éxito",
            "💡 Canales pequeños = menos restricciones",
            "🔧 Si falla, intenta con otro video"
        ]
    })
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
