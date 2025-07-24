import os
import io
import cv2
import numpy as np
import pickle
import time
import logging
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import glob
import threading
import requests
from ultralytics import YOLO
from deepface import DeepFace
import joblib
from utils.telegram import send_telegram_notification, send_multiple_faces_notification, send_system_status_notification
from utils.inference import detect_faces, recognize_face, detect_mask, predict_age, predict_gender

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, static_folder='web')
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Global variables
OUTPUT_FOLDER = os.getenv('OUTPUT_FOLDER')
RETENTION_DAYS = int(os.getenv('RETENTION_DAYS'))
MAX_HISTORY = int(os.getenv('MAX_HISTORY'))
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
DETECTION_HISTORY = []
LAST_DETECTION = None 
ESP32_CAM_URL = os.getenv('ESP32_CAM_URL')

# Create output directory
try:
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
except Exception as e:
    logger.error(f"Failed to create output directory: {e}")

# Configure app
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Load YOLOv8 and DeepFace model components
try:
    yolo_model = YOLO("models/yolov8n-face.pt")
    known_embeddings = joblib.load('models/known_embeddings.pkl')
    known_labels = joblib.load('models/known_labels.pkl')
    label_encoder = joblib.load('models/label_encoder.pkl')
    svm_model = joblib.load('models/svm_model.pkl')
    logger.info("YOLOv8 and DeepFace model components loaded successfully")
except Exception as e:
    logger.error(f"Error loading YOLOv8/DeepFace model components: {e}")
    yolo_model = None
    known_embeddings = []
    known_labels = []
    label_encoder = None
    svm_model = None

def allowed_file(filename):
    """Check if the file extension is allowed"""
    try:
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    except Exception as e:
        logger.error(f"Error checking file extension: {e}")
        return False

def draw_bounding_boxes(image, faces):
    """Draw bounding boxes and labels on the image without text background"""
    try:
        img_copy = image.copy()
        for i, face in enumerate(faces, 1):
            top, right, bottom, left = face['location']
            color = (0, 255, 0) if not face['name'].startswith('Tidak Dikenal') else (0, 0, 255)
            label = f"{face['name']} ({round(face['face_confidence'] * 100)}%)"
            
            cv2.rectangle(img_copy, (left, top), (right, bottom), color, 2)
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 2
            cv2.putText(img_copy, label, (left, top - 4), font, font_scale, color, thickness)
        
        return img_copy
    except Exception as e:
        logger.error(f"Error drawing bounding boxes: {e}")
        return image

def cleanup_old_images():
    """Remove images not referenced in DETECTION_HISTORY or older than RETENTION_DAYS"""
    try:
        files = glob.glob(os.path.join(app.config['OUTPUT_FOLDER'], '*'))
        current_time = time.time()
        retention_seconds = RETENTION_DAYS * 24 * 60 * 60
        
        referenced_images = {entry['image_path'].lstrip('/Output/') for entry in DETECTION_HISTORY 
                            if entry.get('image_path')}
        
        deleted_count = 0
        for file_path in files:
            try:
                filename = os.path.basename(file_path)
                file_mtime = os.path.getmtime(file_path)
                if (filename not in referenced_images) or (current_time - file_mtime > retention_seconds):
                    os.remove(file_path)
                    logger.info(f"Deleted image: {file_path}")
                    deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting image {file_path}: {e}")
        
        logger.info(f"Cleanup completed: {len(files)} files checked, {deleted_count} deleted")
    except Exception as e:
        logger.error(f"Error during image cleanup: {e}")

def start_cleanup_scheduler():
    """Start a background thread to run cleanup daily"""
    def run_cleanup():
        while True:
            try:
                cleanup_old_images()
            except Exception as e:
                logger.error(f"Error in cleanup scheduler: {e}")
            time.sleep(24 * 60 * 60)
            
    try:
        cleanup_thread = threading.Thread(target=run_cleanup, daemon=True)
        cleanup_thread.start()
        logger.info("Started image cleanup scheduler")
    except Exception as e:
        logger.error(f"Error starting cleanup scheduler: {e}")

