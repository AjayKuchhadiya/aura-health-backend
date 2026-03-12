"""OCR service for document processing"""

import logging

logger = logging.getLogger(__name__)


class OCRService:
    """Service for optical character recognition"""

    @staticmethod
    async def process_document(file_path: str) -> dict:
        """Process document and extract text"""
        logger.info("process_document called — file_path: %s", file_path)
        # TODO: Implement OCR logic using Google Vision API
        pass
