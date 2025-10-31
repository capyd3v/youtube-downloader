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
app.secret_key = 'your_secret_key_here'

# Almacenar progreso de descargas
download_progress = {}

# Lista de User-Agents rotativos
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def get_ydl_opts_base():
    """Configuración base mejorada para yt-dlp"""
    return {
        'quiet': True,
        'no_warnings': False,
        'ignoreerrors': False,
        'extract_flat': False,
        'restrictfilenames': True,
        # Configuración crítica para YouTube
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
                'player_skip': ['configs', 'webpage'],
            }
        },
        'http_headers': {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        },
        # Forzar actualización de extractores
        'update': False,
        'no_update': True,
    }

def get_video_info_with_fallback(url):
    """Obtener información del video con múltiples estrategias"""
    strategies = [
        # Estrategia 1: Configuración normal
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        },
        # Estrategia 2: Configuración minimalista
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        },
        # Estrategia 3: Usar innertube
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'extractor_args': {'youtube': {'player_client': ['ios']}},
        }
    ]
    
    for i, strategy in enumerate(strategies):
        try:
            ydl_opts = get_ydl_opts_base()
            ydl_opts.update(strategy)
            ydl_opts['http_headers']['User-Agent'] = get_random_user_agent()
            
            print(f"Intentando estrategia {i + 1}...")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
                
        except Exception as e:
            print(f"Estrategia {i + 1} falló: {str(e)}")
            if i == len(strategies) - 1:  # Última estrategia
                raise e
            time.sleep(1)  # Pequeña pausa entre intentos
    
    raise Exception("Todas las estrategias fallaron")

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
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            ydl_opts = get_ydl_opts_base()
            ydl_opts.update({
                'outtmpl': os.path.join(download_folder, '%(title).100s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
            })
            
            # Configurar formato
            selected_format = self.format_id
            if selected_format == 'best':
                ydl_opts['format'] = 'best[height<=720]'  # Reducir calidad para mayor compatibilidad
            elif selected_format == 'worst':
                ydl_opts['format'] = 'worst'
            elif selected_format == 'bestvideo+bestaudio':
                ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio'
                ydl_opts['merge_output_format'] = 'mp4'
            elif '+' in selected_format:
                ydl_opts['format'] = selected_format
            else:
                ydl_opts['format'] = f'{selected_format}+bestaudio'
                ydl_opts['merge_output_format'] = 'mp4'
            
            # Intentar con diferentes estrategias
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    ydl_opts['http_headers']['User-Agent'] = get_random_user_agent()
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(self.url, download=True)
                        self.filename = ydl.prepare_filename(info)
                        
                        download_progress[self.download_id] = {
                            'progress': 100,
                            'status': 'completed',
                            'filename': os.path.basename(self.filename),
                            'title': info.get('title', 'video')
                        }
                        break
                        
                except yt_dlp.DownloadError as e:
                    if attempt < max_retries - 1:
                        # Cambiar estrategia de formato en reintentos
                        if 'best' in ydl_opts.get('format', ''):
                            ydl_opts['format'] = 'worst'
                        time.sleep(2)
                        continue
                    else:
                        raise e
                
        except Exception as e:
            error_msg = str(e)
            if "Failed to extract any player response" in error_msg:
                self.error = "Error temporal de YouTube. Por favor, actualiza yt-dlp o intenta más tarde."
            elif "Sign in" in error_msg:
                self.error = "YouTube está bloqueando descargas desde servidores cloud. Intenta con otro video."
            elif "Video unavailable" in error_msg:
                self.error = "Video no disponible."
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
    
    if 'youtube.com' not in url and 'youtu.be' not in url:
        return jsonify({'success': False, 'error': 'Solo se admiten URLs de YouTube'})
    
    try:
        # Usar la función con estrategias de fallback
        video_info = get_video_info_with_fallback(url)
        
        # Procesar información del video (mantener igual que antes)
        thumbnails = video_info.get('thumbnails', [])
        thumbnail_url = video_info.get('thumbnail', '')
        if thumbnails:
            best_thumbnail = max(thumbnails, key=lambda x: x.get('width', 0) * x.get('height', 0))
            thumbnail_url = best_thumbnail.get('url', thumbnail_url)
        
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
            
            if not resolution or resolution.lower() == 'unknown':
                continue
            
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
            
            elif acodec != 'none' and vcodec == 'none':
                audio_formats.append({
                    'id': format_id,
                    'display': f"Audio only ({ext.upper()}) - {filesize / (1024*1024):.1f} MB" if filesize else f"Audio only ({ext.upper()})",
                    'extension': ext
                })
        
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
        
        predefined_formats = [
            {'id': 'best', 'display': '🎯 Mejor calidad (hasta 720p)'},
            {'id': 'worst', 'display': '📉 Calidad más baja'},
            {'id': 'bestvideo+bestaudio', 'display': '🏆 Mejor video + audio'}
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
        
    except Exception as e:
        error_msg = str(e)
        if "Failed to extract any player response" in error_msg:
            return jsonify({
                'success': False, 
                'error': 'YouTube ha cambiado su estructura. Por favor, actualiza yt-dlp o intenta más tarde.'
            })
        elif "Sign in" in error_msg:
            return jsonify({
                'success': False, 
                'error': 'YouTube está bloqueando el acceso. Intenta con videos menos populares.'
            })
        else:
            return jsonify({'success': False, 'error': f'Error: {error_msg}'})

# ... (mantener el resto de las rutas igual: start_download, progress, download, cancel_download, tips)

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', '')
    
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

@app.route('/api/tips')
def get_tips():
    return jsonify({
        'tips': [
            "Actualiza yt-dlp frecuentemente para evitar errores",
            "Usa formatos de menor calidad para mayor compatibilidad",
            "Los videos menos populares tienen menos restricciones",
            "Si falla, espera y reintenta en unos minutos"
        ]
    })

@app.route('/api/version')
def get_version():
    """Endpoint para verificar la versión de yt-dlp"""
    return jsonify({
        'version': yt_dlp.version.__version__,
        'update_required': True  # Indicar que necesita actualización
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
