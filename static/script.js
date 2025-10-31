// Variables globales
let currentDownloadId = null;
let progressInterval = null;

// Elementos DOM
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
    downloadBtn: document.getElementById('downloadBtn'),
    
    // Progress
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    speedText: document.getElementById('speedText'),
    etaText: document.getElementById('etaText'),
    downloadActions: document.getElementById('downloadActions'),
    finalDownloadBtn: document.getElementById('finalDownloadBtn'),
    newDownloadBtn: document.getElementById('newDownloadBtn'),
    cancelBtn: document.getElementById('cancelBtn')
};

// Inicialización
document.addEventListener('DOMContentLoaded', function() {
    initializeTabs();
    attachEventListeners();
});

// Sistema de pestañas
function initializeTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            
            // Actualizar botones activos
            tabButtons.forEach(btn => btn.classList.remove('active'));
            this.classList.add('active');
            
            // Actualizar contenido visible
            document.querySelectorAll('.tab-pane').forEach(pane => {
                pane.classList.remove('active');
            });
            document.getElementById(tabName + 'Tab').classList.add('active');
            
            // Actualizar estado del botón de descarga
            updateDownloadButtonState();
        });
    });
}

// Event listeners
function attachEventListeners() {
    elements.fetchBtn.addEventListener('click', fetchVideoInfo);
    elements.downloadBtn.addEventListener('click', startDownload);
    elements.finalDownloadBtn.addEventListener('click', downloadCompletedFile);
    elements.newDownloadBtn.addEventListener('click', resetToInitialState);
    elements.cancelBtn.addEventListener('click', cancelDownload);
    
    // Enter key en input de URL
    elements.urlInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            fetchVideoInfo();
        }
    });
    
    // Cambios en selects de formato
    elements.predefinedSelect.addEventListener('change', updateDownloadButtonState);
    elements.videoSelect.addEventListener('change', updateDownloadButtonState);
    elements.audioSelect.addEventListener('change', updateDownloadButtonState);
}

