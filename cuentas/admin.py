from django.contrib import admin
from .models import PerfilUsuario

@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("usuario", "rol", "codigos_sap_display", "activo")
    filter_horizontal = ("ejecutivos",)   # selector M2M cómodo (dos columnas con búsqueda)

    #Muestra los códigos SAP del perfil (M2M, con fallback al escalar) en la lista
    @admin.display(description="Códigos SAP")
    def codigos_sap_display(self, obj):
        return ", ".join(str(c) for c in obj.codigos_sap) or "—"


