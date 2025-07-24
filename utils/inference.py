import cv2
import numpy as np
from ultralytics import YOLO
from deepface import DeepFace
from sklearn.metrics.pairwise import cosine_similarity
import keras
from keras.models import load_model
import os
import logging
import joblib

# Configure logging
logger = logging.getLogger(__name__)

# Initialize YOLOv8 model
try:
    yolo_model = YOLO("models/yolov8n-face.pt")
    logger.info("YOLOv8 model initialized successfully")
except Exception as e:
    logger.error(f"Error initializing YOLOv8 model: {e}")
    yolo_model = None

# Load DeepFace model components
try:
    known_embeddings = joblib.load('models/known_embeddings.pkl')
    known_labels = joblib.load('models/known_labels.pkl')
    label_encoder = joblib.load('models/label_encoder.pkl')
    svm_model = joblib.load('models/svm_model.pkl')
    logger.info("DeepFace model components loaded successfully")
except Exception as e:
    logger.error(f"Error loading DeepFace model components: {e}")
    known_embeddings = []
    known_labels = []
    label_encoder = None
    svm_model = None

# Load models for mask, age, and gender detection
try:
    mask_model = load_model('models/mask_model.keras')
    logger.info("Mask detection model loaded successfully")
except Exception as e:
    logger.error(f"Error loading mask detection model: {e}")
    mask_model = None

try:
    age_model = load_model('models/age_model.keras')
    logger.info("Age prediction model loaded successfully")
except Exception as e:
    logger.error(f"Error loading age prediction model: {e}")
    age_model = None

try:
    gender_model = load_model('models/gender_model.keras')
    logger.info("Gender prediction model loaded successfully")
except Exception as e:
    logger.error(f"Error loading gender prediction model: {e}")
    gender_model = None

def detect_faces(image, yolo_model):
    if yolo_model is None:
        logger.error("YOLOv8 model not initialized")
        return []
    try:
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = yolo_model(rgb_image)
        face_locations = []
        for r in results:
            for box in r.boxes:
                cls = int(box.cls[0])
                if cls == 0:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    face_locations.append((y1, x2, y2, x1))
        logger.info(f"Detected {len(face_locations)} faces")
        return face_locations
    except Exception as e:
        logger.error(f"Error detecting faces: {e}")
        return []

def recognize_face(image, face_location, known_embeddings, known_labels, svm_model, label_encoder, threshold=0.85):
    if not known_embeddings or not known_labels:
        logger.error("DeepFace model components not initialized")
        return "Error", 0.0
    try:
        top, right, bottom, left = face_location
        face = image[top:bottom, left:right]
        if face.size == 0:
            logger.warning("Empty face crop detected")
            return "Tidak Dikenal", 0.0
        face_rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        embedding = DeepFace.represent(face_rgb, model_name='Facenet512', enforce_detection=False)[0]["embedding"]
        sims = cosine_similarity([embedding], known_embeddings)[0]
        best_idx = np.argmax(sims)
        best_score = sims[best_idx]
        label = known_labels[best_idx] if best_score >= threshold else "Tidak Dikenal"
        confidence = max(0.0, min(1.0, float(best_score)))
        logger.info(f"Recognized face: {label} with similarity {confidence:.2f}")
        return label, confidence
    except Exception as e:
        logger.error(f"Error recognizing face: {e}")
        return "Error", 0.0

def detect_mask(image, face_location):
    try:
        if mask_model is None:
            return "No model", 0.0
        top, right, bottom, left = face_location
        face = image[top:bottom, left:right]
        if face.shape[0] < 20 or face.shape[1] < 20:
            return "Unknown", 0.0
        face = cv2.resize(face, (224, 224))
        face = keras.applications.mobilenet_v2.preprocess_input(face)
        face = np.expand_dims(face, axis=0)
        mask_pred = mask_model.predict(face, verbose=0)[0][0]
        if mask_pred > 0.5:
            return "Tidak", float(mask_pred)
        else:
            return "Pakai", float(1 - mask_pred)
    except Exception as e:
        logger.error(f"Error detecting mask: {e}")
        return "Error", 0.0

def preprocess_face(face):
    face = cv2.resize(face, (160, 160))
    face = face.astype('float32') / 255.0
    return np.expand_dims(face, axis=0)

def predict_age(image, face_location):
    try:
        if age_model is None:
            return "Unknown Age"
        top, right, bottom, left = face_location
        face = image[top:bottom, left:right]
        if face.shape[0] < 20 or face.shape[1] < 20:
            return "Unknown Age"
        face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        face = preprocess_face(face)
        age_pred = age_model.predict(face, verbose=0)[0][0]
        predicted_age = round(float(age_pred))
        if predicted_age < 0 or predicted_age > 120:
            logger.warning(f"Invalid age prediction: {predicted_age}")
            return "Unknown Age"
        return predicted_age
    except Exception as e:
        logger.error(f"Error predicting age: {e}")
        return "Unknown Age"

def predict_gender(image, face_location):
    try:
        if gender_model is None:
            return "No model", 0.0
        top, right, bottom, left = face_location
        face = image[top:bottom, left:right]
        if face.shape[0] < 20 or face.shape[1] < 20:
            return "Unknown", 0.0
        face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        face = preprocess_face(face)
        gender_pred = gender_model.predict(face, verbose=0)[0][0]
        if gender_pred < 0.6:
            return "Pria", float(1 - gender_pred)
        else:
            return "Wanita", float(gender_pred)
    except Exception as e:
        logger.error(f"Error predicting gender: {e}")
        return "Error", 0.0
