from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
import datetime

from ..models import Pedido, SkuCourier
from ..forms import SkuCourierForm
from utils import Courier
from .. import permisos
from .. import services

@login_required
def panel_admin(request):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    return render(request, "pedidos/panel_admin.html", {})

@login_required
@require_POST
def sincronizar(request):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    desde = request.POST.get("after")
    hasta = request.POST.get("before") or datetime.date.today().isoformat()
    if not desde:
        messages.error(request, "Debes indicar la fecha desde.")
    else:
        try:
            r = services.guardar_pedidos_woo(after=f"{desde}T00:00:00", before=f"{hasta}T23:59:59")
            messages.success(request, f"Woo: {r['creados']} creados, {r['omitidos']} omitidos.")
        except Exception as exc:
            messages.error(request, f"Error Woo: {exc}")
        try:
            r = services.guardar_pedidos_sap(after=desde, before=hasta)
            messages.success(request, f"SAP: {r['creados']} creados, {r['omitidos']} omitidos.")
        except Exception as exc:
            messages.error(request, f"Error SAP: {exc}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:panel_admin")
    return resp

@login_required
@require_POST
def cargar_individual(request):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    num = request.POST.get("num_pedido")
    origen = request.POST.get("origen")
    if not num:
        messages.error(request, "Debes indicar el N° de pedido.")
    else:
        try:
            if origen == Pedido.Origen.SAP:
                msg = services.guardar_un_pedido_sap(num)
            elif origen == Pedido.Origen.WEB:
                msg = services.guardar_un_pedido_woo(num)
            else:
                raise ValueError(f"Origen '{origen}' no reconocido.")
            messages.success(request, msg)
        except ValueError as exc:
            messages.error(request, str(exc).replace("[!] Error: ", ""))
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:panel_admin")
    return resp

@login_required
def panel_skus(request):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    skus = SkuCourier.objects.order_by("sku")
    return render(request, "pedidos/panel_skus.html",
                  {"skus": skus, "form": SkuCourierForm(), "courier_choices": Courier.choices})

@login_required
@require_POST
def crear_sku(request):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    form = SkuCourierForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "SKU-Courier creado.")
    else:
        messages.error(request, f"No se pudo crear: {form.errors.as_text()}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:panel_skus")
    return resp

@login_required
@require_POST
def editar_sku(request, pk):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    sku_courier = get_object_or_404(SkuCourier, pk=pk)
    form = SkuCourierForm(request.POST, instance=sku_courier)
    if form.is_valid():
        form.save()
        messages.success(request, f"SKU {sku_courier.sku} actualizado.")
    else:
        messages.error(request, f"No se pudo actualizar: {form.errors.as_text()}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:panel_skus")
    return resp

@login_required
@require_POST
def eliminar_sku(request, pk):
    if not permisos.es_admin(request.user):
        return redirect("inicio")
    sku_courier = get_object_or_404(SkuCourier, pk=pk)
    sku = sku_courier.sku
    sku_courier.delete()
    messages.success(request, f"SKU {sku} eliminado.")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("pedidos:panel_skus")
    return resp
