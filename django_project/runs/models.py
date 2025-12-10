from django.db import models
from catalog.models import LandsatTile


class EDSRun(models.Model):
    """EDS processing run (Run01, Run02, Run03)"""
    
    run_id = models.CharField(max_length=20, primary_key=True)
    run_number = models.IntegerField(unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'eds_runs'
        managed = False
        ordering = ['-run_number']

    def __str__(self):
        return f"Run {self.run_number}: {self.run_id}"

    def get_stats(self):
        """Get statistics for this run"""
        results = self.edsresult_set.all()
        detections = self.edsdetection_set.all()
        return {
            'total_tiles': results.count(),
            'total_detections': detections.count(),
            'total_cleared': sum(r.cleared for r in results),
            'total_not_cleared': sum(r.not_cleared for r in results),
        }


class EDSResult(models.Model):
    """Processing results for each tile in a run"""
    
    id = models.AutoField(primary_key=True)
    run = models.ForeignKey(EDSRun, on_delete=models.CASCADE, related_name='edsresult_set')
    tile = models.ForeignKey(LandsatTile, on_delete=models.CASCADE, to_field='tile_id')
    visual_check = models.CharField(max_length=50, blank=True, null=True)
    analyst = models.CharField(max_length=10, blank=True, null=True)
    comments = models.TextField(blank=True, null=True)
    shp_path = models.TextField(blank=True, null=True)
    cleared = models.IntegerField(default=0)
    not_cleared = models.IntegerField(default=0)
    supplied_to_ceb = models.CharField(max_length=10, blank=True, null=True)
    start_date = models.CharField(max_length=8, blank=True, null=True)
    end_date = models.CharField(max_length=8, blank=True, null=True)
    start_date_dt = models.DateTimeField(blank=True, null=True)
    end_date_dt = models.DateTimeField(blank=True, null=True)
    path = models.IntegerField()
    row = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'eds_results'
        managed = False
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.run.run_id} - Tile {self.tile.tile_id}"

    def total_detections(self):
        return self.cleared + self.not_cleared
