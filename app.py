import os
import requests
from flask import Flask, render_template, request, jsonify, send_file
import tempfile
import threading
import time
import re
import random
from pytube import YouTube
from pytube.exceptions import VideoUnavailable, AgeRestrictedError
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

# Lista de User-Agents para rotación
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

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
    """Obtener información del video con reintentos y rotación de User-Agents"""
    for attempt in range(max_retries):
        try:
            # Delay progresivo entre reintentos
            if attempt > 0:
                delay = 2 ** attempt  # 2, 4, 8 segundos
                print(f"⏳ Reintento {attempt + 1} en {delay} segundos...")
                time.sleep(delay)
            
            # Configurar headers con User-Agent rotativo
            headers = {
                'User-Agent': get_random_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            print(f"🔍 Intento {attempt + 1} con User-Agent: {headers['User-Agent'][:50]}...")
            
            # Crear objeto YouTube con headers personalizados
            yt = YouTube(url, headers=headers)
            
            return yt
            
        except Exception as e:
            print(f"❌ Intento {attempt + 1} falló: {str(e)}")
            if attempt == max_retries - 1:
                raise e
            continue
    
    return None

def get_thumbnail_url(video_id):
    """Obtener URL de miniatura con verificación"""
    thumbnail_qualities = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/default.jpg"
    ]
    
    for thumbnail_url in thumbnail_qualities:
        try:
            response = requests.head(thumbnail_url, timeout=5)
            if response.status_code == 200:
                return thumbnail_url
        except:
            continue
    
    return thumbnail_qualities[1]  # Fallback a hqdefault

