"""R2/S3 storage service for file uploads"""

import logging
import boto3
from app.core.config import settings

logger = logging.getLogger(__name__)


class R2StorageService:
    """Service for handling R2/S3 file uploads"""

    def __init__(self):
        logger.info("Initialising R2StorageService")
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        logger.info(
            "R2StorageService initialised for bucket: %s", settings.AWS_S3_BUCKET_NAME
        )

    async def upload_file(self, file_path: str, object_name: str) -> str:
        """Upload file to R2/S3"""
        logger.info(
            "upload_file called — file_path: %s, object_name: %s",
            file_path,
            object_name,
        )
        # TODO: Implement file upload logic
        pass

    async def delete_file(self, object_name: str) -> bool:
        """Delete file from R2/S3"""
        logger.info("delete_file called — object_name: %s", object_name)
        # TODO: Implement file deletion logic
        pass

    async def get_file_url(self, object_name: str) -> str:
        """Get public URL for file"""
        logger.debug("get_file_url called — object_name: %s", object_name)
        # TODO: Implement URL generation logic
        pass
