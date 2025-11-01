import os
import requests
from flask import Flask, render_template, request, jsonify, send_file
import tempfile
import threading
import time
import re
from pytube import YouTube
from pytube.exceptions import VideoUnavailable, AgeRestrictedError
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

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

class DownloadThread(threading.Thread):
    def __init__(self, url, format_type, download_id):
        threading.Thread.__init__(self)
        self.url = url
        self.format_type = format_type  # 'video' o 'audio'
        self.download_id = download_id
        self.filename = None
        self.error = None

    def progress_callback(self, stream, chunk, bytes_remaining):
        """Callback para el progreso de descarga"""
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        progress = (bytes_downloaded / total_size) * 100
        
        download_progress[self.download_id] = {
            'progress': progress,
            'status': 'downloading',
            'downloaded': bytes_downloaded,
            'total': total_size,
            'speed': 'Calculando...',
            'eta': 'Calculando...'
        }

    def run(self):
        try:
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'iniciando',
                'error': None
            }
            
            # Crear directorio temporal para descargas
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Configurar YouTube object
            yt = YouTube(self.url, on_progress_callback=self.progress_callback)
            
            # Obtener información básica
            video_title = yt.title
            safe_title = re.sub(r'[^\w\s-]', '', video_title)
            safe_title = re.sub(r'[-\s]+', '_', safe_title)
            
            if self.format_type == 'video':
                # Filtrar streams de video progresivo (video + audio)
                streams = yt.streams.filter(progressive=True, file_extension='mp4')
                
                # Ordenar por resolución descendente
                streams = streams.order_by('resolution').desc()
                
                if not streams:
                    self.error = "No se encontraron streams de video disponibles"
                    return
                
                # Seleccionar el stream de mayor resolución disponible
                stream = streams.first()
                file_ext = 'mp4'
                
            else:  # audio
                # Filtrar streams de audio
                streams = yt.streams.filter(only_audio=True, file_extension='mp4')
                
                if not streams:
                    self.error = "No se encontraron streams de audio disponibles"
                    return
                
                # Seleccionar el stream de audio de mayor calidad
                stream = streams.order_by('abr').desc().first()
                file_ext = 'mp4'  # pytube descarga audio como mp4
            
            # Generar nombre de archivo
            filename = f"{safe_title[:50]}.{file_ext}"
            file_path = os.path.join(download_folder, filename)
            
            download_progress[self.download_id] = {
                'progress': 5,
                'status': 'preparando_descarga',
                'error': None
            }
            
            # Descargar el archivo
            print(f"📥 Descargando: {video_title}")
            stream.download(output_path=download_folder, filename=filename)
            
            # Verificar que el archivo existe
            if os.path.exists(file_path):
                self.filename = filename
                download_progress[self.download_id] = {
                    'progress': 100,
                    'status': 'completed',
                    'filename': filename,
                    'title': video_title
                }
                print(f"✅ Descarga completada: {filename}")
            else:
                self.error = "El archivo no se descargó correctamente"
                raise Exception(self.error)
                
        except VideoUnavailable:
            self.error = "El video no está disponible o fue eliminado"
        except AgeRestrictedError:
            self.error = "El video tiene restricción de edad y no se puede descargar"
        except Exception as e:
            self.error = f"Error en la descarga: {str(e)}"
            print(f"❌ Error: {str(e)}")
        
        if self.error:
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
    """Obtener información del video usando pytube"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    try:
        # Obtener información básica del video
        yt = YouTube(url)
        
        # Obtener miniatura de mayor calidad
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        
        # Verificar si existe la miniatura maxres
        response = requests.head(thumbnail_url)
        if response.status_code != 200:
            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        
        # Obtener streams disponibles
        video_streams = yt.streams.filter(progressive=True, file_extension='mp4')
        audio_streams = yt.streams.filter(only_audio=True, file_extension='mp4')
        
        # Procesar formatos de video
        video_formats = []
        for stream in video_streams.order_by('resolution').desc():
            if stream.resolution:
                video_formats.append({
                    'id': f"video_{stream.resolution}",
                    'display': f"🎥 Video {stream.resolution} ({stream.mime_type.split('/')[1]})",
                    'resolution': stream.resolution,
                    'extension': 'mp4',
                    'has_audio': True,
                    'filesize': stream.filesize_mb
                })
        
        # Procesar formatos de audio
        audio_formats = []
        for stream in audio_streams.order_by('abr').desc():
            audio_formats.append({
                'id': f"audio_{stream.abr}",
                'display': f"🎵 Audio {stream.abr}",
                'extension': 'm4a',
                'filesize': stream.filesize_mb
            })
        
        # Formatos predefinidos
        predefined_formats = []
        if video_formats:
            predefined_formats.append({
                'id': 'video_best', 
                'display': '🎯 Mejor calidad de video disponible'
            })
        if audio_formats:
            predefined_formats.append({
                'id': 'audio_best',
                'display': '🔊 Mejor calidad de audio disponible'
            })
        
        return jsonify({
            'success': True,
            'title': yt.title,
            'duration': yt.length,
            'thumbnail': thumbnail_url,
            'description': yt.description[:300] + '...' if yt.description else 'Sin descripción disponible',
            'video_id': video_id,
            'view_count': yt.views,
            'formats': {
                'video': video_formats,
                'audio': audio_formats,
                'predefined': predefined_formats
            },
            'method': 'pytube',
            'message': '✅ Información obtenida correctamente'
        })
        
    except VideoUnavailable:
        return jsonify({'success': False, 'error': 'El video no está disponible o fue eliminado'})
    except AgeRestrictedError:
        return jsonify({'success': False, 'error': 'El video tiene restricción de edad'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al obtener información: {str(e)}'})

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'video_best')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    # Determinar tipo de formato
    if format_id.startswith('video_'):
        format_type = 'video'
    elif format_id.startswith('audio_'):
        format_type = 'audio'
    elif format_id == 'video_best':
        format_type = 'video'
    elif format_id == 'audio_best':
        format_type = 'audio'
    else:
        format_type = 'video'  # Por defecto
    
    download_id = f"dl_{int(time.time())}_{hash(url)}"
    
    print(f"🚀 Iniciando descarga: {format_type}")
    
    download_thread = DownloadThread(url, format_type, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada',
        'format_type': format_type
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
    
    # Verificar tamaño del archivo
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
        'message': '✅ Servicio funcionando con pytube',
        'version': 'Usando pytube para descargas de YouTube'
    })

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
