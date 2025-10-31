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
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Cambia esto en producción

# Almacenar progreso de descargas (en memoria, para producción usar Redis)
download_progress = {}

# Lista de User-Agents rotativos
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0'
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def get_ydl_opts_base():
    """Configuración base mejorada para yt-dlp"""
    user_agent = get_random_user_agent()
    return {
        'quiet': True,
        'no_warnings': False,
        'ignoreerrors': False,
        'extract_flat': False,
        'restrictfilenames': True,
        'http_headers': {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        },
        # Configuración específica para YouTube
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['configs', 'webpage']
            }
        },
        'postprocessor_args': {
            'ffmpeg': ['-hide_banner']
        }
    }

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
            # Crear directorio temporal para descargas
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Configuración mejorada
            ydl_opts = get_ydl_opts_base()
            ydl_opts.update({
                'outtmpl': os.path.join(download_folder, '%(title).100s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
            })
            
            # Configurar formato según selección
            selected_format = self.format_id
            
            # Estrategias de formato mejoradas
            if selected_format == 'best':
                ydl_opts['format'] = 'best[height<=1080]'
            elif selected_format == 'worst':
                ydl_opts['format'] = 'worst'
            elif selected_format == 'bestvideo+bestaudio':
                ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio'
                ydl_opts['merge_output_format'] = 'mp4'
            elif '+' in selected_format:
                ydl_opts['format'] = selected_format
            else:
                # Para formatos individuales, combinar con mejor audio
                ydl_opts['format'] = f'{selected_format}+bestaudio'
                ydl_opts['merge_output_format'] = 'mp4'
            
            # Agregar postprocessors para combinar formatos
            if '+' in ydl_opts.get('format', ''):
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]
            
            # Intentar con diferentes configuraciones
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    # Actualizar User-Agent para cada intento
                    ydl_opts['http_headers']['User-Agent'] = get_random_user_agent()
                    
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
                        break  # Salir del loop si tiene éxito
                        
                except yt_dlp.DownloadError as e:
                    if attempt < max_retries - 1:
                        # Cambiar estrategia en el segundo intento
                        if 'best' in ydl_opts.get('format', ''):
                            ydl_opts['format'] = 'worst'
                        time.sleep(2)  # Esperar antes de reintentar
                        continue
                    else:
                        raise e
                
        except Exception as e:
            error_msg = str(e)
            if "Sign in" in error_msg or "confirm you're not a bot" in error_msg:
                self.error = "YouTube ha bloqueado la descarga. Esto es común en servidores cloud. Intenta con un video menos popular o espera unos minutos."
            elif "Video unavailable" in error_msg:
                self.error = "Video no disponible en tu región o restringido."
            elif "Private video" in error_msg:
                self.error = "Este video es privado."
            elif "Copyright" in error_msg:
                self.error = "El video tiene restricciones de copyright."
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
    """Obtener información del video y formatos disponibles"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    # Validar que sea una URL de YouTube
    if 'youtube.com' not in url and 'youtu.be' not in url:
        return jsonify({'success': False, 'error': 'Solo se admiten URLs de YouTube'})
    
    try:
        # Crear nuevas opciones para cada petición con User-Agent actualizado
        ydl_opts = get_ydl_opts_base()
        ydl_opts.update({
            'skip_download': True,
            'extract_flat': False,
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            video_info = ydl.extract_info(url, download=False)
        
        # Obtener miniatura de mayor calidad disponible
        thumbnails = video_info.get('thumbnails', [])
        thumbnail_url = video_info.get('thumbnail', '')
        if thumbnails:
            # Buscar la miniatura de mayor resolución
            best_thumbnail = max(thumbnails, key=lambda x: x.get('width', 0) * x.get('height', 0))
            thumbnail_url = best_thumbnail.get('url', thumbnail_url)
        
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
                
                # Verificar si incluye audio
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
        
        # Agregar opciones predefinidas optimizadas
        predefined_formats = [
            {'id': 'best', 'display': '🎯 Mejor calidad (hasta 1080p)'},
            {'id': 'worst', 'display': '📉 Calidad más baja (para evitar bloqueos)'},
            {'id': 'bestvideo+bestaudio', 'display': '🏆 Mejor video + mejor audio'}
        ]
        
        return jsonify({
            'success': True,
            'title': video_info.get('title', 'Sin título'),
            'duration': video_info.get('duration', 0),
            'thumbnail': thumbnail_url,
            'description': video_info.get('description', '')[:500] + '...' if video_info.get('description') else 'Sin descripción',
            'formats': {
                'video': video_formats,
                'audio': audio_formats,
                'predefined': predefined_formats
            }
        })
        
    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "confirm you're not a bot" in error_msg:
            return jsonify({
                'success': False, 
                'error': 'YouTube está bloqueando las descargas desde este servidor. Intenta con videos menos populares o formatos de menor calidad.'
            })
        elif "Video unavailable" in error_msg:
            return jsonify({'success': False, 'error': 'Video no disponible o restringido.'})
        elif "Private video" in error_msg:
            return jsonify({'success': False, 'error': 'Este video es privado.'})
        else:
            return jsonify({'success': False, 'error': f'Error al obtener información: {error_msg}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/api/start_download', methods=['POST'])
def start_download():
    """Iniciar descarga en segundo plano"""
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', '')
    
    if not url or not format_id:
        return jsonify({'success': False, 'error': 'URL y formato requeridos'})
    
    # Generar ID único para la descarga
    download_id = f"dl_{int(time.time())}_{hash(url)}"
    
    # Iniciar descarga en hilo separado
    download_thread = DownloadThread(url, format_id, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada'
    })

@app.route('/api/progress/<download_id>')
def get_progress(download_id):
    """Obtener progreso de la descarga"""
    progress = download_progress.get(download_id, {
        'progress': 0,
        'status': 'unknown'
    })
    
    return jsonify(progress)

@app.route('/api/download/<download_id>')
def download_file(download_id):
    """Descargar archivo completado"""
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
    
    # Limpiar progreso después de descargar
    if download_id in download_progress:
        del download_progress[download_id]
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/cancel_download/<download_id>', methods=['POST'])
def cancel_download(download_id):
    """Cancelar descarga (limpiar estado)"""
    if download_id in download_progress:
        del download_progress[download_id]
    
    return jsonify({'success': True, 'message': 'Descarga cancelada'})

@app.route('/api/tips')
def get_tips():
    """Endpoint para obtener tips de uso"""
    return jsonify({
        'tips': [
            "Usa formatos de menor calidad para videos populares (menos bloqueos)",
            "Los videos menos vistos tienen menos restricciones",
            "Si falla, espera unos minutos y reintenta",
            "Evita videos con copyright estricto"
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
