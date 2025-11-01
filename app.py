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
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

download_progress = {}

# Métodos alternativos para obtener información sin usar yt-dlp para metadata
def get_random_headers():
    """Generar headers realistas"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36'
    ]
    
    return {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

def extract_video_id(url):
    """Extraer ID del video de múltiples formatos de URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)',
        r'youtube\.com\/embed\/([^&?\n]+)',
        r'youtube\.com\/v\/([^&?\n]+)',
        r'youtube\.com\/watch\?.+&v=([^&]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_info_external(video_id):
    """Obtener información del video usando APIs externas"""
    apis = [
        # API de oEmbed oficial de YouTube
        {
            'url': f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json',
            'title_key': 'title',
            'author_key': 'author_name',
            'thumbnail_key': 'thumbnail_url'
        },
        # Noembed.com
        {
            'url': f'https://noembed.com/embed?url=https://www.youtube.com/watch?v={video_id}',
            'title_key': 'title',
            'author_key': 'author_name',
            'thumbnail_key': 'thumbnail_url'
        },
        # Embed.ly (fallback)
        {
            'url': f'https://api.embed.ly/1/oembed?url=https://www.youtube.com/watch?v={video_id}',
            'title_key': 'title',
            'author_key': 'author_name',
            'thumbnail_key': 'thumbnail_url'
        }
    ]
    
    for api in apis:
        try:
            response = requests.get(api['url'], timeout=10, headers=get_random_headers())
            if response.status_code == 200:
                data = response.json()
                return {
                    'title': data.get(api['title_key'], f'Video {video_id}'),
                    'author': data.get(api['author_key'], 'YouTube'),
                    'thumbnail': data.get(api['thumbnail_key'], f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'),
                    'success': True
                }
        except:
            continue
    
    # Si todas las APIs fallan, usar información básica
    return {
        'title': f'Video {video_id}',
        'author': 'YouTube',
        'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
        'success': True
    }

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

def direct_download_attempt(url, format_type, download_folder, download_id):
    """Intento directo de descarga sin obtener información primero"""
    try:
        # Configuración ultra-minimalista
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'restrictfilenames': True,
            'socket_timeout': 30,
            'extractor_retries': 1,
            'http_headers': get_random_headers(),
            'ratelimit': 128000,
            'outtmpl': os.path.join(download_folder, '%(title).70s.%(ext)s'),
        }
        
        # Configurar formato basado en el tipo
        if format_type == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }]
        elif format_type == 'worst':
            ydl_opts['format'] = 'worst[height<=360]'
        else:  # best
            ydl_opts['format'] = 'best[height<=480]'
        
        # Hook de progreso simple
        def progress_hook(d):
            if d['status'] == 'downloading':
                progress = d.get('_percent_str', '0%').replace('%', '').strip()
                try:
                    progress_value = float(progress) if progress.replace('.', '').isdigit() else 0
                    download_progress[download_id] = {
                        'progress': progress_value,
                        'status': 'downloading',
                        'speed': d.get('_speed_str', 'N/A'),
                        'eta': d.get('_eta_str', 'N/A')
                    }
                except:
                    download_progress[download_id] = {
                        'progress': 0,
                        'status': 'downloading'
                    }
            elif d['status'] == 'finished':
                download_progress[download_id] = {
                    'progress': 100,
                    'status': 'completed',
                    'filename': os.path.basename(d.get('filename', ''))
                }
        
        ydl_opts['progress_hooks'] = [progress_hook]
        
        # Intentar descarga directa
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info, None
            
    except Exception as e:
        return None, str(e)

