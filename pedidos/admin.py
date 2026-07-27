from django.contrib import admin, messages
from .models import Pedido, SkuCourier
from django.urls import path, reverse
from .services import guardar_pedidos_woo, guardar_pedidos_sap, aprobar_pedido, rechazar_pedido, guardar_un_pedido_sap, guardar_un_pedido_woo, notificar_pedido
from django.shortcuts import redirect
from envios.services import despachar_pedidos
from django.template.response import TemplateResponse
from . import permisos
import datetime

#Modelo para detectar match entre courier y sku de la nota de venta (SOLO SAP)
@admin.register(SkuCourier)
class SkuCourierAdmin(admin.ModelAdmin):
    list_display = ("sku", "courier", "servicio_codigo", "servicio_nombre")

#Campos que aparecerán en la pantalla de admin del proyecto
@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    actions = ["aprobar_pedidos", "despachar_a_courier", "rechazar_pedidos", "notificar_pedidos"]
    list_display = ("origen", "modificado_en", "num_pedido", "ejecutivo", "tipo_entrega", "retirar_en", "courier", "rut", "razon_social", "nombre_contacto", "telefono_contacto", "email_contacto", "direccion_calle", "direccion_comuna", "direccion_ciudad", "estado_comercial", "estado_notificacion", "envio")

    def get_urls(self):
        urls_personalizadas = [
            path(
                "sincronizar/",
                self.admin_site.admin_view(self.sincronizar_pedidos),
                name="pedidos_pedido_sincronizar",
            ),

            path(
                "cargar-individual/",
                self.admin_site.admin_view(self.cargar_pedido_individual),
                name="pedidos_pedido_cargar_individual",
            ),
            path(
                "armar-despacho/",
                self.admin_site.admin_view(self.armar_despacho_courier),
                name="pedidos_pedido_armar_despacho",
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
                f"Woo: {resultado_woo['creados']} creados, {resultado_woo['omitidos']} omitidos (ya rechazados).", 
                level=messages.SUCCESS,
            )
            
        except Exception as exc:
            self.message_user(request, f"[!] Error sincronizando con Woo: {exc}", level=messages.ERROR)
        
        try:
            resultado_sap = guardar_pedidos_sap(after=fecha_desde, before=fecha_hasta)
            self.message_user(
                request,
                f"SAP: {resultado_sap['creados']} creados, {resultado_sap['omitidos']} omitidos (ya rechazados).", 
                level=messages.SUCCESS,
            )
        except Exception as exc:
            self.message_user(request, f"[!] Error sincronizando con SAP: {exc}", level=messages.ERROR)

        return redirect("admin:pedidos_pedido_changelist")
    
    def cargar_pedido_individual(self, request):
        if request.method != "POST":
            return redirect("admin:pedidos_pedido_changelist")

        num_pedido = request.POST.get("num_pedido")
        origen = request.POST.get("origen")
        if not num_pedido:
            self.message_user(request, "[!] Error: Debes indicar el N° de pedido.", level=messages.ERROR)
            return redirect("admin:pedidos_pedido_changelist")

        try:
            if origen == Pedido.Origen.SAP:
                mensaje = guardar_un_pedido_sap(num_pedido)

            elif origen == Pedido.Origen.WEB:
                mensaje = guardar_un_pedido_woo(num_pedido)
            
            else:
                raise ValueError(f"[!] Error: Origen '{origen}' no reconocido.")
            self.message_user(request, mensaje, level=messages.SUCCESS)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)

        return redirect("admin:pedidos_pedido_changelist")
    
    #Captura los datos y redirige al template para armar el despacho.
    def armar_despacho_courier(self, request):
        ids_texto = request.GET.get("ids") or request.POST.get("ids")

        if not ids_texto:
            self.message_user(request, "[!] Error: No se seleccionó ningún pedido.", level=messages.ERROR)
            return redirect("admin:pedidos_pedido_changelist")

        ids = [int(id_texto) for id_texto in ids_texto.split(",")]
        pedidos = list(Pedido.objects.filter(id__in=ids))

        if not pedidos:
            self.message_user(request, "[!] Error: No se encontraron los pedidos seleccionados.", level=messages.ERROR)
            return redirect("admin:pedidos_pedido_changelist")

        courier = pedidos[0].courier

        if request.method == "POST":
            if request.POST.get("modo_bultos") == "simple":
                cantidad_simple = int(request.POST.get("simple_cantidad") or 1)
                peso_total = float(request.POST.get("simple_peso_total") or 0)
                peso_por_bulto = round(peso_total / cantidad_simple, 2) if cantidad_simple else peso_total

                bultos = [{
                    "tipo": "CAJA",
                    "cantidad": cantidad_simple,
                    "alto": "",
                    "ancho": "",
                    "largo": "",
                    "peso": peso_por_bulto,
                    "tipo_contenido": request.POST.get("simple_tipo_contenido"),
                }]
            else:
                tipos = request.POST.getlist("bulto_tipo")
                cantidades = request.POST.getlist("bulto_cantidad")
                altos = request.POST.getlist("bulto_alto")
                anchos = request.POST.getlist("bulto_ancho")
                largos = request.POST.getlist("bulto_largo")
                pesos = request.POST.getlist("bulto_peso")
                contenidos = request.POST.getlist("bulto_tipo_contenido")

                bultos = []
                for i in range(len(pesos)):
                    bultos.append({
                        "tipo": tipos[i],
                        "cantidad": int(cantidades[i]),
                        "alto": altos[i],
                        "ancho": anchos[i],
                        "largo": largos[i],
                        "peso": float(pesos[i]),
                        "tipo_contenido": contenidos[i],
                    })

            destinatario = {
                "nombre": request.POST.get("destinatario_nombre"),
                "rut": request.POST.get("destinatario_rut"),
                "direccion": request.POST.get("destinatario_direccion"),
                "comuna": request.POST.get("destinatario_comuna"),
                "telefono": request.POST.get("destinatario_telefono"),
                "email": request.POST.get("destinatario_email"),
            }

            datos_courier = {
                "centro": request.POST.get("centro"),
                "servicio": request.POST.get("servicio"),
                "valor_declarado": request.POST.get("valor_declarado") or 0,
                "volumen_total": request.POST.get("volumen_total"),
                "observaciones": request.POST.get("observaciones"),
            }

            try:
                envio, notificaciones_fallidas = despachar_pedidos(pedidos, courier, bultos, destinatario, datos_courier, request.user)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                self.message_user(request, f"Envío #{envio.id} despachado a {courier}.", level=messages.SUCCESS)
                for pedido, error in notificaciones_fallidas:
                    self.message_user(request, f"[!] Aviso: Pedido {pedido.origen}-{pedido.num_pedido} despachado pero NO se pudo notificar: {error}", level=messages.WARNING)
                    
            return redirect("admin:pedidos_pedido_changelist")

        contexto = {
            **self.admin_site.each_context(request),
            "pedidos": pedidos,
            "courier": courier,
            "ids_texto": ids_texto,
        }
        return TemplateResponse(request, "admin/pedidos/pedido/armar_despacho.html", contexto)

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
    
    #Procesa los pedidos y si está todo ok, redirecciona al formulario de bultos. Lo hace tomando los id internos de los pedidos y guardandolos en "ids"
    @admin.action(description="Despachar a courier")
    def despachar_a_courier(self, request, queryset):
        ids_pedidos = ",".join(str(pedido.id) for pedido in queryset)

        if not ids_pedidos:
            self.message_user(request, "[!] Error: Debes seleccionar al menos un pedido", level=messages.ERROR)
            return
        
        return redirect(f"{reverse('admin:pedidos_pedido_armar_despacho')}?ids={ids_pedidos}")
    
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

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return super().get_readonly_fields(request, obj)

        campos_permitidos = permisos.campos_editables(request.user, obj)
        if campos_permitidos is None:
            return super().get_readonly_fields(request, obj)

        todos_los_campos = [f.name for f in Pedido._meta.fields]
        return [campo for campo in todos_los_campos if campo not in campos_permitidos]
    
    @admin.action(description="Notificar al cliente (despacho/retiro)")
    def notificar_pedidos(self, request, queryset):
        for pedido in queryset:
            try: 
                notificar_pedido(pedido, request.user)
            except(PermissionError, ValueError) as exc:
                self.message_user(request, f"[!] Error: Pedido {pedido.origen}-{pedido.num_pedido}: {exc}", level=messages.ERROR)
            else:
                self.message_user(request, f"Pedido {pedido.origen}-{pedido.num_pedido} notificado.", level=messages.SUCCESS)
    
    