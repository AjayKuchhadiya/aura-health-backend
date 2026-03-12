import logging
import firebase_admin
from firebase_admin import credentials, auth
import os

logger = logging.getLogger(__name__)

# Initialize Firebase Admin using the key you placed in root
if not firebase_admin._apps:
    cred_path = os.getenv("FIREBASE_CREDENTIALS", "serviceAccountKey.json")
    if os.path.exists(cred_path):
        logger.info("Initialising Firebase Admin SDK from: %s", cred_path)
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialised successfully")
    else:
        logger.warning(
            "serviceAccountKey.json not found at '%s'. Firebase Auth will fail.",
            cred_path,
        )


def verify_id_token(token: str):
    """Verifies a Firebase ID token and returns the decoded token dict."""
    try:
        decoded_token = auth.verify_id_token(token)
        logger.debug("Firebase token verified for uid: %s", decoded_token.get("uid"))
        return decoded_token
    except Exception as e:
        logger.warning("Firebase token verification failed: %s", e)
        return None
