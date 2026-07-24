from django.urls import path
from . import views

app_name = "pedidos"

urlpatterns = [
    path("mis-pedidos/", views.mis_pedidos, name="mis_pedidos"),
    path("<int:pk>/", views.detalle_pedido, name="detalle"),
    path("<int:pk>/cuerpo/", views.detalle_cuerpo, name="detalle_cuerpo"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/aprobar/", views.aprobar, name="aprobar"),
    path("<int:pk>/rechazar/", views.rechazar, name="rechazar"),
    path("anulados/", views.anulados, name="anulados"),
    path("anulados/<int:pk>/reingresar/", views.reingresar, name="reingresar"),
    path("avisos/campana/", views.avisos_campana, name="avisos_campana"),
    path("avisos/marcar-leidos/", views.marcar_avisos_leidos, name="marcar_avisos_leidos"),
    path("avisos/<int:pk>/leer/", views.marcar_aviso_leido, name="marcar_aviso_leido"),
    path("despachos/", views.tablero_logistica, name="despachos"),
    path("<int:pk>/notificar/", views.notificar, name="notificar"),
]