from django.contrib import admin, messages
from .models import Pedido
from django.urls import path
from .services import guardar_pedidos_woo, guardar_pedidos_sap
from django.shortcuts import redirect
import datetime

#Campos que aparecerán en la pantalla de admin del proyecto
@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("origen", "num_pedido", "ejecutivo", "tipo_entrega", "transportation_code", "courier", "rut", "razon_social", "nombre_contacto", "telefono_contacto", "email_contacto", "direccion_calle", "direccion_comuna", "direccion_ciudad", "estado_comercial", "estado_notificacion", "orden_transporte")

    def get_urls(self):
        urls_personalizadas = [
            path(
                "sincronizar/",
                self.admin_site.admin_view(self.sincronizar_pedidos),
                name="pedidos_pedido_sincronizar",
            ),
        ]
        return urls_personalizadas + super().get_urls()

    def sincronizar_pedidos(self, request):
        if request.method != "POST":
            return redirect("admin:pedidos_pedido_changelist")
        
        #Mandar fecha desde y hasta a consulta
        fecha_desde = request.POST.get("after")
        fecha_hasta = request.POST.get("before") or datetime.date.today().isoformat()

        if not fecha_desde:
            self.message_user(request, "[!] Error: Debes indicar la fecha desde.", level=messages.ERROR)
            return redirect("admin:pedidos_pedido_changelist")
        
        try:
            resultado_woo = guardar_pedidos_woo(
            after = f"{fecha_desde}T00:00:00",
            before = f"{fecha_hasta}T23:59:59",
            )
            self.message_user(
                request,
                f"Woo: {resultado_woo['creados']} creados, {resultado_woo['actualizados']} actualizados.",
                level=messages.SUCCESS,
            )
            
        except Exception as exc:
            self.message_user(request, f"[!] Error sincronizando con Woo: {exc}", level=messages.ERROR)
        
        try:
            resultado_sap = guardar_pedidos_sap(after=fecha_desde, before=fecha_hasta)
            self.message_user(
                request,
                f"SAP: {resultado_sap['creados']} creados, {resultado_sap['actualizados']} actualizados.",
                level=messages.SUCCESS,
            )
        except Exception as exc:
            self.message_user(request, f"[!] Error sincronizando con SAP: {exc}", level=messages.ERROR)

        return redirect("admin:pedidos_pedido_changelist")


    
    