@app.route('/')
def index():
    """Serve the main HTML page"""
    try:
        return send_from_directory('web', 'index.html')
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return jsonify({'error': 'Failed to serve page'}), 500

@app.route('/<path:path>')
def static_files(path):
    """Serve static files from web directory"""
    try:
        return send_from_directory('web', path)
    except Exception as e:
        logger.error(f"Error serving static file {path}: {e}")
        return jsonify({'error': 'File not found'}), 404

@app.route('/Output/<path:filename>')
def serve_uploads(filename):
    """Serve files from the output directory"""
    try:
        return send_from_directory(app.config['OUTPUT_FOLDER'], filename)
    except Exception as e:
        logger.error(f"Error serving uploaded file {filename}: {e}")
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/status', methods=['GET'])
def get_status():
    """Return server status information with retry logic for ESP32-CAM"""
    try:
        files = glob.glob(os.path.join(app.config['OUTPUT_FOLDER'], '*'))
        total_size = sum(os.path.getsize(f) for f in files) / (1024 * 1024)
        esp32_status = {'status': 'Offline', 'motion': False, 'buzzer': False, 'pir_connected': False, 'motion_count': 0}
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(f"{ESP32_CAM_URL}/", timeout=15)  # Increased timeout
                response.raise_for_status()
                data = response.json()
                esp32_status = {
                    'status': data.get('status', 'Offline'),
                    'motion': data.get('motion', False),
                    'buzzer': data.get('buzzer', False),
                    'pir_connected': data.get('pir_connected', False),
                    'motion_count': data.get('motion_count', 0)
                }
                logger.info(f"ESP32-CAM status check successful on attempt {attempt + 1}")
                break
            except requests.exceptions.RequestException as e:
                logger.warning(f"Retry {attempt + 1}/{max_retries} for ESP32-CAM status: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to check ESP32-CAM status after {max_retries} attempts: {e}")
                time.sleep(3 * (2 ** attempt))  # Increased backoff delay

        return jsonify({
            'status': 'Online',
            'version': '1.0.5',
            'models_loaded': {
                'face_detection': bool(yolo_model),
                'face_recognition': len(known_embeddings) > 0 and bool(svm_model) and bool(label_encoder),
                'mask_detection': os.path.exists('models/mask_model.keras'),
                'age_prediction': os.path.exists('models/age_model.keras'),
                'gender_prediction': os.path.exists('models/gender_model.keras')
            },
            'telegram_enabled': bool(os.getenv('TELEGRAM_BOT_TOKEN')),
            'esp32_status': esp32_status,
            'detection_count': len(DETECTION_HISTORY),
            'image_count': len(files),
            'total_image_size_mb': round(total_size, 2),
            'LAST_DETECTION': LAST_DETECTION  # Tambahkan deteksi terbaru
        })
    except Exception as e:
        logger.error(f"Error in get_status: {e}")
        return jsonify({'error': 'Failed to retrieve status'}), 500

