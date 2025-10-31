import os
import requests
from flask import Flask, render_template, request, jsonify, send_file
import tempfile
import threading
import time
import re
import random
import json
from urllib.parse import quote

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

# Instancias de Invidious (servicios alternativos)
INVIDIOUS_INSTANCES = [
    'https://inv.riverside.rocks',
    'https://vid.puffyan.us',
    'https://invidious.snopyta.org',
    'https://yewtu.be',
    'https://inv.tux.pizza',
    'https://invidious.osi.kr'
]

def get_random_instance():
    return random.choice(INVIDIOUS_INSTANCES)

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

def get_video_info_invidious(video_id):
    """Obtener información del video usando Invidious"""
    for attempt in range(3):
        try:
            instance = get_random_instance()
            api_url = f"{instance}/api/v1/videos/{video_id}"
            
            print(f"Intentando con instancia: {instance}")
            
            response = requests.get(api_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                # Procesar formatos disponibles
                formats = []
                
                # Formatos de video
                for stream in data.get('formatStreams', []):
                    if stream.get('type', '').startswith('video'):
                        quality = stream.get('quality', 'unknown')
                        # Normalizar calidad (remover 'p' si existe)
                        if 'p' in quality:
                            quality = quality.replace('p', '')
                        
                        formats.append({
                            'format_id': f"video_{quality}",
                            'url': stream.get('url', ''),
                            'quality': quality,
                            'type': 'video',
                            'mimeType': stream.get('type', 'video/mp4'),
                            'has_audio': True
                        })
                
                # Formatos de audio
                for audio in data.get('audioStreams', []):
                    quality = audio.get('quality', 'medium')
                    formats.append({
                        'format_id': f"audio_{quality}",
                        'url': audio.get('url', ''),
                        'quality': quality,
                        'type': 'audio',
                        'mimeType': audio.get('type', 'audio/mp4')
                    })
                
                # Obtener la mejor miniatura
                thumbnails = data.get('videoThumbnails', [])
                thumbnail_url = ''
                if thumbnails:
                    for thumb in thumbnails:
                        if thumb.get('quality') in ['medium', 'high', 'standard']:
                            thumbnail_url = thumb.get('url', '')
                            break
                    if not thumbnail_url and thumbnails:
                        thumbnail_url = thumbnails[0].get('url', '')
                
                video_info = {
                    'title': data.get('title', 'Sin título'),
                    'description': data.get('description', ''),
                    'duration': data.get('lengthSeconds', 0),
                    'viewCount': data.get('viewCount', 0),
                    'thumbnail': thumbnail_url,
                    'formats': formats,
                    'success': True
                }
                
                print(f"✅ Información obtenida correctamente de {instance}")
                print(f"📊 Formatos disponibles: {[f['format_id'] for f in formats]}")
                return video_info
                
        except Exception as e:
            print(f"❌ Instancia {instance} falló: {str(e)}")
            continue
    
    return None

def get_basic_fallback_info(video_id):
    """Información básica de respaldo con formatos realistas"""
    return {
        'title': f"Video {video_id}",
        'description': 'Información limitada disponible - usando servicio alternativo',
        'duration': 0,
        'viewCount': 0,
        'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
        'formats': [
            {
                'format_id': 'video_360',
                'quality': '360',
                'type': 'video',
                'has_audio': True,
                'url': f'https://inv.riverside.rocks/latest_version?id={video_id}&itag=18'
            },
            {
                'format_id': 'video_720', 
                'quality': '720',
                'type': 'video',
                'has_audio': True,
                'url': f'https://inv.riverside.rocks/latest_version?id={video_id}&itag=22'
            },
            {
                'format_id': 'audio_medium',
                'quality': 'medium',
                'type': 'audio',
                'url': f'https://inv.riverside.rocks/latest_version?id={video_id}&itag=140'
            }
        ],
        'success': True
    }

class DownloadThread(threading.Thread):
    def __init__(self, video_id, format_id, download_id):
        threading.Thread.__init__(self)
        self.video_id = video_id
        self.format_id = format_id
        self.download_id = download_id
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
            # Obtener información del video
            info = get_video_info_invidious(self.video_id)
            if not info:
                info = get_basic_fallback_info(self.video_id)
            
            print(f"🔍 Buscando formato: {self.format_id}")
            print(f"📋 Formatos disponibles: {[f['format_id'] for f in info.get('formats', [])]}")
            
            # Determinar URL de descarga
            download_url = None
            available_formats = info.get('formats', [])
            
            # Buscar el formato exacto
            for fmt in available_formats:
                if fmt.get('format_id') == self.format_id:
                    download_url = fmt.get('url')
                    break
            
            # Si no encontramos el formato exacto, buscar cualquier formato del mismo tipo
            if not download_url:
                format_type = self.format_id.split('_')[0]  # 'video' o 'audio'
                print(f"🔄 Formato exacto no encontrado, buscando cualquier formato de tipo: {format_type}")
                
                for fmt in available_formats:
                    if fmt.get('type') == format_type:
                        download_url = fmt.get('url')
                        self.format_id = fmt.get('format_id')  # Actualizar al formato encontrado
                        print(f"✅ Usando formato alternativo: {self.format_id}")
                        break
            
            # Si aún no encontramos, usar el primer formato disponible
            if not download_url and available_formats:
                download_url = available_formats[0].get('url')
                self.format_id = available_formats[0].get('format_id')
                print(f"⚠️ Usando primer formato disponible: {self.format_id}")
            
            if not download_url:
                self.error = f"No se encontró ningún formato disponible. Formatos: {[f['format_id'] for f in available_formats]}"
                return False
            
            # Crear directorio de descargas
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Nombre del archivo seguro
            safe_title = re.sub(r'[^\w\s-]', '', info.get('title', f'video_{self.video_id}'))
            safe_title = re.sub(r'[-\s]+', '_', safe_title)
            file_ext = 'mp4' if 'video' in self.format_id else 'm4a'
            filename = f"{safe_title[:50]}_{self.format_id}.{file_ext}"
            file_path = os.path.join(download_folder, filename)
            
            # Si la URL no es completa, construirla
            if not download_url.startswith('http'):
                instance = get_random_instance()
                download_url = f"{instance}{download_url}" if download_url.startswith('/') else f"{instance}/latest_version?id={self.video_id}"
            
            print(f"📥 Iniciando descarga desde: {download_url[:100]}...")
            
            # Descargar el archivo
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            self.progress_hook(downloaded, total_size)
                        else:
                            # Progreso indefinido
                            progress_percent = min(90, (downloaded / (1024 * 1024)) * 10)  # Estimación
                            download_progress[self.download_id] = {
                                'progress': progress_percent,
                                'status': 'downloading',
                                'downloaded': downloaded,
                                'total': 0
                            }
            
            self.filename = filename
            print(f"✅ Descarga completada: {filename}")
            return True
            
        except Exception as e:
            self.error = f"Error en descarga: {str(e)}"
            print(f"❌ Error en descarga: {str(e)}")
            return False

    def run(self):
        try:
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'starting',
                'error': None
            }
            
            success = self.download_from_invidious()
            
            if success:
                download_progress[self.download_id] = {
                    'progress': 100,
                    'status': 'completed',
                    'filename': self.filename,
                    'title': 'video_descargado'
                }
            else:
                raise Exception(self.error or "No se pudo descargar el video")
                
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
    """Obtener información del video usando Invidious"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    print(f"🎬 Obteniendo información para video ID: {video_id}")
    
    # Método principal: Invidious
    invidious_info = get_video_info_invidious(video_id)
    if invidious_info:
        # Procesar formatos para el frontend
        video_formats = []
        audio_formats = []
        predefined_formats = []
        
        # Agrupar calidades de video
        video_qualities = set()
        audio_qualities = set()
        
        for fmt in invidious_info.get('formats', []):
            if fmt.get('type') == 'video':
                quality = fmt.get('quality', 'unknown')
                video_qualities.add(quality)
            elif fmt.get('type') == 'audio':
                quality = fmt.get('quality', 'unknown')
                audio_qualities.add(quality)
        
        # Crear opciones de video ordenadas
        for quality in sorted(video_qualities, key=lambda x: int(x) if x.isdigit() else 0):
            video_formats.append({
                'id': f"video_{quality}",
                'display': f"🎥 Video {quality}p",
                'resolution': f"{quality}p",
                'extension': 'mp4',
                'has_audio': True
            })
        
        # Crear opciones de audio
        for quality in sorted(audio_qualities):
            audio_formats.append({
                'id': f"audio_{quality}",
                'display': f"🎵 Audio ({quality})",
                'extension': 'm4a'
            })
        
        # Si no hay formatos específicos, usar opciones genéricas
        if not video_formats:
            video_formats = [
                {'id': 'video_360', 'display': '🎥 Video 360p', 'resolution': '360p', 'extension': 'mp4', 'has_audio': True},
                {'id': 'video_720', 'display': '🎥 Video 720p', 'resolution': '720p', 'extension': 'mp4', 'has_audio': True}
            ]
        
        if not audio_formats:
            audio_formats = [
                {'id': 'audio_medium', 'display': '🎵 Audio', 'extension': 'm4a'}
            ]
        
        # Formatos predefinidos basados en lo disponible
        predefined_formats = []
        if video_formats:
            predefined_formats.append({'id': video_formats[0]['id'], 'display': '🎯 Mejor calidad disponible'})
        if len(video_formats) > 1:
            predefined_formats.append({'id': video_formats[1]['id'], 'display': '📹 Calidad media'})
        if audio_formats:
            predefined_formats.append({'id': audio_formats[0]['id'], 'display': '🔊 Solo audio'})
        
        return jsonify({
            'success': True,
            'title': invidious_info.get('title', 'Sin título'),
            'duration': invidious_info.get('duration', 0),
            'thumbnail': invidious_info.get('thumbnail', ''),
            'description': str(invidious_info.get('description', ''))[:200] + '...',
            'video_id': video_id,
            'view_count': invidious_info.get('viewCount', 0),
            'formats': {
                'video': video_formats,
                'audio': audio_formats,
                'predefined': predefined_formats
            },
            'method': 'invidious',
            'message': '✅ Información obtenida mediante servicio alternativo'
        })
    
    # Método de respaldo
    fallback_info = get_basic_fallback_info(video_id)
    
    return jsonify({
        'success': True,
        'title': fallback_info.get('title', 'Sin título'),
        'duration': fallback_info.get('duration', 0),
        'thumbnail': fallback_info.get('thumbnail', ''),
        'description': fallback_info.get('description', ''),
        'video_id': video_id,
        'formats': {
            'video': [
                {'id': 'video_360', 'display': '🎥 Video 360p', 'resolution': '360p', 'extension': 'mp4'},
                {'id': 'video_720', 'display': '🎥 Video 720p', 'resolution': '720p', 'extension': 'mp4'}
            ],
            'audio': [
                {'id': 'audio_medium', 'display': '🎵 Audio', 'extension': 'm4a'}
            ],
            'predefined': [
                {'id': 'video_360', 'display': '🎯 Video 360p (Recomendado)'},
                {'id': 'video_720', 'display': '📹 Video 720p'},
                {'id': 'audio_medium', 'display': '🔊 Solo Audio'}
            ]
        },
        'method': 'fallback',
        'message': '⚠️ Usando información básica - servicio alternativo'
    })

# ... (mantener las demás rutas igual: start_download, progress, download, cancel_download, status)

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'video_360')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    download_id = f"dl_{int(time.time())}_{video_id}"
    
    print(f"🚀 Iniciando descarga: {video_id} con formato {format_id}")
    
    download_thread = DownloadThread(video_id, format_id, download_id)
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
        'status': 'unknown',
        'error': None
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
        'message': '✅ Servicio funcionando con Invidious',
        'instances_available': len(INVIDIOUS_INSTANCES),
        'recommendation': 'El sistema buscará automáticamente formatos disponibles'
    })

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
