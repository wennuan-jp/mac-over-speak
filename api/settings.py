import os
from pathlib import Path

# A minimal Django configuration optimized for a standalone ASR service (no database required).
BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = 'django-insecure-asr-service-key'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'api',
]

MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'api.urls'

DATABASES = {} # No database needed for this simple service

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
