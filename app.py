import os
import yt_dlp
import requests
from flask import Flask, render_template, request, jsonify, send_file
import tempfile
import threading
import time
import re
import random
import json
import base64

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

# Configuración ultra-conservadora para evitar bloqueos
def get_ydl_opts_base():
    """Configuración base ultra-conservadora"""
    return {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'extract_flat': False,
        'restrictfilenames': True,
        'socket_timeout': 60,
        'extractor_retries': 1,
        
        # Eliminar extractor_args problemáticos
        'extractor_args': {},
        
        # Headers realistas
        'http_headers': get_random_headers(),
        
        # Rate limiting muy conservador
        'ratelimit': 256000,
        'throttledratelimit': 128000,
        
        # Configuración de seguridad
        'no_check_certificate': False,
        'prefer_insecure': False,
        'geo_bypass': False,
        
        # Deshabilitar características problemáticas
        'writeinfojson': False,
        'writedescription': False,
        'writeannotations': False,
        'writethumbnail': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'consoletitle': False,
        
        # Forzar formato simple
        'format': 'worst[height<=360]',
    }

def get_random_headers():
    """Generar headers más diversos y realistas"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/121.0.0.0 Safari/537.36'
    ]
    
    accept_languages = [
        'en-US,en;q=0.9',
        'es-ES,es;q=0.9,en;q=0.8',
        'fr-FR,fr;q=0.9,en;q=0.8',
        'de-DE,de;q=0.9,en;q=0.8',
        'ja-JP,ja;q=0.9,en;q=0.8'
    ]
    
    return {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': random.choice(accept_languages),
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
    }

def extract_video_id(url):
    """Extraer ID del video"""
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

def get_basic_video_info(video_id):
    """Obtener información básica usando métodos externos"""
    try:
        # Método 1: Usar oEmbed
        embed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(embed_url, timeout=15, headers=get_random_headers())
        
        if response.status_code == 200:
            data = response.json()
            return {
                'title': data.get('title', 'Video de YouTube'),
                'thumbnail': data.get('thumbnail_url', f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'),
                'author': data.get('author_name', 'YouTube'),
                'success': True
            }
    except:
        pass
    
    try:
        # Método 2: Usar noembed.com
        noembed_url = f"https://noembed.com/embed?url=https://www.youtube.com/watch?v={video_id}"
        response = requests.get(noembed_url, timeout=15, headers=get_random_headers())
        
        if response.status_code == 200:
            data = response.json()
            return {
                'title': data.get('title', 'Video de YouTube'),
                'thumbnail': data.get('thumbnail_url', f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'),
                'author': data.get('author_name', 'YouTube'),
                'success': True
            }
    except:
        pass
    
    # Información mínima de fallback
    return {
        'title': f"Video {video_id}",
        'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        'author': 'YouTube',
        'success': True
    }

def get_video_info_simple(url):
    """Método simple y directo para obtener información"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'extract_flat': True,  # Solo metadata básica
            'socket_timeout': 30,
            'extractor_retries': 1,
            'http_headers': get_random_headers(),
            'ratelimit': 128000,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and info.get('title'):
                return info
    except:
        pass
    
    return None

