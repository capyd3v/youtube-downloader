// Variables globales
let currentDownloadId = null;
let progressInterval = null;
let currentVideoInfo = null;

// Elementos del DOM
const elements = {
    urlInput: document.getElementById('urlInput'),
    fetchBtn: document.getElementById('fetchBtn'),
    loadingSection: document.getElementById('loadingSection'),
    videoInfoSection: document.getElementById('videoInfoSection'),
    downloadSection: document.getElementById('downloadSection'),
    errorSection: document.getElementById('errorSection'),
    
    // Video info
    videoThumbnail: document.getElementById('videoThumbnail'),
    videoTitle: document.getElementById('videoTitle'),
    videoDuration: document.getElementById('videoDuration'),
    videoDescription: document.getElementById('videoDescription'),
    
    // Format selectors
    predefinedSelect: document.getElementById('predefinedSelect'),
    videoSelect: document.getElementById('videoSelect'),
    audioSelect: document.getElementById('audioSelect'),
    
    // Buttons
    downloadBtn: document.getElementById('downloadBtn'),
    finalDownloadBtn: document.getElementById('finalDownloadBtn'),
    newDownloadBtn: document.getElementById('newDownloadBtn'),
    cancelBtn: document.getElementById('cancelBtn'),
    
    // Progress
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    speedText: document.getElementById('speedText'),
    etaText: document.getElementById('etaText'),
    downloadActions: document.getElementById('downloadActions'),
    
    // Error
    errorText: document.getElementById('errorText'),
    
    // Tabs
    tabBtns: document.querySelectorAll('.tab-btn'),
    tabPanes: document.querySelectorAll('.tab-pane')
};

// Inicialización
document.addEventListener('DOMContentLoaded', function() {
    initializeEventListeners();
    showTips();
});

function initializeEventListeners() {
    // Buscar video
    elements.fetchBtn.addEventListener('click', fetchVideoInfo);
    elements.urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') fetchVideoInfo();
    });

    // Tabs
    elements.tabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            switchTab(e.target.dataset.tab);
        });
    });

    // Selectores de formato
    elements.predefinedSelect.addEventListener('change', updateDownloadButton);
    elements.videoSelect.addEventListener('change', updateDownloadButton);
    elements.audioSelect.addEventListener('change', updateDownloadButton);

    // Botones de descarga
    elements.downloadBtn.addEventListener('click', startDownload);
    elements.finalDownloadBtn.addEventListener('click', downloadFile);
    elements.newDownloadBtn.addEventListener('click', resetUI);
    elements.cancelBtn.addEventListener('click', cancelDownload);
}

// Cambiar pestañas
function switchTab(tabName) {
    // Remover clase active de todos los botones y paneles
    elements.tabBtns.forEach(btn => btn.classList.remove('active'));
    elements.tabPanes.forEach(pane => pane.classList.remove('active'));

    // Activar el tab seleccionado
    const activeBtn = document.querySelector(`[data-tab="${tabName}"]`);
    const activePane = document.getElementById(`${tabName}Tab`);
    
    if (activeBtn && activePane) {
        activeBtn.classList.add('active');
        activePane.classList.add('active');
    }
}

// Obtener información del video
async function fetchVideoInfo() {
    const url = elements.urlInput.value.trim();
    
    if (!url) {
        showError('Por favor, ingresa una URL de YouTube');
        return;
    }

    // Validación básica de URL de YouTube
    if (!isValidYouTubeUrl(url)) {
        showError('URL de YouTube no válida');
        return;
    }

    showLoading();
    hideError();

    try {
        const response = await fetch('/api/video_info', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url })
        });

        const data = await response.json();

        if (data.success) {
            currentVideoInfo = data;
            displayVideoInfo(data);
        } else {
            showError(data.error || 'Error al obtener información del video');
        }
    } catch (error) {
        showError('Error de conexión: ' + error.message);
    } finally {
        hideLoading();
    }
}

// Validar URL de YouTube
function isValidYouTubeUrl(url) {
    const patterns = [
        /^(https?:\/\/)?(www\.)?(youtube\.com\/watch\?v=)([^&]{11})/,
        /^(https?:\/\/)?(www\.)?(youtu\.be\/)([^&]{11})/,
        /^(https?:\/\/)?(www\.)?(youtube\.com\/embed\/)([^&]{11})/
    ];
    return patterns.some(pattern => pattern.test(url));
}

