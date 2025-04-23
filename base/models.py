# models.py
from django.db import models

class PaperSize(models.Model):
    name = models.CharField(max_length=50)
    width_mm = models.FloatField()
    height_mm = models.FloatField()
    
    def __str__(self):
        return f"{self.name} ({self.width_mm}mm × {self.height_mm}mm)"




class StickerLayout(models.Model):
    name = models.CharField(max_length=100, default="Untitled Layout")
    created_at = models.DateTimeField(auto_now_add=True)
    paper_size = models.ForeignKey(PaperSize, on_delete=models.CASCADE)
    sticker_width = models.FloatField()
    sticker_height = models.FloatField()
    margin_top = models.FloatField(default=10)
    margin_right = models.FloatField(default=10)
    margin_bottom = models.FloatField(default=10)
    margin_left = models.FloatField(default=10)
    horizontal_spacing = models.FloatField(default=2)
    vertical_spacing = models.FloatField(default=2)
    original_image = models.ImageField(upload_to='stickers/')
    layout_data = models.JSONField(null=True, blank=True)
    