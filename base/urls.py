# urls.py
from django.urls import path

from . import views

urlpatterns = [
    # Upload form
    path('', views.index, name='index'),

    # Read size / DPI from an uploaded image
    path('detect-sticker-size/', views.detect_sticker_size, name='detect_sticker_size'),

    # Live numbers while the customer adjusts things (JSON, nothing is saved)
    path('quote/', views.quote, name='quote'),

    # Create the job, then redirect to its result page
    path('calculate-layout/', views.calculate_layout, name='calculate_layout'),

    # Result page and its sheet pictures - reached only by the job's secret token
    path('result/<uuid:token>/', views.result, name='result'),
    path('result/<uuid:token>/sheet/<int:sheet_no>.png', views.sheet_image, name='sheet_image'),

    # Add, edit, resize or remove designs on an already-calculated job, reusing
    # the same create-job page (recomputes and saves in place)
    path('job/<uuid:token>/edit/', views.job_edit, name='job_edit'),

    # Download PDF (all sheets) or one sheet as PNG:  ?format=pdf  |  ?format=png&sheet=2&dpi=300
    path('download/<uuid:token>/', views.download_layout, name='download_layout'),
]