// Mostrar información del video
function displayVideoInfo(data) {
    // Información básica del video
    elements.videoThumbnail.src = data.thumbnail || '/static/default-thumbnail.jpg';
    elements.videoThumbnail.alt = data.title || 'Miniatura del video';
    
    elements.videoTitle.textContent = data.title || 'Sin título';
    
    // Duración
    if (data.duration && data.duration > 0) {
        const minutes = Math.floor(data.duration / 60);
        const seconds = data.duration % 60;
        elements.videoDuration.textContent = `Duración: ${minutes}:${seconds.toString().padStart(2, '0')}`;
    } else {
        elements.videoDuration.textContent = 'Duración: Desconocida';
    }
    
    // Descripción
    elements.videoDescription.textContent = data.description || 'Sin descripción disponible';

    // Llenar selectores de formato - CON VALIDACIONES SEGURAS
    populateFormatSelectors(data.formats || {});

    // Mostrar sección de información
    elements.videoInfoSection.style.display = 'block';
    
    // Resetear selecciones
    resetFormatSelections();
}

// Llenar selectores de formato (MANEJO SEGURO)
function populateFormatSelectors(formats) {
    // Limpiar selectores
    elements.predefinedSelect.innerHTML = '<option value="">Selecciona una opción...</option>';
    elements.videoSelect.innerHTML = '<option value="">Selecciona calidad de video...</option>';
    elements.audioSelect.innerHTML = '<option value="">Selecciona formato de audio...</option>';

    // Formatos predefinidos - CON VALIDACIÓN
    const predefined = formats.predefined || [];
    if (Array.isArray(predefined) && predefined.length > 0) {
        predefined.forEach(format => {
            if (format && format.id && format.display) {
                const option = new Option(format.display, format.id);
                elements.predefinedSelect.add(option);
            }
        });
    }

    // Formatos de video - CON VALIDACIÓN
    const videoFormats = formats.video || [];
    if (Array.isArray(videoFormats) && videoFormats.length > 0) {
        videoFormats.forEach(format => {
            if (format && format.id && format.display) {
                const option = new Option(format.display, format.id);
                elements.videoSelect.add(option);
            }
        });
    } else {
        elements.videoSelect.innerHTML = '<option value="">No hay formatos de video disponibles</option>';
    }

    // Formatos de audio - CON VALIDACIÓN
    const audioFormats = formats.audio || [];
    if (Array.isArray(audioFormats) && audioFormats.length > 0) {
        audioFormats.forEach(format => {
            if (format && format.id && format.display) {
                const option = new Option(format.display, format.id);
                elements.audioSelect.add(option);
            }
        });
    } else {
        elements.audioSelect.innerHTML = '<option value="">No hay formatos de audio disponibles</option>';
    }
}

// Resetear selecciones de formato
function resetFormatSelections() {
    elements.predefinedSelect.value = '';
    elements.videoSelect.value = '';
    elements.audioSelect.value = '';
    elements.downloadBtn.disabled = true;
}

// Actualizar botón de descarga
function updateDownloadButton() {
    const predefinedValue = elements.predefinedSelect.value;
    const videoValue = elements.videoSelect.value;
    const audioValue = elements.audioSelect.value;
    
    elements.downloadBtn.disabled = !(predefinedValue || videoValue || audioValue);
}

// Iniciar descarga
async function startDownload() {
    const selectedFormat = getSelectedFormat();
    
    if (!selectedFormat) {
        showError('Por favor, selecciona un formato');
        return;
    }

    if (!currentVideoInfo) {
        showError('No hay información del video disponible');
        return;
    }

    const url = elements.urlInput.value.trim();

    showDownloadProgress();
    hideError();

    try {
        const response = await fetch('/api/start_download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                url: url,
                format_id: selectedFormat
            })
        });

        const data = await response.json();

        if (data.success) {
            currentDownloadId = data.download_id;
            startProgressTracking();
        } else {
            showError(data.error || 'Error al iniciar la descarga');
            hideDownloadProgress();
        }
    } catch (error) {
        showError('Error de conexión: ' + error.message);
        hideDownloadProgress();
    }
}

