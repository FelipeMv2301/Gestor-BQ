from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse

from ..models import Pedido
from .. import permisos
from envios.services import despachar_pedidos, validar_pedidos_para_despacho, PARSEAR_DESPACHO

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

    try:
        courier = validar_pedidos_para_despacho(pedidos)   # falla rápido: mismo RUT y courier, antes de mostrar el form
    except ValueError as exc:
        messages.error(request, str(exc).replace("[!] Error: ", ""))
        return redirect("pedidos:despachos")

    if request.method == "POST":
        parsear = PARSEAR_DESPACHO.get(courier)
        if not parsear:
            messages.error(request, f"No hay integración de despacho para {courier}.")
            return redirect(f"{reverse('pedidos:armar_despacho')}?ids={ids_texto}")

        try:
            # Cada parser lee del POST lo suyo y valida (lanza ValueError si falta algo).
            bultos, destinatario, datos_courier = parsear(request)
            envio, notificaciones_fallidas = despachar_pedidos(
                pedidos, courier, bultos, destinatario, datos_courier, request.user)
        except Exception as exc:  # validación del parser, o error HTTP/API del courier → mostrarlo en pantalla, no 500
            messages.error(request, str(exc).replace("[!] Error: ", ""))
            return redirect(f"{reverse('pedidos:armar_despacho')}?ids={ids_texto}")

        messages.success(request, f"Envío #{envio.id} despachado a {courier}.")
        for pedido, error in notificaciones_fallidas:
            messages.warning(request, f"{pedido.origen}-{pedido.num_pedido} despachado pero no se notificó: {error}")
        return redirect("pedidos:despachos")

    return render(request, "pedidos/armar_despacho.html",
                  {"pedidos": pedidos, "courier": courier, "ids_texto": ids_texto})
