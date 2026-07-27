from django.urls import path
from . import views

app_name = "ejecutivos"

urlpatterns = [
    path("panel/", views.panel_ejecutivos, name="panel"),
    path("panel/crear/", views.crear_ejecutivo, name="crear"),
    path("panel/<int:pk>/editar/", views.editar_ejecutivo, name="editar"),
    path("panel/sincronizar/", views.sincronizar_ejecutivos, name="sincronizar"),
    path("panel/<int:pk>/eliminar/", views.eliminar_ejecutivo, name="eliminar"),
]
