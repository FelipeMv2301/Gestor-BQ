from django.urls import path
from . import views

app_name = "cotizaciones"

urlpatterns = [
    path("", views.lista_cotizaciones, name="lista"),
    path("panel/sincronizar/", views.panel_sincronizar_cotizaciones, name="panel_sincronizar"),
    path("panel/facturacion/", views.panel_actualizar_facturacion, name="panel_facturacion"),
    path("eliminar/", views.eliminar_cotizaciones, name="eliminar"),
    path("eliminar-todas/", views.eliminar_todas_cotizaciones, name="eliminar_todas"),
    path("<int:pk>/", views.detalle_cotizacion, name="detalle"),
]