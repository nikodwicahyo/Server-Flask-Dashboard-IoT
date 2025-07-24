/* IoT CCTV - Dashboard Script */

/* Changes:
 * - Fixed PIR status to reflect connection status only (connected/disconnected)
 * - Changed "online" to "Online" for ESP32-CAM status
 * - Added dynamic toggle for video streaming and flash without changing ESP32-CAM code
 * - Fixed issue where stream and toggle turn off unexpectedly when not capturing
 * - Updated: 2025-07-24
 */

// DOM Elements
const connectionStatus = document.getElementById("connectionStatus");
const cameraFeed = document.getElementById("cameraFeed");
const faceCanvas = document.getElementById("faceCanvas");
const streamIndicator = document.getElementById("streamIndicator");
const captureBtn = document.getElementById("captureBtn");
const flashBtn = document.getElementById("flashBtn");
const streamToggleBtn = document.getElementById("streamToggleBtn");
const detectionTime = document.getElementById("detectionTime");
const detectionResults = document.getElementById("detectionResults");
const motionCount = document.getElementById("motionCount");
const knownFaces = document.getElementById("knownFaces");
const unknownFaces = document.getElementById("unknownFaces");
const withMask = document.getElementById("withMask");
const cameraStatus = document.getElementById("cameraStatus");
const sensorStatus = document.getElementById("sensorStatus");
const buzzerStatus = document.getElementById("buzzerStatus");
const telegramStatus = document.getElementById("telegramStatus");
const testAlarmBtn = document.getElementById("testAlarmBtn");
const testNotificationBtn = document.getElementById("testNotificationBtn");
const historyTableBody = document.getElementById("historyTableBody");
const modal = document.getElementById("imageModal");
const modalImage = document.getElementById("modalImage");
const modalDetails = document.getElementById("modalDetails");
const closeModal = document.querySelector(".close");
const themeToggleBtn = document.getElementById("themeToggleBtn");

// Configuration
const API_BASE_URL = "http://192.168.5.24:5000"; // Updated to Flask server IP
const ESP32_CAM_URL = "http://192.168.5.50";
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY = 3000;
const STREAM_RETRY_INTERVAL = 200; 
const MAX_STREAM_RETRIES = 3;
const CAPTURE_TIMEOUT = 5000; 
const STATUS_UPDATE_INTERVAL = 10000; 

// Global variables
let isConnected = false;
let isStreaming = false;
let flashState = false; 
let isCapturing = false; 
let stats = {
    motionCount: 0,
    knownFaces: 0,
    unknownFaces: 0,
    withMask: 0,
};
let detectionHistory = [];
let streamInterval = null;
let lastImagePath = null;
let reconnectAttempts = 0;

// Toast notification function
function showToast(message, type = "info") {
    try {
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        let icon = "";
        switch (type) {
            case "success":
                icon = '<i class="fas fa-check-circle"></i>';
                break;
            case "error":
                icon = '<i class="fas fa-exclamation-circle"></i>';
                break;
            case "warning":
                icon = '<i class="fas fa-exclamation-triangle"></i>';
                break;
            default:
                icon = '<i class="fas fa-info-circle"></i>';
        }
        toast.innerHTML = `${icon}<span>${message}</span>`;
        document.getElementById("toast-container").appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    } catch (error) {
        console.error("Error showing toast:", error);
        alert(`Error: ${message}`);
    }
}

// Show loading overlay
function showLoadingOverlay() {
    try {
        let overlay = document.getElementById("loadingOverlay");
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.id = "loadingOverlay";
            overlay.innerHTML = `
                <div class="loading-content">
                    <div class="spinner"></div>
                    <div class="loading-text">Processing...</div>
                </div>
            `;
            document.body.appendChild(overlay);
        }
        overlay.style.display = "flex";
    } catch (error) {
        console.error("Error showing loading overlay:", error);
        showToast("Failed to show loading overlay", "error");
    }
}

// Hide loading overlay
function hideLoadingOverlay() {
    try {
        const overlay = document.getElementById("loadingOverlay");
        if (overlay) {
            overlay.style.display = "none";
        }
    } catch (error) {
        console.error("Error hiding loading overlay:", error);
        showToast("Failed to hide loading overlay", "error");
    }
}

