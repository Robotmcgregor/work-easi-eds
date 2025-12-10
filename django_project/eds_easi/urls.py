"""Root URL configuration for eds_easi project.

This file defines:
- Core site pages: home, tile map, runs list
- Processing UI and API endpoints for launching and monitoring jobs
- Admin and static/media serving in development
"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from . import views

urlpatterns = [
    # Core site pages
    path('', views.HomeView.as_view(), name='home'),
    path('tiles/map/', views.TileMapView.as_view(), name='tile_map'),
    path('tiles/all/', views.TilesListView.as_view(), name='tiles_list'),
    path('runs/', views.RunsListView.as_view(), name='runs_list'),

    # Processing page UI
    path('processing/', views.processing_page, name='processing_page'),
    # Data management: collection pipeline UI
    path('data/collection/', views.collection_page, name='collection_page'),
    # Data management APIs
    path('api/data/tiles/import', views.import_tiles_from_shapefile, name='import_tiles_from_shapefile'),

    # QC Validation pages
    path('qc/validations/', views.QCValidationsListView.as_view(), name='qc_validations_list'),
    path('qc/review/', views.QCReviewView.as_view(), name='qc_review'),
    path('api/qc/submit', views.qc_submit_review, name='qc_submit_review'),

    # Processing & collection APIs
    path('api/collection/run', views.collection_run, name='collection_run'),
    path('api/processing/run', views.processing_run, name='processing_run'),
    path('api/processing/status/<uuid:run_id>', views.processing_status, name='processing_status'),

    # Admin
    path('admin/', admin.site.urls),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
