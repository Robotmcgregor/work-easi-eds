from django.db import models
from detection.models import EDSDetection


class QCValidation(models.Model):
    """Quality Control validation records for detections"""
    
    QC_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
        ('requires_review', 'Requires Review'),
    ]
    
    CONFIDENCE_CHOICES = [
        (1, '⭐ Very Low'),
        (2, '⭐⭐ Low'),
        (3, '⭐⭐⭐ Medium'),
        (4, '⭐⭐⭐⭐ High'),
        (5, '⭐⭐⭐⭐⭐ Very High'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    id = models.AutoField(primary_key=True)
    nvms_detection_id = models.ForeignKey(EDSDetection, on_delete=models.CASCADE, to_field='id', db_column='nvms_detection_id')
    tile_id = models.CharField(max_length=20, db_index=True)
    qc_status = models.CharField(max_length=20, choices=QC_STATUS_CHOICES, default='pending', db_index=True)
    reviewed_by = models.CharField(max_length=255, blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    is_confirmed_clearing = models.BooleanField(null=True, blank=True)
    confidence_score = models.IntegerField(choices=CONFIDENCE_CHOICES, blank=True, null=True)
    reviewer_comments = models.TextField(blank=True, null=True)
    validation_notes = models.TextField(blank=True, null=True)
    requires_field_visit = models.BooleanField(default=False)
    priority_level = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'qc_validations'
        managed = False
        ordering = ['-created_at']

    def __str__(self):
        return f"QC {self.id} - Tile {self.tile_id} ({self.qc_status})"

    def mark_confirmed(self, confirmed=True):
        """Mark detection as confirmed clearing"""
        self.is_confirmed_clearing = confirmed
        self.qc_status = 'confirmed' if confirmed else 'rejected'
        self.save()


class QCAuditLog(models.Model):
    """Audit log for QC validation changes"""
    
    id = models.AutoField(primary_key=True)
    qc_validation = models.ForeignKey(QCValidation, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=50)
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)
    changed_by = models.CharField(max_length=255)
    changed_at = models.DateTimeField(auto_now_add=True)
    change_reason = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    class Meta:
        db_table = 'qc_audit_log'
        managed = False
        ordering = ['-changed_at']

    def __str__(self):
        return f"Audit {self.id}: {self.action} on QC {self.qc_validation.id}"