// Obtener formato seleccionado
function getSelectedFormat() {
    const predefinedValue = elements.predefinedSelect.value;
    const videoValue = elements.videoSelect.value;
    const audioValue = elements.audioSelect.value;
    
    return predefinedValue || videoValue || audioValue || null;
}

// Seguimiento del progreso
function startProgressTracking() {
    if (progressInterval) {
        clearInterval(progressInterval);
    }

    progressInterval = setInterval(async () => {
        if (!currentDownloadId) return;

        try {
            const response = await fetch(`/api/progress/${currentDownloadId}`);
            const progress = await response.json();
            
            updateProgressDisplay(progress);

            if (progress.status === 'completed' || progress.status === 'error') {
                stopProgressTracking();
                
                if (progress.status === 'completed') {
                    showDownloadComplete();
                } else {
                    showError(progress.error || 'Error en la descarga');
                }
            }
        } catch (error) {
            console.error('Error al verificar el progreso:', error);
        }
    }, 1000);
}

// Actualizar display del progreso
function updateProgressDisplay(progress) {
    const percent = progress.progress || 0;
    const speed = progress.speed || '--';
    const eta = progress.eta || '--';
    const status = progress.status || 'Procesando';

    elements.progressFill.style.width = `${percent}%`;
    elements.progressText.textContent = `${Math.round(percent)}%`;
    elements.speedText.innerHTML = `<i class="fas fa-tachometer-alt"></i> Velocidad: ${speed}`;
    elements.etaText.innerHTML = `<i class="fas fa-clock"></i> Tiempo restante: ${eta}`;

    // Cambiar color según el estado
    if (percent < 30) {
        elements.progressFill.style.backgroundColor = '#e74c3c';
    } else if (percent < 70) {
        elements.progressFill.style.backgroundColor = '#f39c12';
    } else {
        elements.progressFill.style.backgroundColor = '#2ecc71';
    }
}

// Mostrar descarga completada
function showDownloadComplete() {
    elements.downloadActions.style.display = 'block';
    elements.cancelBtn.style.display = 'none';
    elements.progressText.textContent = '¡Descarga completada!';
    elements.progressFill.style.backgroundColor = '#27ae60';
}

// Descargar archivo
function downloadFile() {
    if (!currentDownloadId) return;
    
    window.open(`/api/download/${currentDownloadId}`, '_blank');
}

// Cancelar descarga
async function cancelDownload() {
    if (!currentDownloadId) return;

    try {
        await fetch(`/api/cancel_download/${currentDownloadId}`, { 
            method: 'POST' 
        });
        
        stopProgressTracking();
        hideDownloadProgress();
        showError('Descarga cancelada');
    } catch (error) {
        showError('Error al cancelar la descarga');
    }
}

// Detener seguimiento del progreso
function stopProgressTracking() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
}

// Nueva descarga
function resetUI() {
    hideDownloadProgress();
    elements.videoInfoSection.style.display = 'none';
    elements.urlInput.value = '';
    elements.urlInput.focus();
    currentDownloadId = null;
    currentVideoInfo = null;
    resetFormatSelections();
}

// Mostrar/ocultar secciones
function showLoading() {
    elements.loadingSection.style.display = 'block';
    elements.fetchBtn.disabled = true;
}

function hideLoading() {
    elements.loadingSection.style.display = 'none';
    elements.fetchBtn.disabled = false;
}

function showDownloadProgress() {
    elements.downloadSection.style.display = 'block';
    elements.downloadActions.style.display = 'none';
    elements.cancelBtn.style.display = 'block';
    elements.progressFill.style.width = '0%';
    elements.progressText.textContent = '0%';
    elements.speedText.innerHTML = '<i class="fas fa-tachometer-alt"></i> Velocidad: --';
    elements.etaText.innerHTML = '<i class="fas fa-clock"></i> Tiempo restante: --';
}

function hideDownloadProgress() {
    elements.downloadSection.style.display = 'none';
}

function showError(message) {
    elements.errorText.textContent = message;
    elements.errorSection.style.display = 'block';
    
    // Ocultar error después de 5 segundos
    setTimeout(() => {
        hideError();
    }, 5000);
}

function hideError() {
    elements.errorSection.style.display = 'none';
}

// Mostrar consejos (puedes implementar una API para esto)
function showTips() {
    console.log('💡 Consejos: Usa videos menos populares para mejor resultado');
}
