from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
import json

from ..models import Pedido
from pedidosRechazados.models import PedidoRechazado
from ..forms import PedidoEditForm
from .. import permisos
from .. import services
from ..services import opciones_courier_servicio

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
        .con_courier(request.GET.getlist("courier"))
        .select_related("ejecutivo", "envio")
        .order_by("-modificado_en")
    )

    contexto = {
        "pedidos": pedidos, "vista": vista, "q": request.GET.get("q", ""), "seleccionable": True,
        "sel_notif": request.GET.getlist("notif"), "sel_envio": request.GET.getlist("envio"),
        "sel_origen": request.GET.getlist("origen"), "sel_tipo": request.GET.getlist("tipo"),
        "sel_courier": request.GET.getlist("courier"), "courier_servicio_opciones": opciones_courier_servicio(),
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

#Cambia solo el courier desde la celda de la tabla (Mis pedidos / Despachos), sin entrar a Ver/Editar.
@login_required
@require_POST
def cambiar_courier(request, pk):
    pedido = get_object_or_404(
        permisos.queryset_para_ver(request.user).select_related("envio"), pk=pk)

    if not permisos.puede_editar_courier(request.user, pedido):
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": "No puedes editar el courier de este pedido."}})
        return resp

    form = PedidoEditForm(request.POST, instance=pedido, permitidos=["courier"])
    if form.is_valid():
        form.save()
        resp = render(request, "pedidos/_celda_courier.html", {"pedido": pedido, "courier_servicio_opciones": opciones_courier_servicio()})
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "success", "body": "Courier actualizado."}})
        return resp

    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = json.dumps({"toast": {"level": "error", "body": "Courier inválido."}})
    return resp


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
    rechazados = permisos.queryset_rechazados(request.user).select_related("rechazado_por").order_by("-rechazado_en")
    return render(request, "pedidos/anulados.html", {"rechazados": rechazados})

@login_required
@require_POST
def reingresar(request, pk):
    rechazado = get_object_or_404(PedidoRechazado, pk=pk)
    if not permisos.puede_reingresar(request.user, rechazado):
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error", "body": "No puedes reingresar este pedido."}})
        return resp

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
        .con_origen(request.GET.getlist("origen"))
        .select_related("ejecutivo", "envio")
        .order_by("-modificado_en")
    )

    contexto = {
        "pedidos": pedidos, "q": request.GET.get("q", ""), "seleccionable": True,
        "sel_notif": request.GET.getlist("notif"), "sel_courier": request.GET.getlist("courier"),
        "sel_envio": request.GET.getlist("envio"), "sel_tipo": request.GET.getlist("tipo"),
        "sel_origen": request.GET.getlist("origen"), "courier_servicio_opciones": opciones_courier_servicio(),
    }
    plantilla = "pedidos/_tabla_pedidos.html" if request.headers.get("HX-Request") else "pedidos/tablero_logistica.html"
    return render(request, plantilla, contexto)


"""
Helpers
"""
def _ctx_cuerpo(request, pedido):
    return {
        "pedido": pedido,
        "puede_editar": permisos.puede_editar(request.user, pedido),
        "puede_rechazar": permisos.puede_rechazar(request.user, pedido),
        "puede_notificar": permisos.puede_notificar(request.user, pedido),
        "puede_despachar": permisos.puede_despachar(request.user, pedido),
    }