// Obtener información del video
async function fetchVideoInfo() {
    const url = elements.urlInput.value.trim();
    
    if (!url) {
        showError('Por favor ingresa una URL de YouTube');
        return;
    }
    
    // Validar URL de YouTube
    if (!isValidYouTubeUrl(url)) {
        showError('Por favor ingresa una URL válida de YouTube');
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

// Mostrar información del video
function displayVideoInfo(data) {
    // Thumbnail
    elements.videoThumbnail.src = data.thumbnail;
    elements.videoThumbnail.alt = data.title;
    
    // Title
    elements.videoTitle.textContent = data.title;
    
    // Duration
    const minutes = Math.floor(data.duration / 60);
    const seconds = data.duration % 60;
    elements.videoDuration.textContent = `Duración: ${minutes}m ${seconds}s`;
    
    // Description
    elements.videoDescription.textContent = data.description;
    
    // Llenar selectores de formato
    populateFormatSelectors(data.formats);
    
    // Mostrar sección de información
    elements.videoInfoSection.style.display = 'block';
}

// Llenar selectores de formato
function populateFormatSelectors(formats) {
    // Limpiar selects
    elements.predefinedSelect.innerHTML = '<option value="">Selecciona una opción...</option>';
    elements.videoSelect.innerHTML = '<option value="">Selecciona calidad de video...</option>';
    elements.audioSelect.innerHTML = '<option value="">Selecciona formato de audio...</option>';
    
    // Formatos predefinidos
    formats.predefined.forEach(format => {
        const option = document.createElement('option');
        option.value = format.id;
        option.textContent = format.display;
        elements.predefinedSelect.appendChild(option);
    });
    
    // Formatos de video
    formats.video.forEach(format => {
        const option = document.createElement('option');
        option.value = format.id;
        option.textContent = format.display;
        elements.videoSelect.appendChild(option);
    });
    
    // Formatos de audio
    formats.audio.forEach(format => {
        const option = document.createElement('option');
        option.value = format.id;
        option.textContent = format.display;
        elements.audioSelect.appendChild(option);
    });
}

// Actualizar estado del botón de descarga
function updateDownloadButtonState() {
    const activeTab = document.querySelector('.tab-btn.active').getAttribute('data-tab');
    let selectedFormat = '';
    
    switch (activeTab) {
        case 'predefined':
            selectedFormat = elements.predefinedSelect.value;
            break;
        case 'video':
            selectedFormat = elements.videoSelect.value;
            break;
        case 'audio':
            selectedFormat = elements.audioSelect.value;
            break;
    }
    
    elements.downloadBtn.disabled = !selectedFormat;
}

// Iniciar descarga
async function startDownload() {
    const url = elements.urlInput.value.trim();
    const activeTab = document.querySelector('.tab-btn.active').getAttribute('data-tab');
    let formatId = '';
    
    // Obtener formato seleccionado
    switch (activeTab) {
        case 'predefined':
            formatId = elements.predefinedSelect.value;
            break;
        case 'video':
            formatId = elements.videoSelect.value;
            break;
        case 'audio':
            formatId = elements.audioSelect.value;
            break;
    }
    
    if (!formatId) {
        showError('Por favor selecciona un formato');
        return;
    }
    
    try {
        const response = await fetch('/api/start_download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                url: url, 
                format_id: formatId 
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentDownloadId = data.download_id;
            showDownloadProgress();
            startProgressTracking();
        } else {
            showError(data.error || 'Error al iniciar la descarga');
        }
    } catch (error) {
        showError('Error de conexión: ' + error.message);
    }
}

// Mostrar sección de progreso
function showDownloadProgress() {
    elements.videoInfoSection.style.display = 'none';
    elements.downloadSection.style.display = 'block';
    elements.downloadActions.style.display = 'none';
    elements.cancelBtn.style.display = 'block';
    
    // Reset progress
    updateProgress(0, '0%', '--', '--');
}

// Seguimiento del progreso
function startProgressTracking() {
    progressInterval = setInterval(async () => {
        if (!currentDownloadId) return;
        
        try {
            const response = await fetch(`/api/progress/${currentDownloadId}`);
            const progress = await response.json();
            
            if (progress.status === 'completed') {
                downloadCompleted(progress);
            } else if (progress.status === 'error') {
                downloadError(progress.error);
            } else {
                updateProgress(
                    progress.progress || 0,
                    `${Math.round(progress.progress || 0)}%`,
                    progress.speed || '--',
                    progress.eta || '--'
                );
            }
        } catch (error) {
            console.error('Error tracking progress:', error);
        }
    }, 1000);
}

// Actualizar interfaz de progreso
function updateProgress(percent, text, speed, eta) {
    elements.progressFill.style.width = percent + '%';
    elements.progressText.textContent = text;
    elements.speedText.innerHTML = `<i class="fas fa-tachometer-alt"></i> Velocidad: ${speed}`;
    elements.etaText.innerHTML = `<i class="fas fa-clock"></i> Tiempo restante: ${eta}`;
}

// Descarga completada
function downloadCompleted(progress) {
    clearInterval(progressInterval);
    
    updateProgress(100, '100% - Completado!', '--', '--');
    
    elements.downloadActions.style.display = 'flex';
    elements.cancelBtn.style.display = 'none';
    
    // Actualizar botón de descarga final
    elements.finalDownloadBtn.innerHTML = 
        `<i class="fas fa-file-download"></i> Descargar "${progress.title || 'video'}"`;
}

// Error en descarga
function downloadError(error) {
    clearInterval(progressInterval);
    showError('Error en la descarga: ' + error);
    resetToInitialState();
}

// Descargar archivo completado
function downloadCompletedFile() {
    if (!currentDownloadId) return;
    
    window.location.href = `/api/download/${currentDownloadId}`;
}

// Cancelar descarga
async function cancelDownload() {
    if (currentDownloadId) {
        try {
            await fetch(`/api/cancel_download/${currentDownloadId}`, { method: 'POST' });
        } catch (error) {
            console.error('Error canceling download:', error);
        }
    }
    
    resetToInitialState();
}

// Resetear a estado inicial
function resetToInitialState() {
    clearInterval(progressInterval);
    currentDownloadId = null;
    
    elements.downloadSection.style.display = 'none';
    elements.videoInfoSection.style.display = 'block';
    elements.errorSection.style.display = 'none';
}

// Utilidades
function isValidYouTubeUrl(url) {
    const patterns = [
        /^(https?:\/\/)?(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/,
        /^(https?:\/\/)?(www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})/,
        /^(https?:\/\/)?(www\.)?youtube\.com\/v\/([a-zA-Z0-9_-]{11})/
    ];
    
    return patterns.some(pattern => pattern.test(url));
}

function showLoading() {
    elements.loadingSection.style.display = 'block';
    elements.fetchBtn.disabled = true;
}

function hideLoading() {
    elements.loadingSection.style.display = 'none';
    elements.fetchBtn.disabled = false;
}

function showError(message) {
    elements.errorText.textContent = message;
    elements.errorSection.style.display = 'block';
}

function hideError() {
    elements.errorSection.style.display = 'none';
}
