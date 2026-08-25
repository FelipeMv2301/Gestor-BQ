from django.urls import path
from . import views

app_name = "envios"

urlpatterns = [
    path("", views.lista_envios, name="lista"),
    path("mis-envios/", views.mis_envios, name="mis_envios"),
    path("reporte/", views.reporte_form, name="reporte_form"),
    path("reporte/ver/", views.reporte_ver, name="reporte_ver"),
    path("reporte/excel/", views.reporte_xlsx, name="reporte_xlsx"),
    path("refrescar-estados/", views.refrescar_estados, name="refrescar_estados"),
    path("<int:pk>/", views.detalle_envio, name="detalle"),
    path("<int:pk>/refrescar-estado/", views.refrescar_estado_envio, name="refrescar_estado"),
    path("<int:pk>/estado/", views.cambiar_estado_envio, name="cambiar_estado"),
    path("<int:pk>/anular/", views.anular_envio, name="anular"),
    path("<int:pk>/editar/", views.editar_envio, name="editar"),
    path("<int:pk>/eliminar/", views.eliminar_envio, name="eliminar"),
    path("<int:pk>/documento/<str:tipo>/", views.descargar_documento, name="descargar_documento"),
    path("webhooks/chibra/estado/", views.webhook_estado_chibra, name="webhook_chibra_estado"),
]
