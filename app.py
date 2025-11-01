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
    """Configuración base mejorada con técnicas anti-bot"""
    return {
        'quiet': True,
        'no_warnings': False,
        'ignoreerrors': True,  # Cambiar a True para ignorar errores menores
        'extract_flat': False,
        'restrictfilenames': True,
        'socket_timeout': 45,  # Aumentar timeout
        'extractor_retries': 2,  # Reducir reintentos
        
        # Configuración específica para YouTube anti-bot
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
                'player_skip': ['webpage', 'configs'],
            }
        },
        
        # Headers realistas con rotación
        'http_headers': get_random_headers(),
        
        # Configuración de rate limiting más conservadora
        'ratelimit': 512000,  # Reducir límite de velocidad
        'throttledratelimit': 256000,
        
        # Intentar evitar detección de bot
        'no_check_certificate': False,  # Cambiar a False para mejor compatibilidad
        'prefer_insecure': False,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        
        # Nuevas opciones para mejorar compatibilidad
        'compat_opts': ['seperate-video-versions'],
        'writeinfojson': False,
        'consoletitle': False,
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

def get_fallback_video_info(url):
    """Método de fallback cuando todo lo demás falla"""
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("No se pudo extraer ID del video")
    
    print("🔄 Usando método de fallback...")
    
    # Intentar con diferentes métodos alternativos
    fallback_methods = [
        # Método 1: Usar embed API
        lambda: get_basic_video_info(video_id),
        # Método 2: Usar i.ytimg.com para miniatura
        lambda: {
            'title': f"Video {video_id}",
            'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            'author': 'YouTube',
            'duration': 0,
            'success': True
        }
    ]
    
    for method in fallback_methods:
        try:
            result = method()
            if result.get('success'):
                return result
        except:
            continue
    
    # Información mínima de fallback
    return {
        'title': f"Video {video_id}",
        'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        'author': 'YouTube',
        'duration': 0,
        'success': True
    }

def get_video_info_with_strategies(url, max_retries=3):
    """Obtener información usando múltiples estrategias mejoradas"""
    strategies = [
        # Estrategia 1: Headers móviles
        {
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'],
                    'player_skip': ['webpage']
                }
            },
        },
        # Estrategia 2: Sin extractor args
        {
            'extractor_args': {},
        },
        # Estrategia 3: Solo información básica
        {
            'extract_flat': True,
            'force_json': True,
        }
    ]
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            strategy_idx = attempt % len(strategies)
            strategy = strategies[strategy_idx]
            
            ydl_opts = get_ydl_opts_base()
            ydl_opts.update(strategy)
            
            # Rotar headers en cada intento
            ydl_opts['http_headers'] = get_random_headers()
            
            # Aumentar timeout progresivamente
            ydl_opts['socket_timeout'] = 30 + (attempt * 10)
            
            print(f"🎯 Intento {attempt + 1}, Estrategia {strategy_idx + 1}")
            
            # Delay exponencial entre intentos
            if attempt > 0:
                wait_time = min(2 ** attempt, 30)  # Máximo 30 segundos
                print(f"⏳ Esperando {wait_time} segundos...")
                time.sleep(wait_time)
            
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
                print("🚫 Rate limit detectado, esperando más tiempo...")
                time.sleep(15)  # Espera más larga para rate limit
            elif "Unavailable" in last_error:
                raise Exception("Video no disponible")
            
            if attempt == max_retries - 1:
                # Si todas las estrategias fallan, usar método alternativo
                return get_fallback_video_info(url)
                
        except Exception as e:
            last_error = str(e)
            print(f"❌ Error inesperado: {last_error}")
            if attempt == max_retries - 1:
                return get_fallback_video_info(url)
            time.sleep(min(2 ** attempt, 30))
    
    return get_fallback_video_info(url)

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
        
        # Si llegamos aquí, la información se obtuvo exitosamente
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
        
        # Usar información de fallback
        basic_info = get_fallback_video_info(url)
        
        return jsonify({
            'success': True,
            'title': basic_info['title'],
            'duration': basic_info.get('duration', 0),
            'thumbnail': basic_info['thumbnail'],
            'description': f'Video de {basic_info["author"]} - Información limitada por restricciones de YouTube',
            'formats': {
                'video': [
                    {'id': 'worst', 'display': '📹 Calidad baja (recomendado)'},
                    {'id': 'best', 'display': '🎥 Intentar descargar video'}
                ],
                'audio': [
                    {'id': 'audio', 'display': '🔊 Solo audio MP3'}
                ],
                'predefined': [
                    {'id': 'worst', 'display': '📉 Calidad baja (menos bloqueos)'},
                    {'id': 'audio', 'display': '🔊 Solo audio (recomendado)'}
                ]
            },
            'message': '⚠️ Información limitada - Usa "Calidad baja" o "Solo audio" para mejor resultado'
        })

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
