import datetime
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import reverse

from pedidos import permisos
from .models import DespachoOnt

CAMPOS_CHECKBOX = ("confirmacion_cliente", "retorno_documento", "pedido_recibido", "enviar", "fecha_compromiso_aproximada")
CAMPOS_TEXTO = ("guia_despacho", "observaciones_ok", "observaciones_entrega", "confirmacion_carga")


def _parsear_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.date.fromisoformat(valor)
    except ValueError:
        return None


@login_required
def lista_ont(request):
    seguimientos = (
        permisos.queryset_ont(request.user)
        .select_related("pedido", "pedido__envio", "pedido__ejecutivo")
        .buscar(request.GET.get("q", "").strip())
        .con_accion(request.GET.getlist("accion"))
        .con_fecha_compromiso(request.GET.get("compromiso_desde"), request.GET.get("compromiso_hasta"))
        .con_fecha_despacho(request.GET.get("despacho_desde"), request.GET.get("despacho_hasta"))
    )
    paginador = Paginator(seguimientos, 20)
    seguimientos = paginador.get_page(request.GET.get("page"))

    contexto = {
        "seguimientos": seguimientos,
        "q": request.GET.get("q", ""),
        "sel_accion": request.GET.getlist("accion"),
        "accion_choices": DespachoOnt.Accion.choices,
        "compromiso_desde": request.GET.get("compromiso_desde", ""),
        "compromiso_hasta": request.GET.get("compromiso_hasta", ""),
        "despacho_desde": request.GET.get("despacho_desde", ""),
        "despacho_hasta": request.GET.get("despacho_hasta", ""),
    }
    plantilla = "seguimientoOnt/_tabla_ont.html" if request.headers.get("HX-Request") else "seguimientoOnt/lista_ont.html"
    return render(request, plantilla, contexto)


@login_required
def detalle_ont(request, pk):
    seguimiento = get_object_or_404(DespachoOnt.objects.select_related("pedido", "pedido__envio"), pk=pk)
    puede_editar = permisos.puede_editar_ont(request.user, seguimiento)
    if not puede_editar:
        return redirect("inicio")
    return render(request, "seguimientoOnt/detalle_ont.html", {
        "seguimiento": seguimiento,
        "accion_choices": DespachoOnt.Accion.choices,
        "puede_editar": puede_editar,
    })


@login_required
@require_POST
def editar_ont(request, pk):
    seguimiento = get_object_or_404(DespachoOnt, pk=pk)
    if not permisos.puede_editar_ont(request.user, seguimiento):
        return HttpResponse(status=403)

    seguimiento.accion = request.POST.get("accion", "").strip()
    seguimiento.fecha_compromiso = _parsear_fecha(request.POST.get("fecha_compromiso"))
    seguimiento.fecha_despacho = _parsear_fecha(request.POST.get("fecha_despacho"))
    for campo in CAMPOS_TEXTO:
        setattr(seguimiento, campo, request.POST.get(campo, "").strip())
    for campo in CAMPOS_CHECKBOX:
        setattr(seguimiento, campo, request.POST.get(campo) == "on")
    seguimiento.save()

    messages.success(request, f"Seguimiento ONT {seguimiento.pedido.origen}-{seguimiento.pedido.num_pedido} actualizado.")

    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        referer = request.headers.get("Referer", "")
        resp["HX-Redirect"] = referer or reverse("seguimientoOnt:lista")
        return resp
    return redirect("seguimientoOnt:detalle", pk=pk)
