from __future__ import annotations

import uuid
from django.db import models


class TileRun(models.Model):
    """Lightweight record of a per-tile pipeline run (collection or processing).

    Stores minimal provenance so we can summarize activity and link outputs/logs.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Tile in PPP_RRR (e.g., 094_076)
    tile = models.CharField(max_length=8, db_index=True)

    # Dates in YYYYMMDD strings
    start_date = models.CharField(max_length=8)
    end_date = models.CharField(max_length=8)

    # Mode and index params
    source = models.CharField(max_length=4, choices=[("fc", "FC"), ("sr", "SR")], default="fc")
    veg_index = models.CharField(max_length=8, null=True, blank=True)
    savi_L = models.FloatField(null=True, blank=True)

    # Controls
    span_years = models.IntegerField(default=10)
    window_start = models.CharField(max_length=4, null=True, blank=True)
    window_end = models.CharField(max_length=4, null=True, blank=True)
    sr_dir_start = models.CharField(max_length=512, null=True, blank=True)
    sr_dir_end = models.CharField(max_length=512, null=True, blank=True)
    omit_start_threshold = models.BooleanField(default=False)
    collect_logs = models.BooleanField(default=True)

    # Runtime status and outputs
    status = models.CharField(max_length=20, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    log_path = models.CharField(max_length=512, null=True, blank=True)
    dll_path = models.CharField(max_length=512, null=True, blank=True)
    dlj_path = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tile} {self.start_date}-{self.end_date} {self.source}/{self.veg_index or 'fpc'} ({self.status})"
