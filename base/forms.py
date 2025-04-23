
# forms.py
from django import forms
from .models import PaperSize, SavedLayout

class LayoutGeneratorForm(forms.Form):
    # Paper settings
    paper_size = forms.ModelChoiceField(
        queryset=PaperSize.objects.all(),
        required=False,
        label="Paper Size"
    )
    custom_paper_width = forms.FloatField(
        required=False, 
        min_value=1,
        label="Custom Paper Width (mm)"
    )
    custom_paper_height = forms.FloatField(
        required=False,
        min_value=1, 
        label="Custom Paper Height (mm)"
    )
    
    # Sticker settings
    sticker_width = forms.FloatField(
        min_value=1,
        label="Sticker Width (mm)"
    )
    sticker_height = forms.FloatField(
        min_value=1,
        label="Sticker Height (mm)"
    )
    
    # Margin and spacing settings
    top_margin = forms.FloatField(
        min_value=0,
        initial=5,
        label="Top Margin (mm)"
    )
    bottom_margin = forms.FloatField(
        min_value=0,
        initial=5,
        label="Bottom Margin (mm)"
    )
    left_margin = forms.FloatField(
        min_value=0,
        initial=5,
        label="Left Margin (mm)"
    )
    right_margin = forms.FloatField(
        min_value=0,
        initial=5,
        label="Right Margin (mm)"
    )
    horizontal_spacing = forms.FloatField(
        min_value=0,
        initial=2,
        label="Horizontal Spacing Between Stickers (mm)"
    )
    vertical_spacing = forms.FloatField(
        min_value=0,
        initial=2,
        label="Vertical Spacing Between Stickers (mm)"
    )
    
    # Save settings
    save_layout = forms.BooleanField(
        required=False,
        initial=False,
        label="Save This Layout"
    )
    layout_name = forms.CharField(
        max_length=100,
        required=False,
        label="Layout Name"
    )
    
    def clean(self):
        cleaned_data = super().clean()
        paper_size = cleaned_data.get('paper_size')
        custom_paper_width = cleaned_data.get('custom_paper_width')
        custom_paper_height = cleaned_data.get('custom_paper_height')
        
        # Either a standard paper size or custom dimensions must be provided
        if not paper_size and (not custom_paper_width or not custom_paper_height):
            raise forms.ValidationError(
                "Please select a standard paper size or provide custom dimensions."
            )
            
        # If saving, a name must be provided
        save_layout = cleaned_data.get('save_layout')
        layout_name = cleaned_data.get('layout_name')
        if save_layout and not layout_name:
            raise forms.ValidationError(
                "Please provide a name for the saved layout."
            )
            
        return cleaned_data