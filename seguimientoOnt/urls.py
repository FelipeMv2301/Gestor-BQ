from django.urls import path
from . import views

app_name = "seguimientoOnt"

urlpatterns = [
    path("", views.lista_ont, name="lista"),
    path("<int:pk>/", views.detalle_ont, name="detalle"),
    path("<int:pk>/editar/", views.editar_ont, name="editar"),
]