// Update system time
function updateTime() {
    try {
        const now = new Date();
        detectionTime.textContent = now.toLocaleString("id-ID", {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
    } catch (error) {
        console.error("Error updating time:", error);
        detectionTime.textContent = "Error updating time";
    }
}

// Check ESP32-CAM health
async function checkEsp32Health() {
    try {
        const response = await fetch(`${ESP32_CAM_URL}/`, { signal: AbortSignal.timeout(5000) });
        if (!response.ok) {
            throw new Error(`ESP32-CAM responded with status ${response.status}`);
        }
        const data = await response.json();
        return data.status === "Online";
    } catch (error) {
        console.error("ESP32-CAM health check failed:", error);
        return false;
    }
}

// Start video stream
async function startStream() {
    try {
        if (!isStreaming) {
            const isHealthy = await checkEsp32Health();
            if (!isHealthy) {
                showToast("ESP32-CAM tidak merespons. Mencoba menghubungkan kembali...", "warning");
                await reconnectStream();
                return;
            }
            isStreaming = true;
            streamToggleBtn.innerHTML = '<i class="fas fa-pause"></i>';
            streamIndicator.classList.remove("hidden");
            cameraFeed.src = `${ESP32_CAM_URL}:81/stream`;
            cameraFeed.onload = () => {
                console.log("Stream loaded successfully");
                showToast("Streaming dimulai", "success");
                reconnectAttempts = 0;
            };
            cameraFeed.onerror = async () => {
                if (isStreaming) {
                    showToast("Koneksi streaming terputus. Mencoba menghubungkan kembali...", "warning");
                    await reconnectStream();
                }
            };
        }
    } catch (error) {
        console.error("Error starting stream:", error);
        showToast("Gagal memulai streaming: " + error.message, "error");
        isStreaming = false;
        streamToggleBtn.innerHTML = '<i class="fas fa-play"></i>';
        streamIndicator.classList.add("hidden");
    }
}

// Stop video stream
async function stopStream() {
    try {
        isStreaming = false;
        streamToggleBtn.innerHTML = '<i class="fas fa-play"></i>';
        streamIndicator.classList.add("hidden");
        cameraFeed.src = "";
        await fetch(`${ESP32_CAM_URL}/control?cmd=stopstream`, { signal: AbortSignal.timeout(5000) });
        showToast("Streaming dihentikan", "success");
    } catch (error) {
        console.error("Error stopping stream:", error);
        showToast("Gagal menghentikan streaming: " + error.message, "error");
    }
}

// Reconnect stream with exponential backoff
async function reconnectStream() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        showToast(`Gagal menghubungkan ke ESP32-CAM setelah ${MAX_RECONNECT_ATTEMPTS} percobaan`, "error");
        reconnectAttempts = 0;
        stopStream();
        return;
    }
    try {
        reconnectAttempts++;
        const delay = RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts);
        await new Promise((resolve) => setTimeout(resolve, delay));
        const isHealthy = await checkEsp32Health();
        if (isHealthy) {
            await startStream();
        } else {
            showToast(`Mencoba menghubungkan kembali... Percobaan ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}`, "warning");
            await reconnectStream();
        }
    } catch (error) {
        console.error("Error reconnecting stream:", error);
        showToast("Gagal menghubungkan kembali streaming: " + error.message, "error");
        await reconnectStream();
    }
}

// Toggle flash (dynamic control)
async function toggleFlash() {
    try {
        flashBtn.disabled = true;
        showLoadingOverlay();
        const response = await fetch(`${ESP32_CAM_URL}/control?cmd=flash`, { signal: AbortSignal.timeout(5000) });
        if (!response.ok) {
            throw new Error(`Flash toggle failed with status ${response.status}`);
        }
        flashState = !flashState;
        flashBtn.classList.toggle('flash-on', flashState);
        flashBtn.classList.toggle('flash-off', !flashState);
        showToast(`Flash ${flashState ? "turned ON" : "turned OFF"}`, "success");
    } catch (error) {
        console.error("Error toggling flash:", error);
        showToast("Gagal mengubah status flash: " + error.message, "error");
    } finally {
        flashBtn.disabled = false;
        hideLoadingOverlay();
    }
}