def get_thumbnail_url(video_id):
    """Obtener miniatura del video"""
    qualities = ['maxresdefault', 'sddefault', 'hqdefault', 'mqdefault', 'default']
    for quality in qualities:
        url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
        try:
            response = requests.head(url, timeout=5, headers=get_random_headers())
            if response.status_code == 200:
                return url
        except:
            continue
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

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
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'iniciando',
                'error': None
            }
            
            # Delay aleatorio antes de empezar
            time.sleep(random.uniform(2, 5))
            
            # Crear directorio temporal
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Configuración ultra-conservadora para descarga
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'restrictfilenames': True,
                'socket_timeout': 60,
                'extractor_retries': 1,
                'http_headers': get_random_headers(),
                'ratelimit': 256000,
                'outtmpl': os.path.join(download_folder, '%(title).80s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
            }
            
            # Configurar formato ultra-conservador
            if self.format_id == 'audio':
                ydl_opts['format'] = 'bestaudio'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',
                }]
            elif self.format_id == 'best':
                ydl_opts['format'] = 'best[height<=480]'
            else:  # worst o por defecto
                ydl_opts['format'] = 'worst[height<=360]'
            
            print(f"📥 Iniciando descarga con formato: {self.format_id}")
            
            # Solo un intento para evitar bloqueos
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=True)
                    
                    if info is None:
                        raise Exception("No se pudo obtener información del video")
                    
                    self.filename = ydl.prepare_filename(info)
                    
                    # Para audio, cambiar la extensión
                    if self.format_id == 'audio' and self.filename:
                        base_name = os.path.splitext(self.filename)[0]
                        self.filename = base_name + '.mp3'
                    
                    download_progress[self.download_id] = {
                        'progress': 100,
                        'status': 'completed',
                        'filename': os.path.basename(self.filename) if self.filename else 'video',
                        'title': info.get('title', 'video')
                    }
                    print(f"✅ Descarga completada: {self.filename}")
                    
            except Exception as e:
                raise e
                
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error en descarga: {error_msg}")
            
            if "Sign in" in error_msg or "bot" in error_msg:
                self.error = "YouTube ha detectado actividad automatizada. Intenta más tarde o con otro video."
            elif "429" in error_msg:
                self.error = "Límite de solicitudes excedido. Espera 15-30 minutos."
            elif "Unavailable" in error_msg:
                self.error = "El video no está disponible."
            elif "Private" in error_msg:
                self.error = "El video es privado o no está disponible."
            elif "NoneType" in error_msg:
                self.error = "No se pudo acceder al video. Puede estar restringido."
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
    """Obtener información del video - enfoque minimalista"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    # Intentar método simple primero
    simple_info = get_video_info_simple(url)
    
    if simple_info:
        # Si obtenemos información simple, usarla
        thumbnail_url = get_thumbnail_url(video_id)
        
        return jsonify({
            'success': True,
            'title': simple_info.get('title', 'Video de YouTube'),
            'duration': simple_info.get('duration', 0),
            'thumbnail': thumbnail_url,
            'description': simple_info.get('description', '')[:200] + '...' if simple_info.get('description') else 'Descripción no disponible',
            'formats': {
                'video': [
                    {'id': 'worst', 'display': '📹 Calidad baja 360p (recomendado)'},
                    {'id': 'best', 'display': '🎥 Calidad media 480p'}
                ],
                'audio': [
                    {'id': 'audio', 'display': '🔊 Solo audio MP3'}
                ],
                'predefined': [
                    {'id': 'worst', 'display': '📉 Calidad baja (más estable)'},
                    {'id': 'audio', 'display': '🔊 Solo audio (menos bloqueos)'}
                ]
            },
            'message': '✅ Información básica obtenida - Usa formatos simples para mejor resultado'
        })
    else:
        # Fallback a información básica externa
        basic_info = get_basic_video_info(video_id)
        
        return jsonify({
            'success': True,
            'title': basic_info['title'],
            'duration': 0,
            'thumbnail': basic_info['thumbnail'],
            'description': f'Video de {basic_info["author"]} - Información limitada disponible',
            'formats': {
                'video': [
                    {'id': 'worst', 'display': '📹 Calidad baja 360p (recomendado)'}
                ],
                'audio': [
                    {'id': 'audio', 'display': '🔊 Solo audio MP3 (recomendado)'}
                ],
                'predefined': [
                    {'id': 'worst', 'display': '📉 Calidad baja'},
                    {'id': 'audio', 'display': '🔊 Solo audio'}
                ]
            },
            'message': '⚠️ Información limitada - Recomendado: usar "Solo audio" para menos bloqueos'
        })

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'audio')  # Por defecto audio ahora
    
    if not url or not format_id:
        return jsonify({'success': False, 'error': 'URL y formato requeridos'})
    
    download_id = f"dl_{int(time.time())}_{random.randint(1000, 9999)}"
    
    download_thread = DownloadThread(url, format_id, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada (puede tomar unos momentos)'
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
        # Buscar archivo con nombre similar
        base_name = os.path.splitext(filename)[0]
        for file in os.listdir(download_folder):
            if file.startswith(base_name):
                file_path = os.path.join(download_folder, file)
                filename = file
                break
        else:
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
        'message': '🎯 Servicio optimizado para evitar bloqueos',
        'recommendations': [
            'Usa "Solo audio" para menos bloqueos',
            'Videos cortos funcionan mejor',
            'Espera entre descargas',
            'Si falla, intenta con otro video'
        ]
    })

@app.route('/api/tips')
def get_tips():
    return jsonify({
        'tips': [
            "🎧 PRIORIDAD: Usa 'Solo audio' - tiene menos restricciones",
            "📹 Usa 'Calidad baja' para videos - más estable",
            "⏰ Espera 5-10 minutos entre descargas",
            "🔍 Videos con menos vistas funcionan mejor",
            "🔄 Si falla, no reintentes inmediatamente"
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
