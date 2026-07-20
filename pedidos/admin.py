from django.contrib import admin, messages
from .models import Pedido
from django.urls import path
from .services import guardar_pedidos_woo, guardar_pedidos_sap, aprobar_pedido, rechazar_pedido
from django.shortcuts import redirect
from envios.services import despachar_pedidos
from . import permisos
import datetime

#Campos que aparecerán en la pantalla de admin del proyecto
@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    actions = ["aprobar_pedidos", "despachar_a_courier", "rechazar_pedidos"]
    list_display = ("origen", "num_pedido", "ejecutivo", "tipo_entrega", "transportation_code", "courier", "rut", "razon_social", "nombre_contacto", "telefono_contacto", "email_contacto", "direccion_calle", "direccion_comuna", "direccion_ciudad", "estado_comercial", "estado_notificacion", "envio")

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

    @admin.action(description="Aprobar pedido(s) seleccionado(s)")
    def aprobar_pedidos(self, request, queryset):
        for pedido in queryset:
            try:
                aprobar_pedido(pedido, request.user)
            except (PermissionError, ValueError) as exc:
                self.message_user(request, f"[!] Error: Pedido N° {pedido.origen}-{pedido.num_pedido}: {exc}", level=messages.ERROR)
            else:
                self.message_user(request, f"Pedido {pedido.origen}-{pedido.num_pedido} aprobado.", level=messages.SUCCESS)
    
    #Filtra los datos de la tabla para cada rol.
    def get_queryset(self, request):
      query = super().get_queryset(request)
      return permisos.queryset_visible(request.user, query)
    
    @admin.action(description="Despachar a courier")
    def despachar_a_courier(self, request, queryset):
        pedidos = list(queryset)
        
        if not pedidos:
            self.message_user(request, "[!] Error: Debes seleccionar al menos un pedido", level=messages.ERROR)
            return

        courier = pedidos[0].courier

        try:
            envio = despachar_pedidos(pedidos, courier, datos_courier={})
        
        except ValueError as exc:
            self.message_user(request, f"[!] Error; {exc}", level=messages.ERROR)

        else: self.message_user(request, f"Envío #{envio.id} creado, {len(pedidos)} pedido(s) vinculados.", level=messages.SUCCESS)
    
    #Funcion predeterminada que envía tu rol a Django y valida las cosas que puedes o no puedes hacer
    def has_change_permission(self, request, obj=None):
        if obj is None:
            return super().has_change_permission(request, obj)
        return permisos.puede_editar(request.user, obj)
        
    @admin.action(description="Rechazar/Cancelar pedido(s) seleccionado(s)")
    def rechazar_pedidos(self, request, queryset):
        for pedido in queryset:
            try:
                rechazar_pedido(pedido, motivo="", usuario=request.user)
            except PermissionError as exc:
                self.message_user(request, f"[!] Error: Pedido {pedido.origen}-{pedido.num_pedido}: {exc}", level=messages.ERROR)
            else:
                self.message_user(request, f"Pedido {pedido.origen}-{pedido.num_pedido} rechazado.", level=messages.SUCCESS)