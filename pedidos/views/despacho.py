from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse

from ..models import Pedido
from .. import permisos
from envios.services import despachar_pedidos, validar_pedidos_para_despacho

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
        if request.POST.get("modo_bultos") == "simple":
            cantidad = int(request.POST.get("simple_cantidad") or 1)
            peso_total = float(request.POST.get("simple_peso_total") or 0)
            peso_unitario = round(peso_total / cantidad, 2) if cantidad else peso_total
            bultos = [{"tipo": "CAJA", "cantidad": cantidad, "alto": "", "ancho": "", "largo": "",
                       "peso": peso_unitario, "tipo_contenido": request.POST.get("simple_tipo_contenido")}]
        else:
            tipos = request.POST.getlist("bulto_tipo")
            cantidades = request.POST.getlist("bulto_cantidad")
            altos = request.POST.getlist("bulto_alto")
            anchos = request.POST.getlist("bulto_ancho")
            largos = request.POST.getlist("bulto_largo")
            pesos = request.POST.getlist("bulto_peso")
            contenidos = request.POST.getlist("bulto_tipo_contenido")
            bultos = []
            for i in range(len(pesos)):
                bultos.append({"tipo": tipos[i], "cantidad": int(cantidades[i]), "alto": altos[i],
                               "ancho": anchos[i], "largo": largos[i], "peso": float(pesos[i]),
                               "tipo_contenido": contenidos[i]})

        destinatario = {
            "nombre": request.POST.get("destinatario_nombre"),
            "rut": request.POST.get("destinatario_rut"),
            "direccion": request.POST.get("destinatario_direccion"),
            "comuna": request.POST.get("destinatario_comuna"),
            "telefono": request.POST.get("destinatario_telefono"),
            "email": request.POST.get("destinatario_email"),
        }
        datos_courier = {
            "centro": request.POST.get("centro"),
            "servicio": request.POST.get("servicio"),
            "valor_declarado": request.POST.get("valor_declarado") or 0,
            "volumen_total": request.POST.get("volumen_total"),
            "observaciones": request.POST.get("observaciones"),
        }

        try:
            envio, notificaciones_fallidas = despachar_pedidos(
                pedidos, courier, bultos, destinatario, datos_courier, request.user)
        except ValueError as exc:
            messages.error(request, str(exc).replace("[!] Error: ", ""))
            return redirect(f"{reverse('pedidos:armar_despacho')}?ids={ids_texto}")

        messages.success(request, f"Envío #{envio.id} despachado a {courier}.")
        for pedido, error in notificaciones_fallidas:
            messages.warning(request, f"{pedido.origen}-{pedido.num_pedido} despachado pero no se notificó: {error}")
        return redirect("pedidos:despachos")

    return render(request, "pedidos/armar_despacho.html",
                  {"pedidos": pedidos, "courier": courier, "ids_texto": ids_texto})
