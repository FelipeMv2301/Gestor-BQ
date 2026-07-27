from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
import json

from .. import permisos
from .. import services

#Borrado permanente (sin paso por PedidoRechazado, sin motivo, sin poder reingresar). Solo Admin.
@login_required
@require_POST
def eliminar_lote(request):
    if not permisos.es_admin(request.user):
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": "Solo un administrador puede eliminar pedidos."}})
        return resp

    ids = request.POST.getlist("ids")
    pedidos = permisos.queryset_para_ver(request.user).filter(pk__in=ids)
    referencias = [f"{p.origen}-{p.num_pedido}" for p in pedidos]

    if not referencias:
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error", "body": "Selecciona al menos un pedido."}})
        return resp

    pedidos.delete()
    messages.success(request, f"{len(referencias)} pedido(s) eliminado(s) permanentemente: {', '.join(referencias)}.")

    referer = request.headers.get("Referer", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        destino = referer
    else:
        destino = reverse("pedidos:mis_pedidos")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = destino
    return resp

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
