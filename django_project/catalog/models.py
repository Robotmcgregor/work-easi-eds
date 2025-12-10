from django.db import models


class LandsatTile(models.Model):
    """Landsat tile catalog - represents geographic tiles across Australia"""
    
    id = models.AutoField(primary_key=True)
    tile_id = models.CharField(max_length=20, unique=True, db_index=True)
    path = models.IntegerField(db_index=True)
    row = models.IntegerField(db_index=True)
    center_lat = models.FloatField()
    center_lon = models.FloatField()
    bounds_geojson = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default='pending', db_index=True)
    last_processed = models.DateTimeField(blank=True, null=True, db_index=True)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processing_priority = models.IntegerField(default=5)
    is_active = models.BooleanField(default=True)
    processing_notes = models.TextField(blank=True, null=True)
    latest_landsat_date = models.DateTimeField(blank=True, null=True)
    data_quality_score = models.FloatField(blank=True, null=True)

    class Meta:
        db_table = 'landsat_tiles'
        managed = False  # Don't let Django create/modify this table
        ordering = ['path', 'row']

    def __str__(self):
        return f"Tile {self.tile_id} (P{self.path}R{self.row})"
