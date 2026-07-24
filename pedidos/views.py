from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from .models import Pedido
from pedidosRechazados.models import PedidoRechazado
from .forms import PedidoEditForm
from . import permisos
from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from . import services
from envios.services import despachar_pedidos
import json

#Pantalla principal de la aplicación. Es aquí donde irán las funcionalidades de los filtros de búsqueda y el buscador
@login_required
def mis_pedidos(request):
    vista = request.GET.get("vista", "pendientes")
    estado = {
        "pendientes": Pedido.EstadoComercial.PENDIENTE,
        "cargados": Pedido.EstadoComercial.APROBADO,
    }.get(vista)  # "todos" → None

    pedidos = (
        permisos.queryset_pedidos_ejecutivo(request.user)   # ← scope de seguridad (quién ve qué)
        .con_estado_comercial(estado)
        .buscar(request.GET.get("q", "").strip())
        .con_notificacion(request.GET.getlist("notif"))
        .con_envio(request.GET.getlist("envio"))
        .con_origen(request.GET.getlist("origen"))
        .con_tipo_entrega(request.GET.getlist("tipo"))
        .select_related("ejecutivo", "envio")
        .order_by("-modificado_en")
    )

    contexto = {
        "pedidos": pedidos, "vista": vista, "q": request.GET.get("q", ""), "seleccionable": True,
        "sel_notif": request.GET.getlist("notif"), "sel_envio": request.GET.getlist("envio"),
        "sel_origen": request.GET.getlist("origen"), "sel_tipo": request.GET.getlist("tipo"),
    }

    plantilla = "pedidos/_tabla_pedidos.html" if request.headers.get("HX-Request") else "pedidos/mis_pedidos.html"
    return render(request, plantilla, contexto)

@login_required
@require_POST
def aprobar(request, pk):
    pedido = get_object_or_404(permisos.queryset_para_ver(request.user), pk=pk)
    try:
        services.aprobar_pedido(pedido, request.user)
    except (PermissionError, ValueError) as exc:
        # Error accionable → toast rojo, se queda en la ficha
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({
            "toast": {"level": "error", "body": str(exc).replace("[!] Error: ", "")}
        })
        return resp

    # Éxito → mensaje + recarga la ficha (badge, botones, candados quedan consistentes)
    messages.success(request, f"Pedido {pedido.origen}-{pedido.num_pedido} enviado a Logística.")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:detalle", args=[pk])
    return resp

@login_required
def detalle_pedido(request, pk):
    pedido = get_object_or_404(
        permisos.queryset_para_ver(request.user).select_related("ejecutivo", "envio"), pk=pk)
    return render(request, "pedidos/detalle_pedido.html", _ctx_cuerpo(request, pedido))

@login_required
def detalle_cuerpo(request, pk):
    pedido = get_object_or_404(
        permisos.queryset_para_ver(request.user).select_related("ejecutivo", "envio"), pk=pk)
    return render(request, "pedidos/_detalle_cuerpo.html", _ctx_cuerpo(request, pedido))

@login_required
def editar(request, pk):
    pedido = get_object_or_404(
        permisos.queryset_para_ver(request.user).select_related("ejecutivo", "envio"), pk=pk)

    if not permisos.puede_editar(request.user, pedido):
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": "No puedes editar este pedido en su estado actual."}})
        return resp

    permitidos = permisos.campos_editables(request.user, pedido)  # None = Admin (todos)

    if request.method == "POST":
        form = PedidoEditForm(request.POST, instance=pedido, permitidos=permitidos)
        if form.is_valid():
            form.save()
            resp = render(request, "pedidos/_detalle_cuerpo.html", _ctx_cuerpo(request, pedido))
            resp["HX-Trigger"] = json.dumps({"toast": {"level": "success", "body": "Cambios guardados."}})
            return resp
        return render(request, "pedidos/_form_editar.html", {"form": form, "pedido": pedido})

    form = PedidoEditForm(instance=pedido, permitidos=permitidos)
    return render(request, "pedidos/_form_editar.html", {"form": form, "pedido": pedido})


