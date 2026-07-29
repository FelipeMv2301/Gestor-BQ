from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from pedidos.permisos import es_admin
from .models import PerfilUsuario
from .forms import PerfilUsuarioForm
import json

#Esto ayuda a validar que el usuario exista o que tenga asignado un rol
@login_required
def inicio(request):
    try:
        perfil = request.user.perfil
    
    except PerfilUsuario.DoesNotExist:
        perfil = None
    
    if perfil is None or perfil.rol is None:
        return render(request, "cuentas/esperando_activacion.html")
    
    if perfil.rol == PerfilUsuario.Rol.EJECUTIVO:
        return redirect("pedidos:mis_pedidos")

    if perfil.rol == PerfilUsuario.Rol.LOGISTICA:
        return redirect("pedidos:despachos")

    if perfil.rol == PerfilUsuario.Rol.ADMIN:
        return redirect("pedidos:panel_admin")

    return render(request, "cuentas/bienvenida.html", {"perfil":perfil})


@login_required
def panel_perfiles(request):
    if not es_admin(request.user):
        return redirect("inicio")
    perfiles = PerfilUsuario.objects.select_related("usuario").order_by("usuario__email")
    paginador = Paginator(perfiles, 20)
    perfiles = paginador.get_page(request.GET.get("page"))
    return render(request, "cuentas/panel_perfiles.html",
                  {"perfiles": perfiles, "rol_choices": PerfilUsuario.Rol.choices})


#Trae el form (GET, al clickear "Editar" en una fila) y lo procesa (POST). Al guardar, devuelve
#la fila actualizada (OOB, para que la lista de la izquierda quede al día) + el form de la derecha.
@login_required
def editar_perfil(request, pk):
    perfil = get_object_or_404(PerfilUsuario.objects.select_related("usuario"), pk=pk)

    if not es_admin(request.user):
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"toast": {"level": "error",
            "body": "Solo un administrador puede editar perfiles."}})
        return resp

    if request.method == "POST":
        form = PerfilUsuarioForm(request.POST, instance=perfil)
        if form.is_valid():
            form.save()
            fila_html = render_to_string("cuentas/_fila_perfil.html", {"perfil": perfil, "oob": True}, request=request)
            form_html = render_to_string("cuentas/_form_perfil.html",
                {"perfil": perfil, "form": PerfilUsuarioForm(instance=perfil)}, request=request)
            resp = HttpResponse(fila_html + form_html)
            resp["HX-Trigger"] = json.dumps({"toast": {"level": "success",
                "body": f"Perfil de {perfil.usuario.email} actualizado."}})
            return resp
        return render(request, "cuentas/_form_perfil.html", {"perfil": perfil, "form": form})

    form = PerfilUsuarioForm(instance=perfil)
    return render(request, "cuentas/_form_perfil.html", {"perfil": perfil, "form": form})
    



