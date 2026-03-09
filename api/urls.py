from django.urls import path
from .views import transcribe_view, warmup_view, status_view

# Routes the /transcribe/ and /warmup/ endpoints.
urlpatterns = [
    path('transcribe/', transcribe_view, name='transcribe'),
    path('warmup/', warmup_view, name='warmup'),
    path('status/', status_view, name='status'),
]
