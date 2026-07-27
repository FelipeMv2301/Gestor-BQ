from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse
from pedidos.permisos import es_admin
from .models import Ejecutivo
from .forms import EjecutivoForm
from .services import sincronizar_ejecutivos_desde_sap

@login_required
def panel_ejecutivos(request):
    if not es_admin(request.user):
        return redirect("inicio")
    ejecutivos = Ejecutivo.objects.order_by("nombre")
    return render(request, "ejecutivos/panel_ejecutivos.html",
                {"ejecutivos": ejecutivos, "form": EjecutivoForm()})

@login_required
@require_POST
def crear_ejecutivo(request):
    if not es_admin(request.user):
        return redirect("inicio")
    form = EjecutivoForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Ejecutivo creado.")
    else:
        messages.error(request, f"No se pudo crear: {form.errors.as_text()}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("ejecutivos:panel")
    return resp

@login_required
@require_POST
def editar_ejecutivo(request, pk):
    if not es_admin(request.user):
        return redirect("inicio")
    ejecutivo = get_object_or_404(Ejecutivo, pk=pk)
    form = EjecutivoForm(request.POST, instance=ejecutivo)
    if form.is_valid():
        form.save()
        messages.success(request, f"Ejecutivo {ejecutivo.nombre} actualizado.")
    else:
        messages.error(request, f"No se pudo actualizar: {form.errors.as_text()}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("ejecutivos:panel")
    return resp

@login_required
@require_POST
def sincronizar_ejecutivos(request):
    if not es_admin(request.user):
        return redirect("inicio")
    try:
        r = sincronizar_ejecutivos_desde_sap()
        messages.success(
            request,
            f"{r['creados']} creados, {r['actualizados']} actualizados, "
            f"{r['marcados_inactivos']} marcados inactivos, "
            f"{r['perfiles_actualizados']} perfiles vinculados.",
        )
    except Exception as exc:
        messages.error(request, f"Error sincronizando con SAP: {exc}")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("ejecutivos:panel")
    return resp

@login_required
@require_POST
def eliminar_ejecutivo(request, pk):
    if not es_admin(request.user):
        return redirect("inicio")
    ejecutivo = get_object_or_404(Ejecutivo, pk=pk)
    nombre = ejecutivo.nombre
    ejecutivo.delete()
    messages.success(request, f"Ejecutivo {nombre} eliminado.")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse("ejecutivos:panel")
    return resp