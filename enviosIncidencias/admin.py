from django.contrib import admin
from .models import EnvioIncidencia

@admin.register(EnvioIncidencia)
class EnvioIncidenciaAdmin(admin.ModelAdmin):
    list_display = ("id", "courier", "orden_transporte", "motivo", "registrado_por",
"registrado_en")