@app.route('/api/process_image', methods=['POST'])
def process_image():
    """Process an image and return detection results including face recognition, mask, age, and gender"""
    start_time = time.time()
    
    try:
        if 'image' not in request.files:
            logger.error("No image part in the request")
            return jsonify({'error': 'No image part'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            logger.error("No selected file")
            return jsonify({'error': 'No selected file'}), 400
        
        if file and allowed_file(file.filename):
            img_bytes = file.read()
            img_array = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            if image is None:
                logger.error("Failed to decode image")
                return jsonify({'error': 'Failed to decode image'}), 400
            
            max_size = (800, 600)
            height, width = image.shape[:2]
            if width > max_size[0] or height > max_size[1]:
                scale = min(max_size[0] / width, max_size[1] / height)
                new_size = (int(width * scale), int(height * scale))
                image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
            
            face_locations = detect_faces(image, yolo_model)
            results = []
            unknown_count = 0
            sound_buzzer = False
            
            for face_location in face_locations:
                name, confidence = recognize_face(image, face_location, known_embeddings, known_labels, svm_model, label_encoder)
                if name == "Tidak Dikenal":
                    unknown_count += 1
                    name = f"Tidak Dikenal {unknown_count}"
                mask_result, mask_confidence = detect_mask(image, face_location)
                age_result = predict_age(image, face_location)
                gender_result, gender_confidence = predict_gender(image, face_location)
                
                result = {
                    'name': name,
                    'face_confidence': float(confidence),
                    'mask': mask_result,
                    'mask_confidence': float(mask_confidence),
                    'age': age_result,
                    'gender': gender_result,
                    'gender_confidence': float(gender_confidence),
                    'location': face_location
                }
                results.append(result)
                
                if name.startswith("Tidak Dikenal") and confidence < 0.90:
                    sound_buzzer = True
            
            processed_image = draw_bounding_boxes(image, results)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{secure_filename(file.filename)}"
            filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
            cv2.imwrite(filepath, processed_image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            logger.info(f"Saved processed image with bounding boxes: {filepath}")
            
            if len(results) > 0:
                try:
                    send_multiple_faces_notification(len(results), results, filepath)
                except Exception as e:
                    logger.error(f"Error sending Telegram notification: {e}")
            
            if results:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                detection_entry = {
                    'timestamp': timestamp,
                    'results': results,
                    'image_path': f"/Output/{filename}"
                }
                DETECTION_HISTORY.append(detection_entry)
                
                if len(DETECTION_HISTORY) > MAX_HISTORY:
                    removed_entry = DETECTION_HISTORY.pop(0)
                    image_path = removed_entry.get('image_path')
                    if image_path:
                        filepath = os.path.join(app.config['OUTPUT_FOLDER'], image_path.lstrip('/Output/'))
                        try:
                            if os.path.exists(filepath):
                                os.remove(filepath)
                                logger.info(f"Deleted image from trimmed history: {filepath}")
                        except Exception as e:
                            logger.error(f"Error deleting image {filepath}: {e}")
                
                global LAST_DETECTION
                LAST_DETECTION = detection_entry
            
            cleanup_old_images()
            
            response = {
                'timestamp': datetime.now().isoformat(),
                'faces_detected': len(results),
                'results': results,
                'sound_buzzer': sound_buzzer,
                'processing_time': time.time() - start_time,
                'image_path': f"/Output/{filename}"
            }
            
            logger.info(f"Processed image with {len(results)} faces. Buzzer: {sound_buzzer}")
            return jsonify(response)
        
        return jsonify({'error': 'Invalid file format'}), 400
    
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    """Return detection history sorted by timestamp (newest first)"""
    try:
        limit = request.args.get('limit', default=10, type=int)
        sorted_history = sorted(DETECTION_HISTORY, 
                              key=lambda x: datetime.strptime(x['timestamp'], '%Y-%m-%d %H:%M:%S'),
                              reverse=True)
        logger.info(f"Returning {min(limit, len(sorted_history))} history entries")
        return jsonify(sorted_history[:limit])
    except Exception as e:
        logger.error(f"Error retrieving history: {e}")
        return jsonify({'error': 'Failed to retrieve history'}), 500

@app.route('/api/test_telegram', methods=['GET'])
def test_telegram():
    """Send a test Telegram notification"""
    try:
        message = "🧪 This is a test notification from IoT CCTV"
        send_telegram_notification(message)
        return jsonify({'status': 'success', 'message': 'Tes Notifikasi Telegram Berhasil'})
    except Exception as e:
        logger.error(f"Error sending test Telegram notification: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/test_buzzer', methods=['GET'])
def test_buzzer():
    """Test the ESP32-CAM buzzer for 3 seconds"""
    try:
        response = requests.get(f"{ESP32_CAM_URL}/control?cmd=buzzer&duration=3000", timeout=15)
        response.raise_for_status()
        if response.text == "OK":
            return jsonify({'status': 'success', 'message': 'Buzzer Berhasil dinyalakan elama 3 detik'})
        else:
            raise Exception("ESP32-CAM buzzer test failed")
    except Exception as e:
        logger.error(f"Error testing buzzer: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {str(e)}")
    return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT'))
        debug = os.environ.get('DEBUG').lower() == 'true'
        logger.info(f"Starting IoT CCTV server on port {port}, debug={debug}")
        start_cleanup_scheduler()
        send_system_status_notification(True)
        app.run(host='0.0.0.0', port=port, debug=debug)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise