"""
Django settings for fare_pricing — 多航段运价组合培训系统。

培训沙箱：只保存虚构航班 / 舱位 / 规则数据，不连接任何真实订座或出票系统。
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'training-sandbox-insecure-key-not-for-production'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'rest_framework',
    'pricing',
]

MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
]

ROOT_URLCONF = 'fare_pricing.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'frontend' / 'dist'],
        'APP_DIRS': False,
        'OPTIONS': {'context_processors': []},
    },
]

WSGI_APPLICATION = 'fare_pricing.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'farebook',
        'USER': 'fareuser',
        'PASSWORD': '',
        'HOST': '/tmp',
        'PORT': '55432',
    }
}

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'frontend' / 'dist' / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'UNAUTHENTICATED_USER': None,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

# 培训系统常量（沙箱）
MIN_TRANSFER_MINUTES = 40      # 最短转机衔接时间（示例值）
MAX_TRANSFER_MINUTES = 24 * 60  # 小于 24 小时才算转机
STOPOVER_MINUTES = 24 * 60      # 达到 24 小时即为停留
