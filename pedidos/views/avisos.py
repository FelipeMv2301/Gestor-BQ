from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

@login_required
@require_POST
def marcar_avisos_leidos(request):
    request.user.avisos.filter(leida=False).update(leida=True)
    return render(request, "partials/_campana_avisos.html",
                  {"avisos": [], "no_leidos": 0, "abierto": True})

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
@require_POST
def descartar_aviso(request, pk):
    aviso = get_object_or_404(request.user.avisos, pk=pk)   # solo TUS avisos
    aviso.leida = True
    aviso.save(update_fields=["leida"])
    no_leidos = request.user.avisos.filter(leida=False).count()
    avisos = request.user.avisos.filter(leida=False)[:10]
    return render(request, "partials/_campana_avisos.html",
                  {"avisos": avisos, "no_leidos": no_leidos, "abierto": True})

@login_required
def avisos_campana(request):
    avisos = request.user.avisos.filter(leida=False)[:10]
    no_leidos = request.user.avisos.filter(leida=False).count()
    return render(request, "partials/_campana_avisos.html",
                  {"avisos": avisos, "no_leidos": no_leidos})