// Capture image with automatic toggle off
async function captureImage() {
    try {
        if (isCapturing) return; // Hindari capture berulang
        isCapturing = true;
        captureBtn.disabled = true;
        showLoadingOverlay();

        // Automatically turn off flash and streaming before capture
        if (flashState) {
            await toggleFlash(); // Matikan flash jika menyala
        }
        if (isStreaming) {
            await stopStream(); // Hentikan streaming jika aktif
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CAPTURE_TIMEOUT);

        const response = await fetch(`${ESP32_CAM_URL}/capture`, {
            signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!response.ok) {
            throw new Error(`Capture failed with status ${response.status}`);
        }

        const blob = await response.blob();
        const imageUrl = URL.createObjectURL(blob);
        cameraFeed.src = imageUrl; // Temporary display
        lastImagePath = imageUrl;

        const formData = new FormData();
        formData.append("image", blob, "capture.jpg");

        const processResponse = await fetch(`${API_BASE_URL}/api/process_image`, {
            method: "POST",
            body: formData,
            signal: AbortSignal.timeout(10000),
        });

        if (!processResponse.ok) {
            throw new Error(`Image processing failed with status ${processResponse.status}`);
        }

        const data = await processResponse.json();
        updateDetectionResults(data);
        showToast("Gambar berhasil diambil dan diproses", "success");
    } catch (error) {
        console.error("Error capturing image:", error);
        showToast("Gagal mengambil gambar: " + error.message, "error");
    } finally {
        isCapturing = false;
        captureBtn.disabled = false;
        hideLoadingOverlay();
    }
}

// Update detection results
function updateDetectionResults(data) {
    try {
        detectionResults.innerHTML = "";
        if (data.faces_detected === 0) {
            detectionResults.innerHTML = '<p class="empty-history">Tidak ada wajah terdeteksi</p>';
            return;
        }

        data.results.forEach((result, index) => {
            const item = document.createElement("div");
            item.className = "detection-item";
            item.innerHTML = `
                <h3>Wajah ${index + 1}</h3>
                <div class="detection-field">
                    <span class="field-label">Nama:</span>
                    <span class="field-value ${result.name.startsWith('Tidak Dikenal') ? 'text-danger' : 'text-success'}">${result.name}</span>
                </div>    
                <div class="detection-field">
                    <span class="field-label">Usia:</span>
                    <span class="field-value">${result.age}</span>
                </div>
                <div class="detection-field">
                    <span class="field-label">Gender:</span>
                    <span class="field-value">${result.gender}</span>
                </div>
                <div class="detection-field">
                    <span class="field-label">Masker:</span>
                    <span class="field-value ${result.mask === 'Pakai' ? 'text-success' : 'text-warning'}">${result.mask}</span>
                </div>
                <div class="detection-field">
                    <span class="field-label">Keyakinan:</span>
                    <div class="confidence-container">
                        <div class="progress-bar">
                            <div class="progress-value" style="width: ${result.face_confidence * 100}%"></div>
                        </div>
                        <span class="confidence-text">${Math.round(result.face_confidence * 100)}%</span>
                    </div>
                </div>
            `;
            detectionResults.appendChild(item);
        });

        lastImagePath = data.image_path;
        stats.knownFaces = data.results.filter(r => !r.name.startsWith("Tidak Dikenal")).length;
        stats.unknownFaces = data.results.filter(r => r.name.startsWith("Tidak Dikenal")).length;
        stats.withMask = data.results.filter(r => r.mask === "Pakai").length;

        updateStats();
    } catch (error) {
        console.error("Error updating detection results:", error);
        showToast("Gagal memperbarui hasil deteksi", "error");
    }
}

// Update statistics
function updateStats() {
    try {
        motionCount.textContent = stats.motionCount;
        knownFaces.textContent = stats.knownFaces;
        unknownFaces.textContent = stats.unknownFaces;
        withMask.textContent = stats.withMask;
    } catch (error) {
        console.error("Error updating stats:", error);
        showToast("Gagal memperbarui statistik", "error");
    }
}

// Update ESP32-CAM and server status
async function updateEsp32Status() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/status`, { signal: AbortSignal.timeout(10000) });
        if (!response.ok) {
            throw new Error(`Status check failed with status ${response.status}`);
        }
        const data = await response.json();

        isConnected = data.status === "Online"; 
        connectionStatus.className = `status-indicator ${isConnected ? "online" : "offline"}`;
        connectionStatus.innerHTML = `
            <span class="dot ${isConnected ? "online" : "offline"}"></span>
            ${isConnected ? "Online" : "Offline"}
        `;

        const esp32Status = data.esp32_status;
        cameraStatus.textContent = esp32Status.status === "Online" ? "Online" : "Offline"; 
        cameraStatus.className = `status-badge ${esp32Status.status === "Online" ? "online" : "offline"}`; 
        sensorStatus.textContent = esp32Status.pir_connected ? "Terhubung" : "Terputus";
        sensorStatus.className = `status-badge ${esp32Status.pir_connected ? "online" : "disconnected"}`;
        buzzerStatus.textContent = esp32Status.buzzer ? "Terhubung" : "Terputus";
        buzzerStatus.className = `status-badge ${esp32Status.buzzer ? "online" : "disconnected"}`;
        telegramStatus.textContent = data.telegram_enabled ? "Terhubung" : "Terputus";
        telegramStatus.className = `status-badge ${data.telegram_enabled ? "online" : "offline"}`;

        stats.motionCount = esp32Status.motion_count || 0;

        // Periksa dan perbarui Deteksi Terbaru dari LAST_DETECTION hanya jika ada perubahan baru
        if (data.LAST_DETECTION && !isCapturing) {
            updateDetectionResults(data.LAST_DETECTION);
        }

        if (!isConnected && isStreaming) {
            await stopStream();
            showToast("Koneksi server terputus", "error");
        }

        updateStats();
    } catch (error) {
        console.error("Error updating ESP32 status:", error);
        isConnected = false;
        connectionStatus.className = "status-indicator offline";
        connectionStatus.innerHTML = '<span class="dot offline"></span> Offline';
        showToast("Gagal memperbarui status", "error");
    }
}

// Update detection history
async function updateHistory() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/history?limit=10`, { signal: AbortSignal.timeout(10000) });
        if (!response.ok) {
            throw new Error(`History fetch failed with status ${response.status}`);
        }
        detectionHistory = await response.json();
        historyTableBody.innerHTML = "";

        if (detectionHistory.length === 0) {
            historyTableBody.innerHTML = '<tr><td colspan="6" class="empty-history">Tidak ada riwayat deteksi</td></tr>';
            return;
        }

        detectionHistory.forEach(entry => {
            const results = entry.results || [];
            const age = results.length > 0 
                ? Math.round(results.reduce((sum, r) => sum + parseInt(r.age || 0), 0) / results.length) || "N/A"
                : "N/A";
            const gender = results.length > 0 
                ? (new Set(results.map(r => r.gender)).size > 1 ? "Mixed" : results[0].gender)
                : "N/A";
            const maskCount = results.filter(r => r.mask === "Pakai").length;
            const confidence = results.length > 0 
                ? Math.round(results.reduce((sum, r) => sum + r.face_confidence * 100, 0) / results.length) + "%"
                : "N/A";

            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${entry.timestamp}</td>
                <td>${results.length}</td>
                <td>${age}</td>
                <td>${gender}</td>
                <td>${maskCount}</td>
                <td>${confidence}</td>
            `;
            row.addEventListener("click", () => showModal(entry));
            historyTableBody.appendChild(row);
        });

        // Sync stats with history
        stats.knownFaces = detectionHistory.reduce((sum, entry) => sum + (entry.results.filter(r => !r.name.startsWith("Tidak Dikenal")).length || 0), 0);
        stats.unknownFaces = detectionHistory.reduce((sum, entry) => sum + (entry.results.filter(r => r.name.startsWith("Tidak Dikenal")).length || 0), 0);
        stats.withMask = detectionHistory.reduce((sum, entry) => sum + (entry.results.filter(r => r.mask === "Pakai").length || 0), 0);

        updateStats();
    } catch (error) {
        console.error("Error updating history:", error);
        showToast("Gagal memperbarui riwayat", "error");
    }
}

// Show modal with detection details
function showModal(entry) {
    try {
        modal.style.display = "block";
        modalImage.src = `${API_BASE_URL}${entry.image_path}`;
        modalDetails.innerHTML = entry.results
            .map(
                (result, index) => `
                    <p><strong>Wajah ${index + 1}</strong></p>
                    <p>Nama: ${result.name}</p>
                    <p>Usia: ${result.age}</p>
                    <p>Gender: ${result.gender}</p>
                    <p>Masker: ${result.mask}</p>
                    <p>Keyakinan: ${Math.round(result.face_confidence * 100)}%</p>
                `
            )
            .join("<hr>");
    } catch (error) {
        console.error("Error showing modal:", error);
        showToast("Gagal menampilkan detail deteksi", "error");
    }
}

// Test alarm
async function testAlarm() {
    try {
        testAlarmBtn.disabled = true;
        showLoadingOverlay();
        const response = await fetch(`${API_BASE_URL}/api/test_buzzer`, { signal: AbortSignal.timeout(10000) });
        if (!response.ok) {
            throw new Error(`Buzzer test failed with status ${response.status}`);
        }
        const data = await response.json();
        showToast(data.message, data.status);
    } catch (error) {
        console.error("Error testing buzzer:", error);
        showToast("Gagal menguji alarm: " + error.message, "error");
    } finally {
        testAlarmBtn.disabled = false;
        hideLoadingOverlay();
    }
}

// Test Telegram notification
async function testNotification() {
    try {
        testNotificationBtn.disabled = true;
        const response = await fetch(`${API_BASE_URL}/api/test_telegram`, { signal: AbortSignal.timeout(5000) });
        if (!response.ok) {
            throw new Error(`Telegram test failed with status ${response.status}`);
        }
        const data = await response.json();
        showToast(data.message, data.status);
    } catch (error) {
        console.error("Error testing Telegram:", error);
        showToast("Gagal menguji notifikasi Telegram", "error");
    } finally {
        testNotificationBtn.disabled = false;
    }
}

// Toggle theme
function toggleTheme() {
    try {
        const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
        const newTheme = currentTheme === "light" ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", newTheme);
        localStorage.setItem("theme", newTheme);
        themeToggleBtn.innerHTML = newTheme === "light" ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-sun"></i>';
    } catch (error) {
        console.error("Error toggling theme:", error);
        showToast("Gagal mengganti tema", "error");
    }
}

// Initialize
async function init() {
    try {
        // Load saved theme
        const savedTheme = localStorage.getItem("theme") || "light";
        document.documentElement.setAttribute("data-theme", savedTheme);
        themeToggleBtn.innerHTML = savedTheme === "light" ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-sun"></i>';

        // Set up event listeners
        streamToggleBtn.addEventListener("click", async () => {
            try {
                isStreaming ? await stopStream() : await startStream();
            } catch (error) {
                console.error("Error toggling stream:", error);
                showToast("Gagal mengalihkan streaming", "error");
            }
        });

        captureBtn.addEventListener("click", captureImage);
        flashBtn.addEventListener("click", toggleFlash);
        testAlarmBtn.addEventListener("click", testAlarm);
        testNotificationBtn.addEventListener("click", testNotification);
        closeModal.addEventListener("click", () => {
            try {
                modal.style.display = "none";
            } catch (error) {
                console.error("Error closing modal:", error);
                showToast("Gagal menutup modal", "error");
            }
        });
        themeToggleBtn.addEventListener("click", toggleTheme);

        window.addEventListener("click", (event) => {
            try {
                if (event.target === modal) {
                    modal.style.display = "none";
                }
            } catch (error) {
                console.error("Error handling modal click:", error);
                showToast("Gagal menangani klik modal", "error");
            }
        });

        // Start periodic updates
        setInterval(updateTime, 1000);
        setInterval(updateEsp32Status, STATUS_UPDATE_INTERVAL);
        setInterval(updateHistory, 30000);

        // Initial updates
        updateTime();
        await updateEsp32Status();
        await updateHistory();

        // Start stream if ESP32 is online
        if (isConnected) {
            await startStream();
        }
    } catch (error) {
        console.error("Error initializing app:", error);
        showToast("Gagal menginisialisasi aplikasi", "error");
    }
}

// Run initialization
document.addEventListener("DOMContentLoaded", init);