import logging
import sys
from pathlib import Path
from config import DATA_DIR

# Define log file path
LOG_FILE = DATA_DIR / "trade_journal.log"

def setup_logging():
    """Configures logging to both file and console."""
    logger = logging.getLogger("trade_journal")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(module)s:%(funcName)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File Handler (Audit Trail)
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Console Handler (Immediate Feedback)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

def disable_console_logging():
    """Removes the StreamHandler from the global logger to prevent UI disruption."""
    logger = logging.getLogger("trade_journal")
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)

def enable_console_logging():
    """Restores the StreamHandler to the global logger."""
    logger = logging.getLogger("trade_journal")
    # Check if console handler already exists
    if any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in logger.handlers):
        return
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(module)s:%(funcName)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

# Initialize the global logger instance
logger = setup_logging()

def log_system_milestone(message):
    """Special helper for logging major architectural changes."""
    logger.info(f"🚀 MILESTONE: {message}")
