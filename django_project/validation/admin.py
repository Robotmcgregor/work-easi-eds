from django.contrib import admin
from .models import QCValidation, QCAuditLog


@admin.register(QCValidation)
class QCValidationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'tile_id',
        'qc_status',
        'confidence_score',
        'requires_field_visit',
        'reviewed_by',
        'created_at',
    )
    list_filter = (
        'qc_status',
        'confidence_score',
        'requires_field_visit',
        'priority_level',
        'created_at',
        'updated_at',
    )
    search_fields = (
        'id',
        'tile_id',
        'reviewed_by',
        'reviewer_comments',
    )
    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        ('Detection Reference', {
            'fields': ('nvms_detection_id', 'tile_id'),
        }),
        ('Validation Status', {
            'fields': (
                'qc_status',
                'priority_level',
                'confidence_score',
                'is_confirmed_clearing',
            ),
        }),
        ('Review Information', {
            'fields': (
                'reviewed_by',
                'reviewed_at',
                'requires_field_visit',
            ),
        }),
        ('Comments & Notes', {
            'fields': (
                'reviewer_comments',
                'validation_notes',
            ),
            'classes': ('wide',),
        }),
        ('Audit Information', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('nvms_detection_id').order_by('-created_at')


@admin.register(QCAuditLog)
class QCAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'qc_validation',
        'action',
        'changed_by',
        'changed_at',
    )
    list_filter = (
        'action',
        'changed_at',
    )
    search_fields = (
        'id',
        'qc_validation__id',
        'changed_by',
        'action',
    )
    readonly_fields = (
        'id',
        'qc_validation',
        'action',
        'old_value',
        'new_value',
        'changed_by',
        'changed_at',
        'ip_address',
    )
    fieldsets = (
        ('Change Information', {
            'fields': (
                'qc_validation',
                'action',
            ),
        }),
        ('Values', {
            'fields': (
                'old_value',
                'new_value',
            ),
            'classes': ('wide',),
        }),
        ('User & Metadata', {
            'fields': (
                'changed_by',
                'changed_at',
                'ip_address',
                'change_reason',
            ),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('qc_validation').order_by('-changed_at')
