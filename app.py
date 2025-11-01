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

# Configuración avanzada para yt-dlp con anti-bot
def get_ydl_opts_base():
    """Configuración base con técnicas anti-bot"""
    return {
        'quiet': True,
        'no_warnings': False,
        'ignoreerrors': False,
        'extract_flat': False,
        'restrictfilenames': True,
        'socket_timeout': 30,
        'extractor_retries': 3,
        
        # Configuración específica para YouTube anti-bot
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web_mobile'],
                'player_skip': ['configs', 'webpage', 'js'],
            }
        },
        
        # Headers realistas con rotación
        'http_headers': get_random_headers(),
        
        # Configuración de rate limiting
        'ratelimit': 1024000,  # Limitar velocidad de descarga
        'throttledratelimit': 512000,
        
        # Intentar evitar detección de bot
        'no_check_certificate': True,
        'prefer_insecure': True,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
    }

def get_random_headers():
    """Generar headers aleatorios realistas"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
    ]
    
    return {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
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

def get_video_info_with_strategies(url, max_retries=3):
    """Obtener información usando múltiples estrategias"""
    strategies = [
        # Estrategia 1: Normal con headers rotativos
        {
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        },
        # Estrategia 2: Mobile
        {
            'extractor_args': {'youtube': {'player_client': ['ios', 'android']}},
            'http_headers': get_random_headers(),
        },
        # Estrategia 3: Minimalista
        {
            'extractor_args': {'youtube': {'player_client': ['web_mobile']}},
            'http_headers': get_random_headers(),
        },
        # Estrategia 4: Sin extractor args
        {
            'http_headers': get_random_headers(),
        }
    ]
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            strategy_idx = attempt % len(strategies)
            strategy = strategies[strategy_idx]
            
            ydl_opts = get_ydl_opts_base()
            ydl_opts.update(strategy)
            ydl_opts['http_headers'] = get_random_headers()  # Rotar headers
            
            print(f"🎯 Intento {attempt + 1}, Estrategia {strategy_idx + 1}")
            
            # Delay entre intentos
            if attempt > 0:
                time.sleep(2 ** attempt)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                print("✅ Información obtenida exitosamente")
                return info
                
        except yt_dlp.DownloadError as e:
            last_error = str(e)
            print(f"❌ Estrategia {strategy_idx + 1} falló: {last_error}")
            
            if "Sign in" in last_error or "bot" in last_error:
                print("🤖 Detección de bot detectada, cambiando estrategia...")
            elif "429" in last_error:
                print("🚫 Rate limit, esperando...")
                time.sleep(10)
            
            if attempt == max_retries - 1:
                raise Exception(last_error)
                
        except Exception as e:
            last_error = str(e)
            print(f"❌ Error inesperado: {last_error}")
            if attempt == max_retries - 1:
                raise Exception(last_error)
            time.sleep(2 ** attempt)
    
    raise Exception(f"Todas las estrategias fallaron: {last_error}")

def get_thumbnail_url(video_id):
    """Obtener miniatura del video"""
    qualities = ['maxresdefault', 'hqdefault', 'mqdefault', 'default']
    for quality in qualities:
        url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
        try:
            if requests.head(url, timeout=5).status_code == 200:
                return url
        except:
            continue
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

def get_basic_video_info(video_id):
    """Obtener información básica del video usando métodos alternativos"""
    try:
        # Intentar con embed API
        embed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(embed_url, timeout=10, headers=get_random_headers())
        
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
    
    # Información de fallback
    return {
        'title': f"Video {video_id}",
        'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        'author': 'YouTube',
        'success': True
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
            download_progress[self.download_id] = {
                'progress': 0,
                'status': 'iniciando',
                'error': None
            }
            
            # Crear directorio temporal
            temp_dir = tempfile.gettempdir()
            download_folder = os.path.join(temp_dir, 'youtube_downloads')
            os.makedirs(download_folder, exist_ok=True)
            
            # Configuración de descarga
            ydl_opts = get_ydl_opts_base()
            ydl_opts.update({
                'outtmpl': os.path.join(download_folder, '%(title).100s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
            })
            
            # Configurar formato
            if self.format_id == 'best':
                ydl_opts['format'] = 'best[height<=720]'
            elif self.format_id == 'worst':
                ydl_opts['format'] = 'worst'
            elif self.format_id == 'audio':
                ydl_opts['format'] = 'bestaudio'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            else:
                ydl_opts['format'] = 'best[height<=720]'
            
            # Rotar headers para descarga
            ydl_opts['http_headers'] = get_random_headers()
            
            print(f"📥 Iniciando descarga con formato: {self.format_id}")
            
            # Intentar descarga con estrategias
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(self.url, download=True)
                        self.filename = ydl.prepare_filename(info)
                        
                        download_progress[self.download_id] = {
                            'progress': 100,
                            'status': 'completed',
                            'filename': os.path.basename(self.filename),
                            'title': info.get('title', 'video')
                        }
                        print(f"✅ Descarga completada: {self.filename}")
                        break
                        
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"🔄 Reintentando descarga... ({attempt + 1})")
                        # Cambiar estrategia de headers
                        ydl_opts['http_headers'] = get_random_headers()
                        time.sleep(5)
                        continue
                    else:
                        raise e
                
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error en descarga: {error_msg}")
            
            if "Sign in" in error_msg or "bot" in error_msg:
                self.error = "YouTube ha detectado actividad automatizada. Intenta con un video menos popular o espera unos minutos."
            elif "429" in error_msg:
                self.error = "Demasiadas solicitudes. Espera 10-15 minutos antes de intentar nuevamente."
            elif "Unavailable" in error_msg:
                self.error = "El video no está disponible."
            else:
                self.error = f"Error en la descarga: {error_msg}"
            
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
    """Obtener información del video con manejo de errores mejorado"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL requerida'})
    
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'success': False, 'error': 'URL de YouTube no válida'})
    
    try:
        # Intentar obtener información completa
        video_info = get_video_info_with_strategies(url)
        
        # Procesar formatos
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
        
        # Ordenar y limitar formatos
        def get_resolution_value(res):
            try:
                if 'p' in res.lower():
                    return int(res.lower().replace('p', ''))
                return 0
            except:
                return 0
        
        video_formats.sort(key=lambda x: get_resolution_value(x['resolution']), reverse=True)
        video_formats = video_formats[:6]  # Limitar a 6 formatos
        
        # Formatos predefinidos
        predefined_formats = [
            {'id': 'best', 'display': '🎯 Mejor calidad (hasta 720p)'},
            {'id': 'worst', 'display': '📉 Calidad baja (menos bloqueos)'},
            {'id': 'audio', 'display': '🔊 Solo audio (MP3)'}
        ]
        
        thumbnail_url = get_thumbnail_url(video_id)
        
        return jsonify({
            'success': True,
            'title': video_info.get('title', 'Sin título'),
            'duration': video_info.get('duration', 0),
            'thumbnail': thumbnail_url,
            'description': video_info.get('description', '')[:300] + '...' if video_info.get('description') else 'Sin descripción',
            'formats': {
                'video': video_formats,
                'audio': audio_formats[:3],
                'predefined': predefined_formats
            },
            'message': '✅ Información obtenida - Recomendado: usar "Calidad baja" para menos bloqueos'
        })
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error general: {error_msg}")
        
        if "Sign in" in error_msg or "bot" in error_msg:
            # Obtener información básica como fallback
            basic_info = get_basic_video_info(video_id)
            return jsonify({
                'success': True,
                'title': basic_info['title'],
                'duration': 0,
                'thumbnail': basic_info['thumbnail'],
                'description': f'Video de {basic_info["author"]} - Información limitada por restricciones',
                'formats': {
                    'video': [
                        {'id': 'best', 'display': '🎥 Intentar descargar video'},
                        {'id': 'worst', 'display': '📹 Calidad baja (recomendado)'}
                    ],
                    'audio': [
                        {'id': 'audio', 'display': '🔊 Intentar descargar audio'}
                    ],
                    'predefined': [
                        {'id': 'worst', 'display': '📉 Calidad baja (menos bloqueos)'},
                        {'id': 'audio', 'display': '🔊 Solo audio'}
                    ]
                },
                'message': '⚠️ Información limitada - Usa "Calidad baja" para mejor resultado'
            })
        else:
            return jsonify({'success': False, 'error': f'Error al obtener información: {error_msg}'})

# ... (mantener las demás rutas igual: start_download, progress, download, cancel_download, status)

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url', '')
    format_id = data.get('format_id', 'worst')  # Por defecto calidad baja
    
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

@app.route('/api/status')
def get_status():
    return jsonify({
        'status': 'active',
        'message': '✅ Servicio con protección anti-bot',
        'recommendations': [
            'Usa "Calidad baja" para menos bloqueos',
            'Videos menos populares funcionan mejor',
            'Si falla, espera 10 minutos'
        ]
    })

@app.route('/api/tips')
def get_tips():
    return jsonify({
        'tips': [
            "🎯 Usa 'Calidad baja' para evitar detección de bot",
            "📹 Videos con menos vistas funcionan mejor",
            "⏰ Espera entre descargas",
            "🔊 El formato audio tiene menos restricciones",
            "💡 Si falla, intenta con otro video"
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
