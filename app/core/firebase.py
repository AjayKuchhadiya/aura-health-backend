import firebase_admin
from firebase_admin import credentials, auth
import os

# Initialize Firebase Admin using the key you placed in root
if not firebase_admin._apps:
    cred_path = "serviceAccountKey.json"
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        print("Warning: serviceAccountKey.json not found. Firebase Auth will fail.")

def verify_id_token(token: str):
    """Verifies a Firebase ID token and returns the decoded token dict."""
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        print(f"Token verification failed: {e}")
        return None