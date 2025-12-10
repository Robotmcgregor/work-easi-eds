from django.db import models
from runs.models import EDSRun, EDSResult
from catalog.models import LandsatTile


class EDSDetection(models.Model):
    """Individual detection geometries from EDS processing"""
    
    id = models.AutoField(primary_key=True)
    run = models.ForeignKey(EDSRun, on_delete=models.CASCADE, related_name='edsdetection_set')
    result = models.ForeignKey(EDSResult, on_delete=models.CASCADE, blank=True, null=True, related_name='detections')
    tile = models.ForeignKey(LandsatTile, on_delete=models.CASCADE, to_field='tile_id', blank=True, null=True)
    properties = models.TextField(blank=True, null=True)  # JSON properties
    geom_geojson = models.TextField(blank=True, null=True)  # GeoJSON geometry
    geom_wkt = models.TextField(blank=True, null=True)  # WKT geometry
    geom_hash = models.CharField(max_length=64, unique=True, blank=True, null=True, db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'eds_detections'
        managed = False
        ordering = ['-imported_at']
        indexes = [
            models.Index(fields=['geom_hash']),
            models.Index(fields=['run']),
            models.Index(fields=['tile']),
        ]

    def __str__(self):
        return f"Detection {self.id} - Run {self.run.run_id}"


class DetectionAlert(models.Model):
    """Detection alerts with verification status"""
    
    alert_id = models.CharField(max_length=255, unique=True)
    job_id = models.CharField(max_length=255)
    tile_id = models.CharField(max_length=20)
    detection_lat = models.FloatField()
    detection_lon = models.FloatField()
    detection_geojson = models.TextField(blank=True, null=True)
    detection_date = models.DateTimeField()
    confidence_score = models.FloatField()
    area_hectares = models.FloatField()
    clearing_type = models.CharField(max_length=100, blank=True, null=True)
    severity = models.CharField(max_length=50, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    verification_status = models.CharField(max_length=50, blank=True, null=True)
    verified_by = models.CharField(max_length=255, blank=True, null=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    verification_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'detection_alerts'
        managed = False
        ordering = ['-detection_date']

    def __str__(self):
        return f"Alert {self.alert_id}"
