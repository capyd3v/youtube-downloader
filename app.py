import os
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

# Instancias de Invidious funcionales
INVIDIOUS_INSTANCES = [
    'https://inv.riverside.rocks',
    'https://vid.puffyan.us',
    'https://invidious.snopyta.org',
    'https://yewtu.be',
    'https://inv.tux.pizza'
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
            
            print(f"🔍 Intentando con instancia: {instance}")
            
            response = requests.get(api_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
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
                    'success': True
                }
                
                print(f"✅ Información obtenida correctamente de {instance}")
                return video_info
                
        except Exception as e:
            print(f"❌ Instancia {instance} falló: {str(e)}")
            continue
    
    return None

def get_download_url(video_id, format_type='video'):
    """Obtener URL de descarga directa desde Invidious"""
    for attempt in range(3):
        try:
            instance = get_random_instance()
            
            if format_type == 'video':
                # URL para descarga de video (itag 18 = 360p MP4, itag 22 = 720p MP4)
                download_url = f"{instance}/latest_version?id={video_id}&itag=18"
            else:
                # URL para descarga de audio (itag 140 = audio m4a)
                download_url = f"{instance}/latest_version?id={video_id}&itag=140"
            
            print(f"🔗 Probando URL de descarga: {download_url}")
            
            # Verificar que la URL es accesible
            response = requests.head(download_url, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                print(f"✅ URL de descarga válida: {download_url}")
                return download_url
                
        except Exception as e:
            print(f"❌ URL de descarga falló: {str(e)}")
            continue
    
    return None

class DownloadThread(threading.Thread):
    def __init__(self, video_id, format_type, download_id):
        threading.Thread.__init__(self)
        self.video_id = video_id
        self.format_type = format_type  # 'video' o 'audio'
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

    def download_direct(self):
        """Descarga directa usando Invidious"""
        try:
            # Obtener información del video primero para el título
            info = get_video_info_invidious(self.video_id)
            if not info:
                info = {
                    'title': f'video_{self.video_id}',
                    'description': 'Video descargado desde YouTube'
                }
            
            # Obtener URL de descarga
            download_url = get_download_url(self.video_id, self.format_type)
            if not download_url:
                self.error = "No se pudo obtener URL de descarga. Intenta más tarde."
                return False
            
            # Crear directorio de descargas
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Nombre del archivo seguro
            safe_title = re.sub(r'[^\w\s-]', '', info.get('title', f'video_{self.video_id}'))
            safe_title = re.sub(r'[-\s]+', '_', safe_title)
            file_ext = 'mp4' if self.format_type == 'video' else 'm4a'
            filename = f"{safe_title[:50]}_{self.video_id}.{file_ext}"
            file_path = os.path.join(download_folder, filename)
            
            print(f"📥 Iniciando descarga desde: {download_url}")
            
            # Descargar el archivo
            response = requests.get(download_url, stream=True, timeout=60)
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
                            # Progreso estimado basado en tamaño descargado
                            progress_percent = min(95, (downloaded / (5 * 1024 * 1024)) * 100)  # Asume max 5MB
                            download_progress[self.download_id] = {
                                'progress': progress_percent,
                                'status': 'downloading',
                                'downloaded': downloaded,
                                'total': 0
                            }
            
            # Verificar que el archivo se descargó correctamente
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                self.filename = filename
                print(f"✅ Descarga completada: {filename} ({os.path.getsize(file_path)} bytes)")
                return True
            else:
                self.error = "El archivo se descargó pero está vacío o corrupto"
                return False
            
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
            
            success = self.download_direct()
            
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
    
    # Obtener información del video
    video_info = get_video_info_invidious(video_id)
    if not video_info:
        # Información de respaldo
        video_info = {
            'title': f"Video {video_id}",
            'description': 'Información obtenida mediante servicio alternativo',
            'duration': 0,
            'viewCount': 0,
            'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
            'success': True
        }
    
    # Formatos predefinidos (siempre disponibles)
    predefined_formats = [
        {'id': 'video', 'display': '🎥 Video MP4 (360p)'},
        {'id': 'audio', 'display': '🎵 Audio M4A'}
    ]
    
    video_formats = [
        {'id': 'video', 'display': '🎥 Video MP4 (360p)', 'resolution': '360p', 'extension': 'mp4', 'has_audio': True}
    ]
    
    audio_formats = [
        {'id': 'audio', 'display': '🎵 Audio M4A', 'extension': 'm4a'}
    ]
    
    return jsonify({
        'success': True,
        'title': video_info.get('title', 'Sin título'),
        'duration': video_info.get('duration', 0),
        'thumbnail': video_info.get('thumbnail', ''),
        'description': str(video_info.get('description', ''))[:200] + '...',
        'video_id': video_id,
        'view_count': video_info.get('viewCount', 0),
        'formats': {
            'video': video_formats,
            'audio': audio_formats,
            'predefined': predefined_formats
        },
        'method': 'invidious',
        'message': '✅ Información obtenida - Selecciona formato para descargar'
    })

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'video')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    # Determinar tipo de formato
    format_type = 'video' if format_id == 'video' else 'audio'
    
    download_id = f"dl_{int(time.time())}_{video_id}"
    
    print(f"🚀 Iniciando descarga: {video_id} como {format_type}")
    
    download_thread = DownloadThread(video_id, format_type, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': f'Descarga de {format_type} iniciada',
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
    
    # Verificar que el archivo no esté vacío
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return jsonify({'success': False, 'error': 'El archivo está vacío'})
    
    print(f"📤 Sirviendo archivo: {filename} ({file_size} bytes)")
    
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
        'message': '✅ Servicio funcionando con descarga directa',
        'instances_available': len(INVIDIOUS_INSTANCES),
        'formats_available': ['video (360p MP4)', 'audio (M4A)']
    })

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
