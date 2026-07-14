from django.contrib import admin
from .models import PedidoRechazado

# Register your models here.
@admin.register(PedidoRechazado)
class PedidoRechazadoAdmin(admin.ModelAdmin):
    list_display = ("num_pedido", "motivo", "rechazado_por", "rechazado_en")