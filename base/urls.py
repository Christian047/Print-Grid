# urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Main index page for creating new layouts
    path('', views.index, name='index'),
    
    # API endpoint to detect sticker dimensions
    path('detect-sticker-size/', views.detect_sticker_size, name='detect_sticker_size'),
    
    # Calculate layout and redirect to editor
    path('calculate-layout/', views.calculate_layout, name='calculate_layout'),
    
    # Edit existing layout
    path('edit/<int:layout_id>/', views.edit_layout, name='edit_layout'),
    
    # Save layout changes
    path('save-layout/<int:layout_id>/', views.save_layout, name='save_layout'),
    
    # Download layout as PDF or PNG
    path('download/<int:layout_id>/', views.download_layout, name='download_layout'),
    
    # Create custom paper size
    path('create-custom-paper/', views.custom_paper_size, name='custom_paper_size'),
    
    # Calculate layout via AJAX (for preview)
    path('calculate-layout-ajax/', views.calculate_layout_ajax, name='calculate_layout_ajax'),
]