@login_required
def rechazar(request, pk):
    pedido = get_object_or_404(permisos.queryset_para_ver(request.user), pk=pk)

    if not permisos.puede_rechazar(request.user, pedido):
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": "Solo un administrador puede anular pedidos."}})
        return resp

    if request.method == "POST":
        motivo = request.POST.get("motivo", "").strip()
        services.rechazar_pedido(pedido, motivo, request.user)  # archiva en PedidoRechazado + borra
        messages.success(request, f"Pedido {pedido.origen}-{pedido.num_pedido} anulado.")
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = reverse("pedidos:mis_pedidos")
        return resp

    return render(request, "pedidos/_modal_rechazo.html", {"pedido": pedido})


@login_required
def anulados(request):
    if not permisos.puede_reingresar(request.user):  # vista solo para Admin
        return redirect("inicio")
    rechazados = PedidoRechazado.objects.select_related("rechazado_por").order_by("-rechazado_en")
    return render(request, "pedidos/anulados.html", {"rechazados": rechazados})


@login_required
@require_POST
def reingresar(request, pk):
    if not permisos.puede_reingresar(request.user):
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": "Solo un administrador puede reingresar pedidos."}})
        return resp

    rechazado = get_object_or_404(PedidoRechazado, pk=pk)
    origen, num = rechazado.origen, rechazado.num_pedido
    try:
        services.reingresar_pedido(rechazado)
    except Exception as exc:
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": str(exc).replace("[!] Error: ", "")}})
        return resp

    messages.success(request, f"Pedido {origen}-{num} reingresado desde la fuente.")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:anulados")
    return resp

@login_required
def avisos_campana(request):
    avisos = request.user.avisos.all()[:10]                     
    no_leidos = request.user.avisos.filter(leida=False).count()
    return render(request, "partials/_campana_avisos.html",
                  {"avisos": avisos, "no_leidos": no_leidos})

@login_required
@require_POST
def marcar_avisos_leidos(request):
    request.user.avisos.filter(leida=False).update(leida=True)   
    return render(request, "partials/_campana_avisos.html",
                  {"avisos": request.user.avisos.all()[:10], "no_leidos": 0})

@login_required
@require_POST
def marcar_aviso_leido(request, pk):
    aviso = get_object_or_404(request.user.avisos, pk=pk)        # scope: solo TUS avisos (seguridad)
    aviso.leida = True
    aviso.save(update_fields=["leida"])
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = (reverse("pedidos:detalle", args=[aviso.pedido_id])
                           if aviso.pedido_id else reverse("pedidos:mis_pedidos"))
    return resp

@login_required
def tablero_logistica(request):
    if not permisos.es_logistica(request.user):
        return redirect("inicio")

    pedidos = (
        Pedido.objects.con_estado_comercial(Pedido.EstadoComercial.APROBADO)
        .buscar(request.GET.get("q", "").strip())
        .con_notificacion(request.GET.getlist("notif"))
        .con_courier(request.GET.getlist("courier"))
        .con_envio(request.GET.getlist("envio"))
        .con_tipo_entrega(request.GET.getlist("tipo"))
        .select_related("ejecutivo", "envio")
        .order_by("-modificado_en")
    )

    contexto = {
        "pedidos": pedidos, "q": request.GET.get("q", ""), "seleccionable": True,
        "sel_notif": request.GET.getlist("notif"), "sel_courier": request.GET.getlist("courier"),
        "sel_envio": request.GET.getlist("envio"), "sel_tipo": request.GET.getlist("tipo"),
    }
    plantilla = "pedidos/_tabla_pedidos.html" if request.headers.get("HX-Request") else "pedidos/tablero_logistica.html"
    return render(request, plantilla, contexto)

@login_required
@require_POST
def aprobar_lote(request):
    # Reusa aprobar_pedido en loop; junta ok/errores en un toast resumen.
    ids = request.POST.getlist("ids")
    pedidos = permisos.queryset_para_ver(request.user).filter(pk__in=ids)

    aprobados = 0
    for pedido in pedidos:
        try:
            services.aprobar_pedido(pedido, request.user)
            aprobados += 1
        except (PermissionError, ValueError) as exc:
            messages.error(request, f"{pedido.origen}-{pedido.num_pedido}: {str(exc).replace('[!] Error: ', '')}")
    if aprobados:
        messages.success(request, f"{aprobados} pedido(s) enviado(s) a Logística.")

    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:mis_pedidos")
    return resp


