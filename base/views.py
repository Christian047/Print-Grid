# views.py - Updated with color mode conversion and automatic dimension handling

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import PaperSize, StickerLayout
from PIL import Image, ImageCms
import io
import json
import base64
import math
import os
import logging
import traceback
from django.contrib import messages
import tempfile
import logging
from django.http import HttpResponse, JsonResponse



logger = logging.getLogger(__name__)

def index(request):
    """Index page with form for creating a new layout"""
    # Check if paper sizes exist, create if needed
    if not PaperSize.objects.exists():
        # Define standard paper sizes
        paper_sizes = [
            {"name": "A4", "width_mm": 210, "height_mm": 297},
            {"name": "US Letter", "width_mm": 215.9, "height_mm": 279.4},
            {"name": "A3", "width_mm": 297, "height_mm": 420},    
            {"name": "A5", "width_mm": 148, "height_mm": 210},
            {"name": "A6", "width_mm": 105, "height_mm": 148},
            {"name": "B5", "width_mm": 176, "height_mm": 250},
            {"name": "Legal", "width_mm": 215.9, "height_mm": 355.6},
            {"name": "Tabloid", "width_mm": 279.4, "height_mm": 431.8},
            {"name": "4x6 Photo", "width_mm": 101.6, "height_mm": 152.4},
            {"name": "5x7 Photo", "width_mm": 127, "height_mm": 177.8},
            {"name": "Executive", "width_mm": 184.15, "height_mm": 266.7},
            {"name": "Index Card 3x5", "width_mm": 76.2, "height_mm": 127},
            {"name": "Index Card 4x6", "width_mm": 101.6, "height_mm": 152.4},
            {"name": "Index Card 5x8", "width_mm": 127, "height_mm": 203.2},
            {"name": "Statement", "width_mm": 139.7, "height_mm": 215.9},
            {"name": "Half Letter", "width_mm": 139.7, "height_mm": 215.9},
            {"name": "Postcard", "width_mm": 101.6, "height_mm": 152.4},
        ]
        
        # Create paper sizes
        for size in paper_sizes:
            PaperSize.objects.create(**size)
    
    # Get all paper sizes for the template
    paper_sizes = PaperSize.objects.all().order_by('name')
    recent_layouts = StickerLayout.objects.all().order_by('-created_at')[:5]
    
    return render(request, 'base/index2.html', {
        'paper_sizes': paper_sizes,
        'recent_layouts': recent_layouts
    })

