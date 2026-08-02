from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import redirect
import datetime
from .models import Cotizacion
from .services import sincronizar_cotizaciones_sap, refrescar_cotizaciones_abiertas, actualizar_facturacion

@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    actions = ["recalcular_facturacion"]
    list_display = ("docnum", "card_name", "rut", "ejecutivo", "neto", "total", "total_facturado",
                    "estado", "fecha_contabilizacion", "fecha_caducidad", "actualizado_sap")
    search_fields = ("docnum", "card_name", "rut", "card_code")
    list_filter = ("estado", "tipo_venta", "area_trabajo")

    @admin.action(description="Recalcular facturación (seleccionadas)")
    def recalcular_facturacion(self, request, queryset):
        try:
            n = actualizar_facturacion(queryset)
        except Exception as exc:
            self.message_user(request, f"[!] Error recalculando facturación: {exc}", level=messages.ERROR)
        else:
            self.message_user(request, f"Facturación recalculada en {n} cotizaciones.", level=messages.SUCCESS)

    def get_urls(self):
        urls_personalizadas = [
            path(
                "sincronizar/",
                self.admin_site.admin_view(self.sincronizar_cotizaciones),
                name="cotizaciones_cotizacion_sincronizar",
            ),
            path(
                "refrescar-abiertas/",
                self.admin_site.admin_view(self.refrescar_abiertas),
                name="cotizaciones_cotizacion_refrescar_abiertas",
            ),
        ]
        return urls_personalizadas + super().get_urls()

    def sincronizar_cotizaciones(self, request):
        if request.method != "POST":
            return redirect("admin:cotizaciones_cotizacion_changelist")

        fecha_desde = request.POST.get("after")
        fecha_hasta = request.POST.get("before") or datetime.date.today().isoformat()

        if not fecha_desde:
            self.message_user(request, "[!] Error: Debes indicar la fecha desde.", level=messages.ERROR)
            return redirect("admin:cotizaciones_cotizacion_changelist")

        try:
            resultado = sincronizar_cotizaciones_sap(after=fecha_desde, before=fecha_hasta)
        except Exception as exc:
            self.message_user(request, f"[!] Error sincronizando cotizaciones: {exc}", level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Cotizaciones: {resultado['creadas']} creadas, {resultado['actualizadas']} actualizadas.",
                level=messages.SUCCESS,
            )
        return redirect("admin:cotizaciones_cotizacion_changelist")

    def refrescar_abiertas(self, request):
        if request.method != "POST":
            return redirect("admin:cotizaciones_cotizacion_changelist")

        try:
            resultado = refrescar_cotizaciones_abiertas()
        except Exception as exc:
            self.message_user(request, f"[!] Error refrescando cotizaciones abiertas: {exc}", level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Refrescadas {resultado['refrescadas']} cotizaciones abiertas.",
                level=messages.SUCCESS,
            )
        return redirect("admin:cotizaciones_cotizacion_changelist")