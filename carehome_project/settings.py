import os
from pathlib import Path

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-1oafo=nwgt9wp2d_6i@xyy6$i4mw7@_28&miy)hq#*yovo^=q0")
DEBUG = os.environ.get("DEBUG", "False") == "True"

ALLOWED_HOSTS = [  # Render URL
    'localhost',
    '127.0.0.1',
    'prestigecarehomemanagement-k5rs.onrender.com',
    'prestigesupportedliving.com', 'www.prestigesupportedliving.com'
]

CSRF_TRUSTED_ORIGINS = [
    'https://prestigecarehomemanagement-k5rs.onrender.com',
    'https://www.prestigesupportedliving.com',  # Bluehost frontend
    'https://prestigesupportedliving.com',
]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# CUSTOM USER
AUTH_USER_MODEL = 'core.CustomUser'

# LOGIN
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# APPS
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",  # NEW: Required for API access from frontend
    'core',
]

# MIDDLEWARE
MIDDLEWARE = [
    'whitenoise.middleware.WhiteNoiseMiddleware',
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # NEW: Must be above CommonMiddleware
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    'core.middleware.UpdateLastActiveMiddleware',
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# CORS (for frontend to access backend)
CORS_ALLOW_ALL_ORIGINS = True  # For testing — restrict later for security
# OR:
# CORS_ALLOWED_ORIGINS = [
#     "https://www.prestigesupportedliving.com",
#     "https://prestigesupportedliving.com"
# ]

ROOT_URLCONF = "carehome_project.urls"

# TEMPLATES
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        'DIRS': [
            os.path.join(BASE_DIR, 'core', 'core', 'templates'),  # Check this path
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                'django.template.context_processors.debug',
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# PASSWORD VALIDATION
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# TIME ZONE
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# STATIC FILES (IMPORTANT for Render)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "core/core/static",
    BASE_DIR / "core/static",
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # For collectstatic on Render

# MEDIA
MEDIA_URL = '/media/'
# MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_ROOT = '/opt/render/project/src/media'

# DEFAULT PK
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
