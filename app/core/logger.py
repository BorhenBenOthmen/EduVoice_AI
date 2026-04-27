import logging
import sys
from app.core.config import LOG_LEVEL

logger = logging.getLogger("ARA_VOICE_CORE")

if not logger.handlers:
    logger.setLevel(getattr(logging, LOG_LEVEL))
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    file_handler = logging.FileHandler("ara_backend.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
