from django.contrib import admin
from .models import EDSRun, EDSResult


@admin.register(EDSRun)
class EDSRunAdmin(admin.ModelAdmin):
    list_display = ['run_number', 'run_id', 'created_at']
    search_fields = ['run_id', 'description']
    readonly_fields = ['created_at', 'run_id']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by('-run_number')


@admin.register(EDSResult)
class EDSResultAdmin(admin.ModelAdmin):
    list_display = ['run', 'tile', 'analyst', 'cleared', 'not_cleared', 'created_at']
    list_filter = ['run', 'analyst', 'created_at']
    search_fields = ['tile__tile_id', 'analyst']
    readonly_fields = ['created_at']
    fieldsets = (
        ('Run & Tile', {
            'fields': ('run', 'tile')
        }),
        ('Analysis', {
            'fields': ('visual_check', 'analyst', 'comments')
        }),
        ('Results', {
            'fields': ('cleared', 'not_cleared', 'supplied_to_ceb')
        }),
        ('Date Range', {
            'fields': ('start_date', 'end_date', 'start_date_dt', 'end_date_dt')
        }),
        ('Metadata', {
            'fields': ('path', 'row', 'shp_path', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('run', 'tile').order_by('-created_at')