class DownloadThread(threading.Thread):
    def __init__(self, url, format_id, download_id):
        threading.Thread.__init__(self)
        self.url = url
        self.format_id = format_id
        self.download_id = download_id
        self.filename = None
        self.error = None

    def run(self):
        try:
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'preparando',
                'error': None
            }
            
            # Crear directorio temporal
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Pequeño delay aleatorio
            time.sleep(random.uniform(1, 3))
            
            print(f"🚀 Iniciando descarga directa: {self.format_id}")
            
            # Intentar descarga directa
            info, error = direct_download_attempt(self.url, self.format_id, download_folder, self.download_id)
            
            if error:
                raise Exception(error)
                
            if info:
                # Obtener nombre de archivo
                if self.format_id == 'audio':
                    base_name = os.path.splitext(yt_dlp.YoutubeDL({}).prepare_filename(info))[0]
                    self.filename = base_name + '.mp3'
                else:
                    self.filename = yt_dlp.YoutubeDL({}).prepare_filename(info)
                
                download_progress[self.download_id] = {
                    'progress': 100,
                    'status': 'completed',
                    'filename': os.path.basename(self.filename),
                    'title': info.get('title', 'video_descargado')
                }
                print(f"✅ Descarga exitosa: {self.filename}")
            else:
                raise Exception("No se pudo completar la descarga")
                
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error en descarga: {error_msg}")
            
            # Mensajes de error más específicos
            if "Private" in error_msg:
                self.error = "El video es privado o no está disponible."
            elif "Unavailable" in error_msg:
                self.error = "El video no está disponible en tu país o fue eliminado."
            elif "Sign in" in error_msg:
                self.error = "YouTube requiere iniciar sesión para ver este video."
            elif "too many requests" in error_msg.lower() or "429" in error_msg:
                self.error = "Límite de solicitudes excedido. Espera 30-60 minutos."
            elif "bot" in error_msg.lower():
                self.error = "YouTube ha bloqueado las descargas automáticas. Intenta más tarde."
            else:
                self.error = f"No se pudo descargar el video. Error: {error_msg}"
            
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
    """Obtener información del video usando métodos externos"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    try:
        # Obtener información usando APIs externas
        video_info = get_video_info_external(video_id)
        
        # Siempre ofrecer solo formatos básicos y estables
        formats = {
            'video': [
                {'id': 'worst', 'display': '🎥 Video calidad baja (360p) - Más estable'},
                {'id': 'best', 'display': '🎥 Video calidad media (480p)'}
            ],
            'audio': [
                {'id': 'audio', 'display': '🔊 Solo audio MP3 - Menos bloqueos'}
            ],
            'predefined': [
                {'id': 'audio', 'display': '🔊 SOLO AUDIO (Recomendado)'},
                {'id': 'worst', 'display': '📹 Video baja calidad'},
                {'id': 'best', 'display': '🎥 Video media calidad'}
            ]
        }
        
        return jsonify({
            'success': True,
            'title': video_info['title'],
            'duration': 0,  # No disponible con APIs externas
            'thumbnail': video_info['thumbnail'],
            'description': f'Video de {video_info["author"]}. La descarga directa puede intentarse pero no hay garantías debido a restricciones de YouTube.',
            'formats': formats,
            'message': '⚠️ ADVERTENCIA: Las descargas pueden fallar debido a bloqueos de YouTube. Prioriza "Solo audio".'
        })
        
    except Exception as e:
        return jsonify({
            'success': True,
            'title': f'Video {video_id}',
            'duration': 0,
            'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
            'description': 'Información limitada disponible debido a restricciones.',
            'formats': {
                'video': [
                    {'id': 'worst', 'display': '🎥 Intentar descargar video (puede fallar)'}
                ],
                'audio': [
                    {'id': 'audio', 'display': '🔊 Intentar descargar audio (menos bloqueos)'}
                ],
                'predefined': [
                    {'id': 'audio', 'display': '🔊 Solo audio (recomendado)'},
                    {'id': 'worst', 'display': '📹 Video baja calidad'}
                ]
            },
            'message': '❌ No se pudo obtener información completa. Puedes intentar descargar directamente.'
        })

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'audio')  # Audio por defecto
    
    if not url or not format_id:
        return jsonify({'success': False, 'error': 'URL y formato requeridos'})
    
    download_id = f"dl_{int(time.time())}_{random.randint(1000, 9999)}"
    
    download_thread = DownloadThread(url, format_id, download_id)
    download_thread.start()
    
    return jsonify({
        'success': True, 
        'download_id': download_id,
        'message': 'Descarga iniciada. Esto puede tomar varios minutos...'
    })

@app.route('/api/progress/<download_id>')
def get_progress(download_id):
    progress = download_progress.get(download_id, {
        'progress': 0,
        'status': 'no_iniciado'
    })
    return jsonify(progress)

@app.route('/api/download/<download_id>')
def download_file(download_id):
    progress = download_progress.get(download_id, {})
    
    if progress.get('status') != 'completed':
        return jsonify({'success': False, 'error': 'Descarga no completada o falló'})
    
    filename = progress.get('filename', '')
    if not filename:
        return jsonify({'success': False, 'error': 'Archivo no encontrado'})
    
    temp_dir = tempfile.gettempdir()
    download_folder = os.path.join(temp_dir, 'youtube_downloads')
    file_path = os.path.join(download_folder, filename)
    
    # Buscar el archivo real (puede tener nombre diferente)
    if not os.path.exists(file_path):
        actual_files = [f for f in os.listdir(download_folder) if f.startswith('Video') or f.endswith(('.mp4', '.mp3', '.webm'))]
        if actual_files:
            file_path = os.path.join(download_folder, actual_files[0])
            filename = actual_files[0]
        else:
            return jsonify({'success': False, 'error': 'Archivo no encontrado en el servidor'})
    
    # Limpiar el progreso
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
        'status': 'limited',
        'message': '🔴 Servicio limitado por restricciones de YouTube',
        'recommendations': [
            'SOLO AUDIO funciona en ~60% de los casos',
            'Videos cortos y menos populares tienen más éxito',
            'Espera 10+ minutos entre descargas',
            'Considera usar herramientas locales para descargas críticas'
        ]
    })

@app.route('/api/tips')
def get_tips():
    return jsonify({
        'tips': [
            "🎧 PRIORIDAD ABSOLUTA: Usa 'Solo audio'",
            "⏰ Espera 10+ minutos entre descargas",
            "📹 Videos de <10 minutos funcionan mejor", 
            "🔍 Canales pequeños tienen menos restricciones",
            "💡 Si falla 2 veces, espera 1 hora",
            "🔄 Reinicia la app si hay muchos errores"
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
