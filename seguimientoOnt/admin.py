from django.contrib import admin
from .models import DespachoOnt


@admin.register(DespachoOnt)
class DespachoOntAdmin(admin.ModelAdmin):
    list_display = ("pedido", "accion", "fecha_compromiso", "fecha_despacho", "modificado_en")
    list_filter = ("accion",)
    search_fields = ("pedido__num_pedido", "guia_despacho")
