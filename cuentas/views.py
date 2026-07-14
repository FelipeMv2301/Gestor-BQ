from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from .models import PerfilUsuario

#Esto ayuda a validar que el usuario exista o que tenga asignado un rol
@login_required
def inicio(request):
    try:
        perfil = request.user.perfil
    
    except PerfilUsuario.DoesNotExist:
        perfil = None
    
    if perfil is None or perfil.rol is None:
        return render(request, "cuentas/esperando_activacion.html")
    
    return render(request, "cuentas/bienvenida.html", {"perfil":perfil})
    