@csrf_exempt
def detect_sticker_size(request):
    """API endpoint to detect sticker dimensions from uploaded image"""
    if request.method == 'POST' and request.FILES.get('sticker_image'):
        try:
            sticker_image = request.FILES['sticker_image']
            img = Image.open(sticker_image)
            width_px, height_px = img.size
            
            # Get image DPI if available, otherwise use default 72 DPI
            dpi_x, dpi_y = 72, 72
            if 'dpi' in img.info:
                dpi_x, dpi_y = img.info['dpi']
            
            # Convert to millimeters (25.4 mm = 1 inch)
            width_mm = (width_px / dpi_x) * 25.4
            height_mm = (height_px / dpi_y) * 25.4
            
            # Convert to inches
            width_inch = width_px / dpi_x
            height_inch = height_px / dpi_y
            
            # Get the color mode
            color_mode = img.mode
            
            # Generate a thumbnail
            img.thumbnail((150, 150))
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            thumbnail = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            # Calculate a safe printing size (slightly reduced to ensure proper printing)
            safe_width_mm = width_mm * 0.95
            safe_height_mm = height_mm * 0.95
            
            return JsonResponse({
                'success': True,
                'dimensions': {
                    'pixels': {
                        'width': width_px,
                        'height': height_px
                    },
                    'mm': {
                        'width': round(width_mm, 2),
                        'height': round(height_mm, 2)
                    },
                    'safe_mm': {
                        'width': round(safe_width_mm, 2),
                        'height': round(safe_height_mm, 2)
                    },
                    'inches': {
                        'width': round(width_inch, 2),
                        'height': round(height_inch, 2)
                    },
                    'dpi': {
                        'x': dpi_x,
                        'y': dpi_y
                    }
                },
                'color_mode': color_mode,
                'thumbnail': thumbnail
            })
        except Exception as e:
            logger.error(f"Error detecting sticker size: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'No image uploaded'}, status=400)





def calculate_layout(request):
    """Enhanced layout calculation with comprehensive error handling"""
    logger.info("Starting layout calculation process")
    
    if request.method != "POST":
        logger.warning("Non-POST request to calculate_layout")
        return redirect('index')
    
    try:
        # Check if custom paper size is provided
        use_custom_paper = request.POST.get('use_custom_paper', 'false') == 'true'
        logger.info(f"Custom paper size: {use_custom_paper}")
        
        if use_custom_paper:
            # Create custom paper size
            paper_width = float(request.POST.get('custom_paper_width'))
            paper_height = float(request.POST.get('custom_paper_height'))
            paper_name = f"Custom {paper_width}x{paper_height}mm"
            
            # Create or get the custom paper size
            paper_size, created = PaperSize.objects.get_or_create(
                name=paper_name,
                defaults={
                    'width_mm': paper_width,
                    'height_mm': paper_height
                }
            )
        else:
            # Use standard paper size
            paper_size_id = request.POST.get('paper_size')
            paper_size = PaperSize.objects.get(id=paper_size_id)
            
            paper_width = paper_size.width_mm
            paper_height = paper_size.height_mm
        
        # Get orientation and adjust dimensions if needed
        orientation = request.POST.get('paper_orientation', 'portrait')
        
        if orientation == 'landscape' and paper_width < paper_height:
            paper_width, paper_height = paper_height, paper_width
        
        # Get margins (in mm)
        margin_top = float(request.POST.get('margin_top', 10))
        margin_right = float(request.POST.get('margin_right', 10))
        margin_bottom = float(request.POST.get('margin_bottom', 10))
        margin_left = float(request.POST.get('margin_left', 10))
        
        # Check if custom sticker size is provided
        use_custom_sticker = request.POST.get('use_custom_sticker', 'false') == 'true'
        
        if use_custom_sticker:
            # Use custom dimensions
            sticker_width = float(request.POST.get('custom_sticker_width'))
            sticker_height = float(request.POST.get('custom_sticker_height'))
        else:
            # Use dimensions from form
            sticker_width = float(request.POST.get('sticker_width'))
            sticker_height = float(request.POST.get('sticker_height'))
        
        # Get spacing between stickers (in mm)
        horizontal_spacing = float(request.POST.get('horizontal_spacing', 2))
        vertical_spacing = float(request.POST.get('vertical_spacing', 2))
        
        # Calculate printable area dimensions
        printable_width = paper_width - margin_left - margin_right
        printable_height = paper_height - margin_top - margin_bottom
        
        # Calculate how many stickers can fit horizontally and vertically
        # stickers_per_row = math.floor((printable_width + horizontal_spacing - sticker_width) / (sticker_width + horizontal_spacing))
        # rows_per_page = math.floor((printable_height + vertical_spacing) / (sticker_height + vertical_spacing))
        
        
        
        stickers_per_row = math.floor(printable_width / (sticker_width + horizontal_spacing))
        rows_per_page = math.floor(printable_height / (sticker_height + vertical_spacing))
        
        # Calculate total stickers per page
        total_stickers = stickers_per_row * rows_per_page
        
        # Process the uploaded image
        sticker_image = request.FILES.get('sticker_image')
        if not sticker_image:
            messages.error(request, "No sticker image was uploaded.")
            logger.error("No sticker image uploaded")
            return redirect('index')
        
        # Get the color mode preference if available
        color_mode_preference = request.POST.get('color_mode', 'original')
        
        # Create layout record
        try:
            layout = StickerLayout.objects.create(
                name=request.POST.get('layout_name', 'New Layout'),
                paper_size=paper_size,
                margin_top=margin_top,
                margin_right=margin_right,
                margin_bottom=margin_bottom,
                margin_left=margin_left,
                sticker_width=sticker_width,
                sticker_height=sticker_height,
                horizontal_spacing=horizontal_spacing,
                vertical_spacing=vertical_spacing,
                original_image=sticker_image
            )
            logger.info(f"Layout created with ID {layout.id}")
        except Exception as create_error:
            logger.error(f"Layout creation failed: {create_error}")
            messages.error(request, f"Failed to create layout: {create_error}")
            return redirect('index')
        
        # Generate positions for all stickers
        positions = []
        for row in range(rows_per_page):
            for col in range(stickers_per_row):
                x = margin_left + col * (sticker_width + horizontal_spacing)
                y = margin_top + row * (sticker_height + vertical_spacing)
                positions.append({
                    'x': x,
                    'y': y,
                    'row': row,
                    'col': col,
                    'index': row * stickers_per_row + col
                })
        
        # Create comprehensive layout data
        layout_data = {
            'stickers_per_row': stickers_per_row,
            'rows_per_page': rows_per_page,
            'total_stickers': total_stickers,
            'positions': positions,
            'paper_width': paper_width,
            'paper_height': paper_height,
            'margins': {
                'top': margin_top,
                'right': margin_right,
                'bottom': margin_bottom,
                'left': margin_left
            },
            'sticker': {
                'width': sticker_width,
                'height': sticker_height
            },
            'spacing': {
                'horizontal': horizontal_spacing,
                'vertical': vertical_spacing
            },
            'color_mode': color_mode_preference
        }
        
        # Store the layout data
        layout.layout_data = layout_data
        layout.save()
        logger.info(f"Layout data saved for layout {layout.id}")
        
        # Process the image for base64
        try:
            with Image.open(layout.original_image.path) as img:
                # Get image current color mode
                original_color_mode = img.mode
                
                # Convert color mode if requested and different from original
                if color_mode_preference != 'original' and color_mode_preference != original_color_mode:
                    if color_mode_preference == 'CMYK' and original_color_mode != 'CMYK':
                        # Convert RGB to CMYK
                        if original_color_mode == 'RGB':
                            try:
                                # Use ImageCms for proper color conversion
                                rgb_profile = ImageCms.createProfile("sRGB")
                                cmyk_profile = ImageCms.createProfile("USWebCoatedSWOP")
                                img = ImageCms.profileToProfile(img, rgb_profile, cmyk_profile, outputMode='CMYK')
                                logger.info("Converted image from RGB to CMYK")
                            except Exception as e:
                                logger.error(f"Error converting to CMYK: {str(e)}")
                                # Fallback to simple conversion
                                img = img.convert('CMYK')
                    elif color_mode_preference == 'RGB' and original_color_mode != 'RGB':
                        # Convert CMYK to RGB
                        if original_color_mode == 'CMYK':
                            try:
                                cmyk_profile = ImageCms.createProfile("USWebCoatedSWOP")
                                rgb_profile = ImageCms.createProfile("sRGB")
                                img = ImageCms.profileToProfile(img, cmyk_profile, rgb_profile, outputMode='RGB')
                                logger.info("Converted image from CMYK to RGB")
                            except Exception as e:
                                logger.error(f"Error converting to RGB: {str(e)}")
                                # Fallback to simple conversion
                                img = img.convert('RGB')
                
                # Save to buffer for base64 encoding
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                logger.info(f"Image converted to base64, length: {len(image_base64)}")
        except Exception as image_error:
            logger.error(f"Image processing failed: {str(image_error)}")
            messages.error(request, "Failed to process image")
            return redirect('index')
        
        # Render template with context
        context = {
            'layout': layout,
            'layout_data_json': json.dumps(layout_data),
            'image_base64': image_base64,
            'paper_size': paper_size,
            'color_mode': color_mode_preference
        }
        
        logger.info("Rendering editor template with context")
        return render(request, 'base/editor.html', context)
    
    except Exception as global_error:
        # Catch-all error handling
        logger.error(f"Unhandled error in layout calculation: {global_error}")
        logger.error(traceback.format_exc())
        messages.error(request, f"An unexpected error occurred: {global_error}")
        return redirect('index')







def download_layout(request, layout_id):
    """Generate downloadable file for printing with color mode support"""
    layout = get_object_or_404(StickerLayout, id=layout_id)
    
    # Get requested format
    download_format = request.GET.get('format', 'pdf')
    
    # Get requested color mode (RGB/CMYK)
    color_mode = request.GET.get('color_mode', layout.layout_data.get('color_mode', 'original'))
    
    if download_format == 'pdf':
        return generate_pdf(layout, color_mode)
    elif download_format == 'png':
        return generate_png(layout, color_mode)
    else:
        return JsonResponse({
            'success': False, 
            'error': 'Unsupported format'
        }, status=400)
















def generate_pdf(layout, color_mode='original'):
    """Generate a PDF for printing stickers with color mode support"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader

        logger.info(f"[PDF] Starting PDF generation for layout: {layout.name}, ID: {layout.id}")
        logger.info(f"[PDF] Color mode requested: {color_mode}")
        logger.info(f"[PDF] Original image path: {layout.original_image.path}")

        buffer = io.BytesIO()

        width_mm = layout.layout_data['paper_width']
        height_mm = layout.layout_data['paper_height']
        width_pt = width_mm * 72 / 25.4
        height_pt = height_mm * 72 / 25.4
        logger.info(f"[PDF] Page size in mm: {width_mm} x {height_mm}")
        logger.info(f"[PDF] Page size in points: {width_pt} x {height_pt}")

        p = canvas.Canvas(buffer, pagesize=(width_pt, height_pt))

        # Open image
        logger.info("[PDF] Opening image...")
        with Image.open(layout.original_image.path) as img:
            logger.info(f"[PDF] Original image mode: {img.mode}")
            logger.info(f"[PDF] Image size: {img.size}")

            # Convert color mode if needed
            if color_mode != 'original' and color_mode not in (img.mode, 'original'):
                try:
                    logger.info(f"[PDF] Attempting color conversion to {color_mode}")
                    if color_mode == 'CMYK':
                        img = ImageCms.profileToProfile(
                            img,
                            ImageCms.createProfile("sRGB"),
                            ImageCms.createProfile("USWebCoatedSWOP"),
                            outputMode='CMYK'
                        )
                    elif color_mode == 'RGB':
                        img = ImageCms.profileToProfile(
                            img,
                            ImageCms.createProfile("USWebCoatedSWOP"),
                            ImageCms.createProfile("sRGB"),
                            outputMode='RGB'
                        )
                    logger.info(f"[PDF] Conversion successful. New mode: {img.mode}")
                except Exception as e:
                    logger.error(f"[PDF] Color mode conversion failed: {str(e)}")
                    img = img.convert(color_mode)
                    logger.info(f"[PDF] Fallback conversion used. New mode: {img.mode}")

            # Prepare image for ReportLab
            logger.info("[PDF] Saving image to in-memory PNG stream...")
            img_io = io.BytesIO()
            img.save(img_io, format='PNG')
            img_io.seek(0)
            rl_image = ImageReader(img_io)
            logger.info("[PDF] ImageReader ready.")

            # Draw stickers
            logger.info(f"[PDF] Drawing {len(layout.layout_data['positions'])} stickers...")
            for index, position in enumerate(layout.layout_data['positions']):
                x_pt = position['x'] * 72 / 25.4
                y_pt = height_pt - ((position['y'] + layout.sticker_height) * 72 / 25.4)
                logger.info(f"[PDF] Sticker {index+1}: x={position['x']}mm, y={position['y']}mm -> x_pt={x_pt}, y_pt={y_pt}")
                p.drawImage(rl_image, x_pt, y_pt,
                            width=layout.sticker_width * 72 / 25.4,
                            height=layout.sticker_height * 72 / 25.4,
                            preserveAspectRatio=True)

        p.save()
        buffer.seek(0)
        logger.info("[PDF] PDF generation completed successfully.")

        response = HttpResponse(buffer, content_type='application/pdf')
        suffix = f"_{color_mode.lower()}" if color_mode != 'original' else ""
        response['Content-Disposition'] = f'attachment; filename="{layout.name}{suffix}.pdf"'
        return response

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[PDF] Error generating PDF: {str(e)}\nTraceback:\n{tb}")
        return JsonResponse({'success': False, 'error': str(e)})


















def generate_png(layout, color_mode='original'):
    """Generate a PNG for the layout with color mode support"""
    try:
        # Open the original image
        with Image.open(layout.original_image.path) as img:
            # Convert color mode if needed
            if color_mode != 'original' and color_mode not in (img.mode, 'original'):
                if color_mode == 'CMYK' and img.mode != 'CMYK':
                    try:
                        rgb_profile = ImageCms.createProfile("sRGB")
                        cmyk_profile = ImageCms.createProfile("USWebCoatedSWOP")
                        img = ImageCms.profileToProfile(img, rgb_profile, cmyk_profile, outputMode='CMYK')
                    except Exception as e:
                        logger.error(f"Error converting to CMYK for PNG: {str(e)}")
                        img = img.convert('CMYK')
                elif color_mode == 'RGB' and img.mode != 'RGB':
                    try:
                        cmyk_profile = ImageCms.createProfile("USWebCoatedSWOP")
                        rgb_profile = ImageCms.createProfile("sRGB")
                        img = ImageCms.profileToProfile(img, cmyk_profile, rgb_profile, outputMode='RGB')
                    except Exception as e:
                        logger.error(f"Error converting to RGB for PNG: {str(e)}")
                        img = img.convert('RGB')
        
        # Create a PNG file for download
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='image/png')
        color_suffix = f"_{color_mode.lower()}" if color_mode != 'original' else ""
        response['Content-Disposition'] = f'attachment; filename="{layout.name}{color_suffix}.png"'
        
        return response
        
    except Exception as e:
        logger.error(f"Error generating PNG: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

def edit_layout(request, layout_id):
    """Edit an existing layout"""
    try:
        layout = get_object_or_404(StickerLayout, id=layout_id)
        
        # Convert image to base64 for display
        with open(layout.original_image.path, "rb") as image_file:
            image_base64 = base64.b64encode(image_file.read()).decode('utf-8')
        
        return render(request, 'base/editor.html', {
            'layout': layout,
            'layout_data_json': json.dumps(layout.layout_data),
            'image_base64': image_base64,
            'paper_size': layout.paper_size
        })
        
    except Exception as e:
        logger.error(f"Error editing layout: {str(e)}")
        return redirect('index')

@require_POST
def save_layout(request, layout_id):
    """Save updated layout positions"""
    try:
        layout = get_object_or_404(StickerLayout, id=layout_id)
        
        # Parse JSON data from request
        data = json.loads(request.body)
        positions = data.get('positions', [])
        
        # Update layout name if provided
        new_name = data.get('name')
        if new_name:
            layout.name = new_name
        
        # Update the layout data with new positions
        layout_data = layout.layout_data
        layout_data['positions'] = positions
        layout_data['total_stickers'] = len(positions)
        
        layout.layout_data = layout_data
        layout.save()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Error saving layout: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

def custom_paper_size(request):
    """Handle custom paper size creation"""
    if request.method == "POST":
        try:
            width_mm = float(request.POST.get('width_mm'))
            height_mm = float(request.POST.get('height_mm'))
            name = request.POST.get('name', f'Custom {width_mm}x{height_mm}mm')
            
            # Create the paper size
            paper_size = PaperSize.objects.create(
                name=name,
                width_mm=width_mm,
                height_mm=height_mm
            )
            
            return JsonResponse({
                'success': True, 
                'paper_size': {
                    'id': paper_size.id,
                    'name': paper_size.name,
                    'width_mm': paper_size.width_mm,
                    'height_mm': paper_size.height_mm
                }
            })
            
        except Exception as e:
            logger.error(f"Error creating custom paper size: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def calculate_layout_ajax(request):
    """Calculate layout without creating a record (for preview)"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            
            # Get paper dimensions
            paper_width = float(data.get('paper_width'))
            paper_height = float(data.get('paper_height'))
            
            # Get margins
            margin_top = float(data.get('margin_top', 10))
            margin_right = float(data.get('margin_right', 10))
            margin_bottom = float(data.get('margin_bottom', 10))
            margin_left = float(data.get('margin_left', 10))
            
            # Get sticker dimensions
            sticker_width = float(data.get('sticker_width'))
            sticker_height = float(data.get('sticker_height'))
            
            # Get spacing
            horizontal_spacing = float(data.get('horizontal_spacing', 2))
            vertical_spacing = float(data.get('vertical_spacing', 2))
            
            # Calculate printable area
            printable_width = paper_width - margin_left - margin_right
            printable_height = paper_height - margin_top - margin_bottom
            
            # Calculate how many stickers can fit
            stickers_per_row = math.floor((printable_width + horizontal_spacing) / (sticker_width + horizontal_spacing))
            rows_per_page = math.floor((printable_height + vertical_spacing) / (sticker_height + vertical_spacing))
            
            # Calculate total stickers per page
            total_stickers = stickers_per_row * rows_per_page
            
            # Generate positions
            positions = []
            for row in range(rows_per_page):
                for col in range(stickers_per_row):
                    x = margin_left + col * (sticker_width + horizontal_spacing)
                    y = margin_top + row * (sticker_height + vertical_spacing)
                    positions.append({
                        'x': x,
                        'y': y,
                        'row': row,
                        'col': col,
                        'index': row * stickers_per_row + col
                    })
            
            # Return the layout data
            return JsonResponse({
                'success': True,
                'layout': {
                    'stickers_per_row': stickers_per_row,
                    'rows_per_page': rows_per_page,
                    'total_stickers': total_stickers,
                    'positions': positions,
                    'paper_width': paper_width,
                    'paper_height': paper_height
                }
            })
            
        except Exception as e:
            logger.error(f"Error calculating layout: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})