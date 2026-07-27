from django.urls import path
from . import views

urlpatterns = [
    path("inicio/", views.inicio, name="inicio"),
    path("panel/perfiles/", views.panel_perfiles, name="panel_perfiles"),
    path("panel/perfiles/<int:pk>/editar/", views.editar_perfil, name="editar_perfil"),
]