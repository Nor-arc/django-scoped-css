SECRET_KEY = "test"
DEBUG = True
INSTALLED_APPS = ["django.contrib.staticfiles", "scoped_css", "tests.testapp"]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]
STATIC_URL = "/static/"
USE_TZ = True
