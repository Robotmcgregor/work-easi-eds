from django.contrib import admin
from .models import EDSDetection, DetectionAlert


@admin.register(EDSDetection)
class EDSDetectionAdmin(admin.ModelAdmin):
    list_display = ['id', 'run', 'tile', 'imported_at']
    list_filter = ['run', 'imported_at']
    search_fields = ['geom_hash', 'tile__tile_id']
    readonly_fields = ['imported_at', 'id']
    fieldsets = (
        ('Detection Info', {
            'fields': ('id', 'run', 'result', 'tile')
        }),
        ('Geometry', {
            'fields': ('geom_wkt', 'geom_geojson', 'geom_hash')
        }),
        ('Properties', {
            'fields': ('properties',)
        }),
        ('Metadata', {
            'fields': ('imported_at',),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('run', 'tile').order_by('-imported_at')


@admin.register(DetectionAlert)
class DetectionAlertAdmin(admin.ModelAdmin):
    list_display = ['alert_id', 'tile_id', 'confidence_score', 'is_verified', 'verification_status', 'detection_date']
    list_filter = ['is_verified', 'verification_status', 'severity', 'detection_date']
    search_fields = ['alert_id', 'tile_id', 'verified_by']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Alert Info', {
            'fields': ('alert_id', 'job_id', 'tile_id')
        }),
        ('Location', {
            'fields': ('detection_lat', 'detection_lon', 'detection_geojson')
        }),
        ('Detection Details', {
            'fields': ('detection_date', 'confidence_score', 'area_hectares', 'clearing_type', 'severity')
        }),
        ('Verification', {
            'fields': ('is_verified', 'verification_status', 'verified_by', 'verified_at', 'verification_notes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by('-detection_date')
