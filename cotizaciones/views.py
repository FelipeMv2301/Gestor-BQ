from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
import datetime
import json
from pedidos.permisos import es_admin
from .models import Cotizacion
from . import permisos
from . import services
from .services import documentos_asociados

# Create your views here.

@login_required
def lista_cotizaciones(request):
    cotizaciones = permisos.queryset_cotizaciones_visible(request.user).select_related("ejecutivo")

    q = request.GET.get("q", "").strip()
    if q:
        cotizaciones = cotizaciones.filter(
            Q(docnum__icontains=q) | Q(card_name__icontains=q) | Q(rut__icontains=q)
        )

    estados = request.GET.getlist("estado")
    if estados:
        cotizaciones = cotizaciones.filter(estado__in=estados)

    desde = request.GET.get("desde", "").strip()
    hasta = request.GET.get("hasta", "").strip()
    if desde:
        cotizaciones = cotizaciones.filter(fecha_contabilizacion__gte=desde)
    if hasta:
        cotizaciones = cotizaciones.filter(fecha_contabilizacion__lte=hasta)

    vence_desde = request.GET.get("vence_desde", "").strip()
    vence_hasta = request.GET.get("vence_hasta", "").strip()
    if vence_desde:
        cotizaciones = cotizaciones.filter(fecha_caducidad__gte=vence_desde)
    if vence_hasta:
        cotizaciones = cotizaciones.filter(fecha_caducidad__lte=vence_hasta)

    cotizaciones = cotizaciones.order_by("-fecha_contabilizacion")

    paginador = Paginator(cotizaciones, 20)
    cotizaciones = paginador.get_page(request.GET.get("page"))

    contexto = {
        "cotizaciones": cotizaciones, "q": q, "sel_estado": estados,
        "desde": desde, "hasta": hasta, "vence_desde": vence_desde, "vence_hasta": vence_hasta,
        "seleccionable": es_admin(request.user),  # solo Admin ve checkboxes + borrado
    }

    plantilla = ("cotizaciones/_tabla_cotizaciones.html"
                if request.headers.get("HX-Request")
                else "cotizaciones/cotizaciones.html")
    return render(request, plantilla, contexto)


@login_required
def detalle_cotizacion(request, pk):
    cotizacion = get_object_or_404(
        permisos.queryset_cotizaciones_visible(request.user).select_related("ejecutivo"),
        pk=pk,
    )
    # Trazado en vivo de la cadena (pega a SAP; una cotización = un cliente, aceptable en el detalle).
    docs = documentos_asociados(cotizacion)
    return render(request, "cotizaciones/detalle_cotizacion.html",
                  {"cotizacion": cotizacion, "docs": docs})


@login_required
@require_POST
def panel_sincronizar_cotizaciones(request):
    # Ingesta de cotizaciones por rango, desde el panel Administración del portal.
    if not es_admin(request.user):
        return redirect("inicio")
    desde = request.POST.get("after")
    hasta = request.POST.get("before") or datetime.date.today().isoformat()
    if not desde:
        messages.error(request, "Debes indicar la fecha desde.")
    else:
        try:
            r = services.sincronizar_cotizaciones_sap(after=desde, before=hasta)
            messages.success(request, f"Cotizaciones: {r['creadas']} creadas, {r['actualizadas']} actualizadas.")
        except Exception as exc:
            messages.error(request, f"Error sincronizando cotizaciones: {exc}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:panel_admin")
    return resp


@login_required
@require_POST
def panel_actualizar_facturacion(request):
    # Refresca datos + facturación de las cotizaciones ABIERTO/PARCIAL (acotado, seguro para web).
    if not es_admin(request.user):
        return redirect("inicio")
    try:
        r = services.refrescar_cotizaciones_abiertas()
        messages.success(request, f"Facturación actualizada en {r['refrescadas']} cotizaciones (abiertas/parciales).")
    except Exception as exc:
        messages.error(request, f"Error actualizando facturación: {exc}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:panel_admin")
    return resp


def _toast_error(mensaje):
    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = json.dumps({"toast": {"level": "error", "body": mensaje}})
    return resp


@login_required
@require_POST
def eliminar_cotizaciones(request):
    # Borra las cotizaciones seleccionadas (checkbox). Solo Admin. Se pueden re-sincronizar de SAP.
    if not es_admin(request.user):
        return _toast_error("Solo un administrador puede eliminar cotizaciones.")
    ids = request.POST.getlist("ids")
    queryset = Cotizacion.objects.filter(pk__in=ids)
    cantidad = queryset.count()
    if not cantidad:
        return _toast_error("Selecciona al menos una cotización.")
    queryset.delete()
    messages.success(request, f"{cantidad} cotización(es) eliminada(s). Se pueden re-sincronizar de SAP.")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("cotizaciones:lista")
    return resp


@login_required
@require_POST
def eliminar_todas_cotizaciones(request):
    # Borra TODAS las cotizaciones. Solo Admin. Se pueden re-sincronizar de SAP.
    if not es_admin(request.user):
        return _toast_error("Solo un administrador puede eliminar cotizaciones.")
    cantidad = Cotizacion.objects.count()
    Cotizacion.objects.all().delete()
    messages.success(request, f"{cantidad} cotización(es) eliminada(s) (todas). Se pueden re-sincronizar de SAP.")
    # Vuelve a donde se disparó (panel Administración o lista de cotizaciones).
    referer = request.headers.get("Referer", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        destino = referer
    else:
        destino = reverse("cotizaciones:lista")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = destino
    return resp