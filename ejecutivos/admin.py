from django.contrib import admin, messages
from .models import Ejecutivo
from django.urls import path
from .services import sincronizar_ejecutivos_desde_sap
from django.shortcuts import redirect

#Campos que se van a mostrar en el panel de administrador
@admin.register(Ejecutivo)
class EjecutivoAdmin(admin.ModelAdmin):
    list_display=("nombre", "codigo_sap", "email", "activo")

    #definir las urls
    def get_urls(self):
        urls_personalizadas = [
            path(
                "sincronizar/",
                self.admin_site.admin_view(self.sincronizar_desde_sap),
                name="ejecutivos_ejecutivo_sincronizar",
            ),
        ]
        return urls_personalizadas + super().get_urls()

    #Ejecuta la función de ejecutivos en SAP, que viene desde services.py
    def sincronizar_desde_sap(self, request):
        if request.method != "POST":
            return redirect("admin:ejecutivos_ejecutivo_changelist")

        try:
            resultado = sincronizar_ejecutivos_desde_sap()
        
        except Exception as exc:
            self.message_user(request, f"[!] Error: No se pudo sincronizar con SAP: {exc}", level=messages.ERROR)
        
        #
        else: 
            self.message_user(
                request,
                f"{resultado['creados']} creados, {resultado['actualizados']} actualizados, "
                f"{resultado['marcados_inactivos']} marcados inactivos, "
                f"{resultado['perfiles_actualizados']} perfiles vinculados.",
                level=messages.SUCCESS,
            )
        return redirect("admin:ejecutivos_ejecutivo_changelist")