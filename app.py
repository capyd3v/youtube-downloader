import os
import tempfile
import threading
from flask import Flask, render_template, request, jsonify, send_file
import time
import re
import random

# USAR youtube-dl con configuración anti-bot
import youtube_dl

app = Flask(__name__)

# Configuración
class Config:
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
        self.download_folder = os.path.join(self.temp_dir, 'youtube_downloads')
        os.makedirs(self.download_folder, exist_ok=True)

config = Config()

# Almacenar progreso
download_progress = {}

# Lista de User-Agents rotativos
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
]

def get_ydl_opts():
    """Configuración anti-bot para YouTube"""
    return {
        'outtmpl': os.path.join(config.download_folder, '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': False,
        
        # Configuración anti-bot
        'http_headers': {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        
        # Configuración de red
        'socket_timeout': 30,
        'source_address': '0.0.0.0',
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
                'status': 'completed',
                'filename': d.get('filename', '')
            }

    def run(self):
        try:
            ydl_opts = get_ydl_opts()
            ydl_opts['progress_hooks'] = [self.progress_hook]
            
            # Configuración simple
            if self.format_id == 'best':
                ydl_opts['format'] = 'best'
            elif self.format_id == 'worst':
                ydl_opts['format'] = 'worst'
            else:
                ydl_opts['format'] = self.format_id
            
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
                self.filename = ydl.prepare_filename(info)
                
                download_progress[self.download_id] = {
                    'progress': 100,
                    'status': 'completed',
                    'filename': os.path.basename(self.filename),
                    'title': info.get('title', 'video')
                }
                
        except Exception as e:
            self.error = str(e)
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'error',
                'error': f'Error en descarga: {str(e)}'
            }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/video_info', methods=['POST'])
def get_video_info():
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    try:
        ydl_opts = get_ydl_opts()
        ydl_opts.update({
            'skip_download': True,
            'no_warnings': True
        })
        
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            video_info = ydl.extract_info(url, download=False)
        
        return jsonify({
            'success': True,
            'title': video_info.get('title', 'Sin título'),
            'duration': video_info.get('duration', 0),
            'thumbnail': video_info.get('thumbnail', ''),
            'description': 'Descarga disponible - YouTube puede requerir verificación humana para algunos videos',
            'formats': {
                'predefined': [
                    {'id': 'best', 'display': '🎯 Mejor calidad (recomendado)'},
                    {'id': 'worst', 'display': '📉 Peor calidad'}
                ]
            }
        })
        
    except Exception as e:
        error_msg = str(e)
        if 'Sign in' in error_msg or 'bot' in error_msg:
            return jsonify({
                'success': False, 
                'error': 'YouTube requiere verificación humana. Intenta con otro video o prueba más tarde.'
            })
        else:
            return jsonify({'success': False, 'error': f'Error: {error_msg}'})

# ... (mantén las otras rutas igual: start_download, progress, download_file)

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', '')
    
    if not url or not format_id:
        return jsonify({'success': False, 'error': 'URL y formato requeridos'})
    
    download_id = f"dl_{int(time.time())}"
    download_thread = DownloadThread(url, format_id, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada - Nota: Algunos videos pueden requerir verificación'
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
    
    file_path = os.path.join(config.download_folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': 'Archivo no existe'})
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
