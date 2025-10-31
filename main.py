import os
import yt_dlp
import requests
from flask import Flask, render_template, request, jsonify, send_file, session
from io import BytesIO
import tempfile
import threading
import time
import re
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Cambia esto en producción

# Almacenar progreso de descargas (en memoria, para producción usar Redis)
download_progress = {}

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
            
            ydl_opts = {
                'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'quiet': True,
            }
            
            # Configurar formato según selección
            selected_format = self.format_id
            
            # Verificar si es un formato que incluye audio
            if '+' in selected_format or selected_format == 'best':
                ydl_opts['format'] = selected_format
            else:
                # Combinar video seleccionado con mejor audio
                ydl_opts['format'] = f'{selected_format}+bestaudio'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]
            
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
                
        except Exception as e:
            self.error = str(e)
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'error',
                'error': str(e)
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
    
    try:
        ydl_opts = {
            'quiet': True, 
            'skip_download': True,
            'no_warnings': True
        }
        
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
        
        # Agregar opciones predefinidas
        predefined_formats = [
            {'id': 'best', 'display': '🎯 Mejor calidad (video+audio)'},
            {'id': 'worst', 'display': '📉 Peor calidad (video+audio)'},
            {'id': 'bestvideo+bestaudio', 'display': '🏆 Mejor video + mejor audio (combinar)'}
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

if __name__ == '__main__':
    app.run(debug=True)