@login_required
@require_POST
def notificar_lote(request):
    # Reusa notificar_pedido en loop; toast resumen.
    ids = request.POST.getlist("ids")
    pedidos = permisos.queryset_para_ver(request.user).filter(pk__in=ids)

    notificados = 0
    for pedido in pedidos:
        try:
            services.notificar_pedido(pedido, request.user)
            notificados += 1
        except (PermissionError, ValueError) as exc:
            messages.error(request, f"{pedido.origen}-{pedido.num_pedido}: {str(exc).replace('[!] Error: ', '')}")
    if notificados:
        messages.success(request, f"{notificados} cliente(s) notificado(s).")

    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:despachos")
    return resp


@login_required
@require_POST
def notificar(request, pk):
    pedido = get_object_or_404(permisos.queryset_para_ver(request.user), pk=pk)
    try:
        services.notificar_pedido(pedido, request.user)   # ← dispara el aviso al ejecutivo
    except (PermissionError, ValueError) as exc:
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": str(exc).replace("[!] Error: ", "")}})
        return resp
    messages.success(request, f"Cliente del pedido {pedido.origen}-{pedido.num_pedido} notificado.")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:detalle", args=[pk])
    return resp

@login_required
def armar_despacho(request):
    if not permisos.es_logistica(request.user):
        return redirect("inicio")

    ids_texto = request.GET.get("ids") or request.POST.get("ids")
    if not ids_texto:
        messages.error(request, "No se seleccionó ningún pedido.")
        return redirect("pedidos:despachos")

    ids = [int(x) for x in ids_texto.split(",") if x]
    pedidos = list(Pedido.objects.filter(id__in=ids))
    if not pedidos:
        messages.error(request, "No se encontraron los pedidos seleccionados.")
        return redirect("pedidos:despachos")

    courier = pedidos[0].courier

    if request.method == "POST":
        if request.POST.get("modo_bultos") == "simple":
            cantidad = int(request.POST.get("simple_cantidad") or 1)
            peso_total = float(request.POST.get("simple_peso_total") or 0)
            peso_unitario = round(peso_total / cantidad, 2) if cantidad else peso_total
            bultos = [{"tipo": "CAJA", "cantidad": cantidad, "alto": "", "ancho": "", "largo": "",
                       "peso": peso_unitario, "tipo_contenido": request.POST.get("simple_tipo_contenido")}]
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
                bultos.append({"tipo": tipos[i], "cantidad": int(cantidades[i]), "alto": altos[i],
                               "ancho": anchos[i], "largo": largos[i], "peso": float(pesos[i]),
                               "tipo_contenido": contenidos[i]})

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
            envio, notificaciones_fallidas = despachar_pedidos(
                pedidos, courier, bultos, destinatario, datos_courier, request.user)
        except ValueError as exc:
            messages.error(request, str(exc).replace("[!] Error: ", ""))
            return redirect(f"{reverse('pedidos:armar_despacho')}?ids={ids_texto}")

        messages.success(request, f"Envío #{envio.id} despachado a {courier}.")
        for pedido, error in notificaciones_fallidas:
            messages.warning(request, f"{pedido.origen}-{pedido.num_pedido} despachado pero no se notificó: {error}")
        return redirect("pedidos:despachos")

    return render(request, "pedidos/armar_despacho.html",
                  {"pedidos": pedidos, "courier": courier, "ids_texto": ids_texto})


"""
Helpers
"""
def _ctx_cuerpo(request, pedido):
    return {
        "pedido": pedido,
        "puede_editar": permisos.puede_editar(request.user, pedido),
        "puede_rechazar": permisos.puede_rechazar(request.user, pedido),
        "puede_notificar": permisos.puede_notificar(request.user, pedido),
    }