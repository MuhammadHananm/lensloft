#!/usr/bin/env python
"""WSGI entry point for Azure App Service"""

import sys
import logging

# Set up logging to help debug issues
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

try:
    logger.info("Starting Flask app initialization...")
    
    # Try importing all dependencies
    logger.info("Importing Flask...")
    from flask import Flask
    
    logger.info("Importing Flask extensions...")
    from flask_login import LoginManager
    from flask_sqlalchemy import SQLAlchemy
    
    logger.info("Importing werkzeug...")
    from werkzeug.security import generate_password_hash, check_password_hash
    
    logger.info("Importing models...")
    from models import db, User, Photo
    
    logger.info("Importing app...")
    from app import app as application
    
    logger.info("✓ Flask app initialized successfully!")
    
except ImportError as e:
    logger.error(f"✗ Import Error: {e}", exc_info=True)
    sys.exit(1)
except Exception as e:
    logger.error(f"✗ Initialization Error: {e}", exc_info=True)
    sys.exit(1)

if __name__ == '__main__':
    application.run()
