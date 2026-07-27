from django.urls import path
from . import views

app_name = "pedidos"

urlpatterns = [
    path("mis-pedidos/", views.mis_pedidos, name="mis_pedidos"),
    path("<int:pk>/", views.detalle_pedido, name="detalle"),
    path("<int:pk>/cuerpo/", views.detalle_cuerpo, name="detalle_cuerpo"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/courier/", views.cambiar_courier, name="cambiar_courier"),
    path("<int:pk>/aprobar/", views.aprobar, name="aprobar"),
    path("<int:pk>/rechazar/", views.rechazar, name="rechazar"),
    path("anulados/", views.anulados, name="anulados"),
    path("anulados/<int:pk>/reingresar/", views.reingresar, name="reingresar"),
    path("avisos/campana/", views.avisos_campana, name="avisos_campana"),
    path("avisos/marcar-leidos/", views.marcar_avisos_leidos, name="marcar_avisos_leidos"),
    path("avisos/<int:pk>/leer/", views.marcar_aviso_leido, name="marcar_aviso_leido"),
    path("despachos/", views.tablero_logistica, name="despachos"),
    path("lote/aprobar/", views.aprobar_lote, name="aprobar_lote"),
    path("lote/notificar/", views.notificar_lote, name="notificar_lote"),
    path("lote/eliminar/", views.eliminar_lote, name="eliminar_lote"),
    path("armar-despacho/", views.armar_despacho, name="armar_despacho"),
    path("<int:pk>/notificar/", views.notificar, name="notificar"),
    path("panel/", views.panel_admin, name="panel_admin"),
    path("panel/sincronizar/", views.sincronizar, name="sincronizar"),
    path("panel/cargar/", views.cargar_individual, name="cargar_individual"),
    path("avisos/<int:pk>/descartar/", views.descartar_aviso, name="descartar_aviso"),
    path("panel/skus/", views.panel_skus, name="panel_skus"),
    path("panel/skus/crear/", views.crear_sku, name="crear_sku"),
    path("panel/skus/<int:pk>/editar/", views.editar_sku, name="editar_sku"),
    path("panel/skus/<int:pk>/eliminar/", views.eliminar_sku, name="eliminar_sku"),
]