from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render

from .models import TileRun


def _python_exe() -> str:
    return sys.executable


def _scripts_root() -> Path:
    # Path to the original processing scripts; do not modify scripts there.
    return Path(r"C:\Users\DCCEEW\code\work-easi-eds\scripts\easi-scripts\eds-processing")


def _derive_scene(tile: str) -> str:
    if "_" not in tile or len(tile) != 7:
        raise ValueError("Tile must be PPP_RRR e.g. '094_076'")
    p, r = tile.split("_")
    return f"p{p}r{r}"


@csrf_exempt
def collection_run(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    data = json.loads(request.body.decode("utf-8"))
    tile = data.get("tile")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not tile or not start_date or not end_date:
        return JsonResponse({"error": "tile, start_date, end_date required"}, status=400)

    # Record job
    run = TileRun.objects.create(
        tile=tile,
        start_date=start_date,
        end_date=end_date,
        source="sr",  # collection is SR acquisition by convention
        status="queued",
    )

    # Build command to call eds_lsat_collection (wrapper: use python and original script)
    pyexe = _python_exe()
    script = _scripts_root() / "easi_eds_master_processing_pipeline.py"
    # For collection, we trigger master pipeline minimally if desired; here we just record the request.
    # If you have a dedicated eds_lsat_collection.py, wire it similarly.

    # Respond immediately
    return JsonResponse({"id": str(run.id), "status": run.status})


@csrf_exempt
def processing_run(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    data = json.loads(request.body.decode("utf-8"))
    tile = data.get("tile")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    source = data.get("source", "fc")  # fc or sr
    veg_index = data.get("veg_index")  # ndvi/evi/savi/ndmi if sr
    savi_L = data.get("savi_L", 0.5)
    span_years = int(data.get("span_years", 10))
    window_start = data.get("window_start")
    window_end = data.get("window_end")
    sr_dir_start = data.get("sr_dir_start")
    sr_dir_end = data.get("sr_dir_end")
    omit_start_threshold = bool(data.get("omit_start_threshold", False))
    collect_logs = bool(data.get("collect_logs", True))
    out_root = data.get("out_root") or str(Path(r"C:\Users\DCCEEW\code\work-easi-eds") / "data" / "compat" / "files")

    if not tile or not start_date or not end_date:
        return JsonResponse({"error": "tile, start_date, end_date required"}, status=400)
    if source == "sr" and (not sr_dir_start or not sr_dir_end):
        return JsonResponse({"error": "sr_dir_start and sr_dir_end required for SR runs"}, status=400)

    run = TileRun.objects.create(
        tile=tile,
        start_date=start_date,
        end_date=end_date,
        source=source,
        veg_index=veg_index,
        savi_L=savi_L if veg_index == "savi" else None,
        span_years=span_years,
        window_start=window_start,
        window_end=window_end,
        sr_dir_start=sr_dir_start,
        sr_dir_end=sr_dir_end,
        omit_start_threshold=omit_start_threshold,
        collect_logs=collect_logs,
        status="queued",
    )

    # Build command to call master pipeline
    pyexe = _python_exe()
    master = _scripts_root() / "easi_eds_master_processing_pipeline.py"
    cmd = [
        pyexe,
        str(master),
        "--tile",
        tile,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--span-years",
        str(span_years),
        "--out-root",
        out_root,
    ]
    if window_start and window_end:
        cmd += ["--season-window", window_start, window_end]
    if collect_logs:
        cmd += ["--collect-logs"]
    if source == "fc":
        cmd += ["--timeseries-source", "fc"]
        if omit_start_threshold:
            cmd += ["--omit-fpc-start-threshold"]
    else:
        cmd += ["--timeseries-source", "sr", "--sr-dir-start", sr_dir_start, "--sr-dir-end", sr_dir_end]
        # Veg index routed by specific script today; future: add --veg-index to master and handle internally.
        # For now, master runs SR compat + legacy; the index selection occurs in dedicated runs if needed.

    # Launch subprocess in background; log to a file per run
    log_dir = Path(out_root) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"pipeline_{tile}_d{start_date}{end_date}_{run.id}.log"
    with open(log_file, "w", encoding="utf-8") as lf:
        lf.write("Command: " + " ".join(cmd) + "\n\n")
    # Start process
    proc = subprocess.Popen(cmd, stdout=open(log_file, "a", encoding="utf-8"), stderr=subprocess.STDOUT)
    run.status = "running"
    run.log_path = str(log_file)
    run.save(update_fields=["status", "log_path"])

    return JsonResponse({"id": str(run.id), "status": run.status})


def processing_status(request, run_id: str):
    try:
        run = TileRun.objects.get(id=run_id)
    except TileRun.DoesNotExist:
        return JsonResponse({"error": "run not found"}, status=404)
    # Return minimal status and log tail
    tail = ""
    if run.log_path and os.path.exists(run.log_path):
        try:
            with open(run.log_path, "r", encoding="utf-8") as f:
                content = f.read()
                tail = content[-4000:]
        except Exception:
            tail = ""
    return JsonResponse({
        "id": str(run.id),
        "status": run.status,
        "log_tail": tail,
        "dll": run.dll_path,
        "dlj": run.dlj_path,
    })
from django.views.generic import TemplateView, ListView
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.paginator import Paginator
from django.db.models import Q, Count
from catalog.models import LandsatTile
from runs.models import EDSRun, EDSResult
import json


@method_decorator(login_required, name='dispatch')
class HomeView(TemplateView):
    """Homepage view for EDS Admin Dashboard"""
    template_name = 'home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get statistics from models
        try:
            from catalog.models import LandsatTile
            from runs.models import EDSRun, EDSResult
            from detection.models import EDSDetection
            from validation.models import QCValidation
            from accounts.models import User
            
            context['stats'] = {
                'tiles': LandsatTile.objects.count(),
                'runs': EDSRun.objects.count(),
                'results': EDSResult.objects.count(),
                'detections': EDSDetection.objects.count(),
                'validations': QCValidation.objects.count(),
                'users': User.objects.count(),
            }
        except Exception as e:
            context['stats'] = {}
        
        context['page_title'] = 'EDS Admin Dashboard'
        return context


def processing_page(request):
    """Render the Processing form UI.

    This page provides the form to submit processing jobs and polls status.
    """
    return render(request, 'processing.html')


def collection_page(request):
    """Render the data collection (LS8/9 SR+FC) pipeline form UI.

    This page provides a form to run the tile-driven LS8/9 SR+FC pipeline
    (query + optional season filter + optional download) over selected tiles.
    """
    return render(request, 'collection.html')


@csrf_exempt
def import_tiles_from_shapefile(request):
    """Import or update Landsat tiles in DB from a shapefile.

    Body JSON:
      - shp_path: absolute path to a shapefile containing path,row and geometry

    Expected columns: path, row, geometry
    Creates or updates catalog.LandsatTile with tile_id=pPPP rRRR and bounds_geojson.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = {}
    shp_path = data.get("shp_path")
    if not shp_path:
        return JsonResponse({"error": "shp_path required"}, status=400)
    p = Path(shp_path).expanduser()
    if not p.exists():
        return JsonResponse({"error": f"shapefile not found: {p}"}, status=400)
    # Lazy import geopandas to avoid hard dependency if unused
    try:
        import geopandas as gpd  # type: ignore
    except Exception:
        return JsonResponse({"error": "geopandas not installed. Please install geopandas (and fiona, shapely, pyproj) in the Django venv."}, status=500)
    try:
        gdf = gpd.read_file(str(p))
    except Exception as e:
        return JsonResponse({"error": f"failed to read shapefile: {e}"}, status=400)
    required = {"path", "row"}
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        return JsonResponse({"error": f"missing required columns: {missing}"}, status=400)

    created, updated = 0, 0
    for _, r in gdf.iterrows():
        try:
            path_val = int(r["path"]) if not isinstance(r["path"], str) else int(r["path"]) 
            row_val = int(r["row"]) if not isinstance(r["row"], str) else int(r["row"]) 
        except Exception:
            # skip rows with invalid numbers
            continue
        tile_id = f"p{path_val:03d}r{row_val:03d}"
        # Serialize geometry to GeoJSON
        bounds_geojson = None
        try:
            if r.get("geometry") is not None:
                bounds_geojson = json.loads(gpd.GeoSeries([r["geometry"]]).to_json())
                # Convert to single feature geometry
                if isinstance(bounds_geojson, dict) and "features" in bounds_geojson:
                    geom = bounds_geojson["features"][0].get("geometry")
                    bounds_geojson = json.dumps(geom)
                else:
                    bounds_geojson = None
        except Exception:
            bounds_geojson = None

        obj, exists = None, False
        try:
            obj = LandsatTile.objects.get(tile_id=tile_id)
            exists = True
        except LandsatTile.DoesNotExist:
            obj = LandsatTile(tile_id=tile_id, path=path_val, row=row_val)

        # Update fields
        obj.path = path_val
        obj.row = row_val
        if bounds_geojson:
            obj.bounds_geojson = bounds_geojson
        # Default active status if not set
        if not getattr(obj, "is_active", True) is None:
            obj.is_active = True
        obj.status = getattr(obj, "status", "pending") or "pending"
        obj.save()
        if exists:
            updated += 1
        else:
            created += 1

    return JsonResponse({"created": created, "updated": updated})


@method_decorator(login_required, name='dispatch')
class TileMapView(TemplateView):
    """Interactive map view showing Landsat tile grid over Australia"""
    template_name = 'tile_map.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all tiles
        tiles = LandsatTile.objects.all()
        
        # Convert to GeoJSON for map
        features = []
        for tile in tiles:
            if tile.bounds_geojson:
                try:
                    bounds = json.loads(tile.bounds_geojson)
                    feature = {
                        "type": "Feature",
                        "properties": {
                            "tile_id": tile.tile_id,
                            "path": tile.path,
                            "row": tile.row,
                            "status": tile.status,
                            "is_active": tile.is_active,
                        },
                        "geometry": bounds
                    }
                    features.append(feature)
                except:
                    pass
        
        geojson_data = {
            "type": "FeatureCollection",
            "features": features
        }
        
        context['geojson_data'] = json.dumps(geojson_data)
        context['tiles_count'] = tiles.count()
        context['active_tiles'] = tiles.filter(is_active=True).count()
        
        return context
@method_decorator(login_required, name='dispatch')
class TilesListView(ListView):
    """All Tiles table view with filters and styling."""
    template_name = 'tiles_list.html'
    model = LandsatTile
    context_object_name = 'tiles'
    paginate_by = 25

    def get_queryset(self):
        qs = LandsatTile.objects.all().order_by('path', 'row')
        # filters
        status = self.request.GET.get('status')
        active = self.request.GET.get('active')
        search = self.request.GET.get('search')
        if status:
            qs = qs.filter(status__iexact=status)
        if active in ('true', 'false'):
            qs = qs.filter(is_active=(active == 'true'))
        if search:
            qs = qs.filter(
                Q(tile_id__icontains=search) |
                Q(path__icontains=search) |
                Q(row__icontains=search)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status'] = self.request.GET.get('status', '')
        ctx['active'] = self.request.GET.get('active', '')
        ctx['search'] = self.request.GET.get('search', '')
        return ctx


@method_decorator(login_required, name='dispatch')
class RunsListView(TemplateView):
    """List view for EDS Runs with filtering"""
    template_name = 'runs_list.html'
    paginate_by = 20
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter parameters
        search = self.request.GET.get('search', '')
        status_filter = self.request.GET.get('status', '')
        
        # Get runs queryset with deterministic ordering to ensure stable pagination
        # Use a valid field for ordering; prefer newest first by creation time
        runs = EDSRun.objects.all().order_by('-created_at')
        
        # Apply search filter
        if search:
            runs = runs.filter(
                Q(run_id__icontains=search) | 
                Q(description__icontains=search)
            )
        
        # Annotate with stats
        runs = runs.annotate(
            total_tiles=Count('edsresult_set'),
            total_detections=Count('edsdetection_set')
        )
        
        # Apply pagination
        paginator = Paginator(runs, self.paginate_by)
        page_number = self.request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        # Add stats to each run
        for run in page_obj:
            results = run.edsresult_set.all()
            run.cleared_total = sum(r.cleared or 0 for r in results)
            run.not_cleared_total = sum(r.not_cleared or 0 for r in results)
            run.detection_total = run.cleared_total + run.not_cleared_total
        
        context['page_obj'] = page_obj
        context['runs'] = page_obj.object_list
        context['search'] = search
        context['status_filter'] = status_filter
        context['total_runs'] = paginator.count
        
        return context


@method_decorator(login_required, name='dispatch')
class QCValidationsListView(ListView):
    """QC Validations dashboard - list all validations with filters and metrics."""
    template_name = 'qc_validations_list.html'
    context_object_name = 'validations'
    paginate_by = 50

    def get_queryset(self):
        from validation.models import QCValidation
        # Only select_related the ForeignKey field name (nvms_detection_id)
        qs = QCValidation.objects.select_related('nvms_detection_id').order_by('-reviewed_at')
        # filters
        status = self.request.GET.get('status')
        reviewer = self.request.GET.get('reviewer')
        tile = self.request.GET.get('tile')
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if status:
            qs = qs.filter(qc_status__iexact=status)
        if reviewer:
            qs = qs.filter(reviewed_by__icontains=reviewer)
        if tile:
            qs = qs.filter(tile_id__icontains=tile)
        if date_from:
            try:
                from datetime import datetime
                dt = datetime.strptime(date_from, '%Y-%m-%d')
                qs = qs.filter(reviewed_at__gte=dt)
            except Exception:
                pass
        if date_to:
            try:
                from datetime import datetime
                dt = datetime.strptime(date_to, '%Y-%m-%d')
                qs = qs.filter(reviewed_at__lte=dt)
            except Exception:
                pass
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from validation.models import QCValidation
        ctx['status'] = self.request.GET.get('status', '')
        ctx['reviewer'] = self.request.GET.get('reviewer', '')
        ctx['tile'] = self.request.GET.get('tile', '')
        ctx['date_from'] = self.request.GET.get('date_from', '')
        ctx['date_to'] = self.request.GET.get('date_to', '')
        # summary metrics
        ctx['total_validations'] = QCValidation.objects.count()
        ctx['confirmed'] = QCValidation.objects.filter(qc_status='confirmed').count()
        ctx['rejected'] = QCValidation.objects.filter(qc_status='rejected').count()
        ctx['requires_review'] = QCValidation.objects.filter(qc_status='requires_review').count()
        return ctx


@method_decorator(login_required, name='dispatch')
class QCReviewView(TemplateView):
    """QC Review page: map + detection details + form to submit validation."""
    template_name = 'qc_review.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from detection.models import EDSDetection
        from validation.models import QCValidation
        import json
        # Get unreviewed detections for dropdown
        # filter only to clearing detections (IsClearing='y')
        all_detections = EDSDetection.objects.exclude(
            id__in=QCValidation.objects.filter(
                qc_status__in=['confirmed', 'rejected']
            ).values_list('nvms_detection_id', flat=True)
        ).order_by('-imported_at')[:500]
        # filter to IsClearing='y' if properties field available (properties is TEXT, need to parse)
        unreviewed = []
        for d in all_detections:
            if d.properties:
                try:
                    props = json.loads(d.properties) if isinstance(d.properties, str) else d.properties
                    if props.get('IsClearing') == 'y':
                        unreviewed.append(d)
                except:
                    pass
        ctx['unreviewed_detections'] = unreviewed
        ctx['total_detections'] = len(unreviewed)
        return ctx


@csrf_exempt
def qc_submit_review(request):
    """API endpoint to submit a QC validation."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    detection_id = data.get("detection_id")
    reviewer = data.get("reviewer")
    decision = data.get("decision")  # confirmed, rejected, requires_review
    confidence = data.get("confidence", 3)
    comments = data.get("comments", "")
    if not detection_id or not reviewer or not decision:
        return JsonResponse({"error": "detection_id, reviewer, decision required"}, status=400)
    from detection.models import EDSDetection
    from validation.models import QCValidation
    from datetime import datetime
    try:
        det = EDSDetection.objects.get(id=detection_id)
    except EDSDetection.DoesNotExist:
        return JsonResponse({"error": "detection not found"}, status=404)
    # create or update validation
    # tile_id is CharField in QCValidation, get it from det.tile.tile_id
    tile_id_val = det.tile.tile_id if det.tile else None
    qc, created = QCValidation.objects.update_or_create(
        nvms_detection_id=det,
        defaults={
            'tile_id': tile_id_val,
            'qc_status': decision,
            'reviewed_by': reviewer,
            'reviewed_at': datetime.now(),
            'reviewer_comments': comments,
            'confidence_score': int(confidence),
            'is_confirmed_clearing': (decision == 'confirmed'),
        }
    )
    return JsonResponse({"id": str(qc.id), "status": qc.qc_status, "created": created})


@csrf_exempt
def run_pipeline_api(request):
    """
    API endpoint to trigger master EDS processing pipeline
    
    POST JSON body:
    {
        "tiles": ["p104r070", "p105r069"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31"
    }
    
    Response:
    {
        "status": "success|error|timeout",
        "returncode": <int>,
        "stdout": "<output>",
        "stderr": "<errors>",
        "timestamp": "2024-12-15T10:30:00.000000",
        "command": "<full command>"
    }
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    try:
        from .pipeline_executor import PipelineExecutor
        
        tiles = data.get('tiles')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        timeout = data.get('timeout', 3600)
        
        result = PipelineExecutor.run(
            tiles=tiles,
            start_date=start_date,
            end_date=end_date,
            timeout=timeout
        )
        
        return JsonResponse(result)
    
    except Exception as e:
        return JsonResponse(
            {"error": str(e), "status": "error"},
            status=500
        )