class DownloadThread(threading.Thread):
    def __init__(self, url, format_type, download_id):
        threading.Thread.__init__(self)
        self.url = url
        self.format_type = format_type
        self.download_id = download_id
        self.filename = None
        self.error = None

    def progress_callback(self, stream, chunk, bytes_remaining):
        """Callback para el progreso de descarga"""
        total_size = stream.filesize
        if total_size:
            bytes_downloaded = total_size - bytes_remaining
            progress = (bytes_downloaded / total_size) * 100
            
            download_progress[self.download_id] = {
                'progress': progress,
                'status': 'downloading',
                'downloaded': bytes_downloaded,
                'total': total_size
            }

    def run(self):
        try:
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'iniciando',
                'error': None
            }
            
            # Pequeño delay aleatorio antes de empezar
            time.sleep(random.uniform(1, 3))
            
            # Crear directorio temporal para descargas
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Obtener información del video con retry
            headers = {'User-Agent': get_random_user_agent()}
            yt = YouTube(self.url, headers=headers, on_progress_callback=self.progress_callback)
            
            # Obtener información básica
            video_title = yt.title
            safe_title = re.sub(r'[^\w\s-]', '', video_title)
            safe_title = re.sub(r'[-\s]+', '_', safe_title)
            
            download_progress[self.download_id] = {
                'progress': 10,
                'status': 'buscando_streams',
                'error': None
            }
            
            if self.format_type == 'video':
                # Filtrar streams de video progresivo (video + audio)
                streams = yt.streams.filter(progressive=True, file_extension='mp4')
                
                if not streams:
                    # Si no hay streams progresivos, intentar con adaptative
                    streams = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True)
                    if streams:
                        # Para adaptive streams, necesitamos descargar audio por separado
                        # Por simplicidad, usamos el primer stream disponible
                        stream = streams.order_by('resolution').desc().first()
                    else:
                        self.error = "No se encontraron streams de video disponibles"
                        return
                else:
                    # Ordenar por resolución descendente y tomar el primero
                    stream = streams.order_by('resolution').desc().first()
                
                file_ext = 'mp4'
                
            else:  # audio
                # Filtrar streams de audio
                streams = yt.streams.filter(only_audio=True)
                
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
                'progress': 20,
                'status': 'preparando_descarga',
                'error': None
            }
            
            # Pequeño delay antes de descargar
            time.sleep(random.uniform(1, 2))
            
            # Descargar el archivo
            print(f"📥 Descargando: {video_title}")
            stream.download(output_path=download_folder, filename=filename)
            
            # Verificar que el archivo existe
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
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
            error_msg = str(e)
            if "429" in error_msg:
                self.error = "YouTube está bloqueando las solicitudes. Por favor, espera unos minutos e intenta nuevamente."
            else:
                self.error = f"Error en la descarga: {error_msg}"
            print(f"❌ Error: {error_msg}")
        
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
    """Obtener información del video con protección contra rate limiting"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    try:
        # Obtener información con reintentos
        yt = get_video_info_with_retry(url)
        if not yt:
            return jsonify({'success': False, 'error': 'No se pudo obtener información después de varios intentos'})
        
        # Obtener miniatura
        thumbnail_url = get_thumbnail_url(video_id)
        
        # Obtener streams disponibles (sin descargar)
        video_streams = yt.streams.filter(progressive=True, file_extension='mp4')
        audio_streams = yt.streams.filter(only_audio=True)
        
        # Procesar formatos de video
        video_formats = []
        for stream in video_streams.order_by('resolution').desc()[:5]:  # Limitar a 5 opciones
            if stream.resolution:
                size_text = f" - {stream.filesize_mb:.1f} MB" if stream.filesize_mb else ""
                video_formats.append({
                    'id': f"video_{stream.resolution}",
                    'display': f"🎥 Video {stream.resolution}{size_text}",
                    'resolution': stream.resolution,
                    'extension': 'mp4',
                    'has_audio': True,
                    'filesize': stream.filesize_mb
                })
        
        # Procesar formatos de audio
        audio_formats = []
        for stream in audio_streams.order_by('abr').desc()[:3]:  # Limitar a 3 opciones
            size_text = f" - {stream.filesize_mb:.1f} MB" if stream.filesize_mb else ""
            audio_formats.append({
                'id': f"audio_{stream.abr}",
                'display': f"🎵 Audio {stream.abr}{size_text}",
                'extension': 'm4a',
                'filesize': stream.filesize_mb
            })
        
        # Si no hay formatos, usar opciones básicas
        if not video_formats:
            video_formats = [{
                'id': 'video_auto',
                'display': '🎥 Video (calidad automática)',
                'resolution': 'auto',
                'extension': 'mp4',
                'has_audio': True
            }]
        
        if not audio_formats:
            audio_formats = [{
                'id': 'audio_auto',
                'display': '🎵 Audio',
                'extension': 'm4a'
            }]
        
        # Formatos predefinidos
        predefined_formats = []
        if video_formats:
            predefined_formats.append({
                'id': 'video_best', 
                'display': '🎯 Mejor calidad de video'
            })
        if len(video_formats) > 1:
            predefined_formats.append({
                'id': 'video_medium',
                'display': '📹 Calidad media'
            })
        if audio_formats:
            predefined_formats.append({
                'id': 'audio_best',
                'display': '🔊 Mejor calidad de audio'
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
        error_msg = str(e)
        if "429" in error_msg:
            return jsonify({'success': False, 'error': 'YouTube está bloqueando solicitudes. Espera 5-10 minutos e intenta nuevamente.'})
        else:
            return jsonify({'success': False, 'error': f'Error al obtener información: {error_msg}'})

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
    elif format_id == 'video_medium':
        format_type = 'video'
    elif format_id == 'audio_best':
        format_type = 'audio'
    else:
        format_type = 'video'
    
    download_id = f"dl_{int(time.time())}_{hash(url)}"
    
    print(f"🚀 Iniciando descarga: {format_type} ({format_id})")
    
    download_thread = DownloadThread(url, format_type, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada',
        'format_type': format_type
    })

# ... (mantener las demás rutas igual: progress, download, cancel_download, status)

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
        'message': '✅ Servicio funcionando con protección anti-rate-limiting',
        'features': [
            'Rotación de User-Agents',
            'Reintentos automáticos',
            'Delays aleatorios',
            'Manejo de errores 429'
        ]
    })

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
