from django.contrib import admin
from .models import PaperSize, StickerLayout

# Register your models here.





@admin.register(PaperSize)
class PaperSizeAdmin(admin.ModelAdmin):
    list_display = ("height_mm", "width_mm", "name")


@admin.register(StickerLayout)
class StickerLayoutAdmin(admin.ModelAdmin):
    list_display = ("layout_data", "original_image", "vertical_spacing", "horizontal_spacing", "margin_left", "margin_bottom", "margin_right", "margin_top", "sticker_height", "sticker_width", "paper_size", "created_at", "name")
