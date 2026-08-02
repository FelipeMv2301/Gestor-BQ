from django.urls import path
from . import views

app_name = "envios"

urlpatterns = [
    path("", views.lista_envios, name="lista"),
    path("mis-envios/", views.mis_envios, name="mis_envios"),
    path("refrescar-estados/", views.refrescar_estados, name="refrescar_estados"),
    path("<int:pk>/", views.detalle_envio, name="detalle"),
    path("<int:pk>/refrescar-estado/", views.refrescar_estado_envio, name="refrescar_estado"),
    path("<int:pk>/estado/", views.cambiar_estado_envio, name="cambiar_estado"),
    path("<int:pk>/editar/", views.editar_envio, name="editar"),
    path("<int:pk>/eliminar/", views.eliminar_envio, name="eliminar"),
]
