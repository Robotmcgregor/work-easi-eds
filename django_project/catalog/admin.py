from django.contrib import admin
from .models import LandsatTile


@admin.register(LandsatTile)
class LandsatTileAdmin(admin.ModelAdmin):
    list_display = ['tile_id', 'path', 'row', 'status', 'is_active', 'data_quality_score', 'last_processed']
    list_filter = ['status', 'is_active', 'processing_priority', 'created_at']
    search_fields = ['tile_id']
    readonly_fields = ['created_at', 'last_updated', 'id']
    fieldsets = (
        ('Tile Information', {
            'fields': ('tile_id', 'path', 'row', 'center_lat', 'center_lon')
        }),
        ('Status', {
            'fields': ('status', 'is_active', 'processing_priority')
        }),
        ('Processing', {
            'fields': ('last_processed', 'latest_landsat_date', 'data_quality_score', 'processing_notes')
        }),
        ('Geometry', {
            'fields': ('bounds_geojson',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'last_updated', 'id'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by('path', 'row')
