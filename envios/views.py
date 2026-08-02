from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib import messages
from pedidos.permisos import es_logistica
from cuentas.models import PerfilUsuario
from .models import EnvioCourier
from .services import parsear_bultos
from integraciones.seguimiento import refrescar_estados_courier, actualizar_estado_courier
from utils import Courier
from pedidos import permisos
from django.urls import reverse
from django.http import HttpResponse
from django.core.paginator import Paginator


@login_required
def lista_envios(request):
    if not es_logistica(request.user):
        return redirect("inicio")

    envios = (
        EnvioCourier.objects.buscar(request.GET.get("q", "").strip())
        .con_courier(request.GET.getlist("courier"))
        .con_origen(request.GET.getlist("origen"))
        .prefetch_related("pedidos")
        .order_by("-creado_en")
    )
    paginador = Paginator(envios, 20)
    envios = paginador.get_page(request.GET.get("page"))

    contexto = {
        "envios": envios, "q": request.GET.get("q", ""),
        "sel_courier": request.GET.getlist("courier"), "sel_origen": request.GET.getlist("origen"),
        "courier_choices": Courier.choices,
    }
    plantilla = "envios/_tabla_envios.html" if request.headers.get("HX-Request") else "envios/lista_envios.html"
    return render(request, plantilla, contexto)


#Igual que lista_envios pero acotado a los envíos del ejecutivo (los que agrupan un pedido suyo).
#Read-only: sin botón "Actualizar estados" (eso es de logística). ADMIN usa la lista completa.
@login_required
def mis_envios(request):
    if permisos.obtener_rol(request.user) != PerfilUsuario.Rol.EJECUTIVO:
        return redirect("inicio")

    codigos = permisos.codigos_sap_usuario(request.user)
    envios = (
        EnvioCourier.objects.de_ejecutivo(codigos)
        .buscar(request.GET.get("q", "").strip())
        .con_courier(request.GET.getlist("courier"))
        .con_origen(request.GET.getlist("origen"))
        .prefetch_related("pedidos")
        .order_by("-creado_en")
    )
    paginador = Paginator(envios, 20)
    envios = paginador.get_page(request.GET.get("page"))

    contexto = {
        "envios": envios, "q": request.GET.get("q", ""),
        "sel_courier": request.GET.getlist("courier"), "sel_origen": request.GET.getlist("origen"),
        "courier_choices": Courier.choices,
    }
    plantilla = "envios/_tabla_envios.html" if request.headers.get("HX-Request") else "envios/mis_envios.html"
    return render(request, plantilla, contexto)


@login_required
def detalle_envio(request, pk):
    envio = get_object_or_404(EnvioCourier.objects.prefetch_related("pedidos"), pk=pk)
    if not permisos.puede_ver_envio(request.user, envio):
        return redirect("inicio")
    # Ejecutivo: read-only (sin botones de acción). Logística/Admin: gestiona.
    return render(request, "envios/detalle_envio.html",
                  {"envio": envio, "puede_gestionar": es_logistica(request.user)})


#Batch: refresca el estado-courier de todos los MoveUP en 1 sola llamada a la API (ver seguimiento.py).
@login_required
@require_POST
def refrescar_estados(request):
    if not es_logistica(request.user):
        return redirect("inicio")
    envios = EnvioCourier.objects.filter(courier=Courier.MOVEUP)
    total = refrescar_estados_courier(envios)
    messages.success(request, f"Estados de courier actualizados ({total} envío/s).")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("envios:lista")
    return resp


#Individual: refresca el estado-courier de UN envío (1 llamada). Para el botón del detalle.
@login_required
@require_POST
def refrescar_estado_envio(request, pk):
    if not es_logistica(request.user):
        return redirect("inicio")
    envio = get_object_or_404(EnvioCourier, pk=pk)
    try:
        if actualizar_estado_courier(envio):
            messages.success(request, f"Estado actualizado: {envio.estado_courier or '—'}.")
        else:
            messages.info(request, "Este courier no tiene consulta de estado por API.")
    except Exception as exc:
        messages.error(request, f"No se pudo consultar el estado: {exc}")
    return redirect("envios:detalle", pk=pk)


#Solo ENTREGADO/ERROR: nada del flujo automático los setea hoy (despachar_pedidos deja DESPACHADO).
@login_required
@require_POST
def cambiar_estado_envio(request, pk):
    if not es_logistica(request.user):
        return redirect("inicio")
    envio = get_object_or_404(EnvioCourier, pk=pk)
    nuevo_estado = request.POST.get("estado")
    if nuevo_estado not in (EnvioCourier.Estado.ENTREGADO, EnvioCourier.Estado.ERROR):
        messages.error(request, "Estado inválido.")
        return redirect("envios:detalle", pk=pk)

    envio.estado = nuevo_estado
    envio.save(update_fields=["estado", "actualizado_en"])
    messages.success(request, f"Envío #{envio.id} marcado como {envio.get_estado_display()}.")
    return redirect("envios:detalle", pk=pk)

@login_required
def editar_envio(request, pk):
    if not permisos.es_logistica(request.user):
        return redirect("inicio")
    envio = get_object_or_404(EnvioCourier, pk=pk)

    if request.method == "POST":
        bultos = parsear_bultos(request)

        envio.courier = request.POST.get("courier")
        envio.orden_transporte = request.POST.get("orden_transporte", "").strip()
        envio.datos_courier = {
            "centro": request.POST.get("centro"),
            "servicio": request.POST.get("servicio"),
            "valor_declarado": request.POST.get("valor_declarado") or 0,
            "volumen_total": request.POST.get("volumen_total"),
            "observaciones": request.POST.get("observaciones"),
            "bultos": bultos,
        }
        envio.save()
        messages.success(request, f"Envío #{envio.id} actualizado.")
        return redirect("envios:detalle", pk=envio.pk)

    return render(request, "envios/editar_envio.html",
                {"envio": envio, "courier_choices": Courier.choices})

@login_required
@require_POST
def eliminar_envio(request, pk):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    envio = get_object_or_404(EnvioCourier, pk=pk)
    envio.delete()  # Pedido.envio es SET_NULL — los pedidos quedan sin envío, no se borran
    messages.success(request, f"Envío #{pk} eliminado.")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("envios:lista")
    return resp
