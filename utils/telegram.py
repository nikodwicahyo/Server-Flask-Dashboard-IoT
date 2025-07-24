import os
import requests
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

def send_telegram_notification(message, image_path=None):
    """
    Send a notification message to Telegram
    
    Args:
        message: Text message to send
        image_path: Optional path to an image file to send
        
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        logger.error("Telegram credentials not found in environment variables")
        return False
    
    try:
        base_url = f"https://api.telegram.org/bot{token}/"
        
        if image_path and os.path.exists(image_path):
            # Send photo with caption
            with open(image_path, 'rb') as photo:
                response = requests.post(
                    f"{base_url}sendPhoto",
                    data={'chat_id': chat_id, 'caption': message, 'parse_mode': 'HTML'},
                    files={'photo': photo}
                )
        else:
            # Send text message
            response = requests.post(
                f"{base_url}sendMessage",
                data={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}
            )
        
        if response.status_code == 200:
            logger.info("Notifikasi Telegram berhasil terkirim")
            return True
        else:
            logger.error(f"Gagal mengirim notifikasi Telegram: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error saat mengirim notifikasi Telegram: {e}")
        return False

def send_multiple_faces_notification(face_count, faces, image_path=None):
    """
    Send a notification when multiple faces are detected with detailed face info
    
    Args:
        face_count: Number of faces detected
        faces: List of face detection results
        JR    image_path: Optional path to an image file to send
        
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    message = f"👥 People detected: {face_count} faces in frame\n\n"
    for i, face in enumerate(faces, 1):
        message += f"<b>Wajah {i}</b>\n"
        message += f"Wajah : {face['name']}\n"
        message += f"Usia : {face['age'] if face['age'] != 'Unknown Age' else '-'}\n"
        message += f"Gender : {face['gender'] or '-'}\n"
        message += f"Masker : {face['mask']}\n"
        message += f"Keyakinan : {round(face['face_confidence'] * 100)}%\n\n"
    message += f"Waktu : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return send_telegram_notification(message, image_path)

def send_system_status_notification(is_online=True):
    """
    Send a system status notification
    
    Args:
        is_online: Whether the system is online
        
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    if is_online:
        message = "✅ IoT CCTV System is ONLINE"
    else:
        message = "❌ IoT CCTV System is OFFLINE"
    
    return send_telegram_notification(message)