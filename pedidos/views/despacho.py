from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages

from ..models import Pedido
from .. import permisos
from envios.services import despachar_pedidos, validar_pedidos_para_despacho, PARSEAR_DESPACHO
from integraciones import starken_client
from utils import Courier


# Reconstruye las filas de bultos tipeadas en un POST fallido, para no perderlas al volver a
# mostrar el formulario (ver armar_despacho). Vacío si nunca se envió nada (GET inicial).
def _bultos_previos(request):
    tipos = request.POST.getlist("bulto_tipo")
    cantidades = request.POST.getlist("bulto_cantidad")
    altos = request.POST.getlist("bulto_alto")
    anchos = request.POST.getlist("bulto_ancho")
    largos = request.POST.getlist("bulto_largo")
    pesos = request.POST.getlist("bulto_peso")
    contenidos = request.POST.getlist("bulto_tipo_contenido")
    total = len(pesos)
    return [{
        "tipo": tipos[i] if i < len(tipos) else "",
        "cantidad": cantidades[i] if i < len(cantidades) else "",
        "alto": altos[i] if i < len(altos) else "",
        "ancho": anchos[i] if i < len(anchos) else "",
        "largo": largos[i] if i < len(largos) else "",
        "peso": pesos[i] if i < len(pesos) else "",
        "tipo_contenido": contenidos[i] if i < len(contenidos) else "",
    } for i in range(total)]


# Idem para documentos de referencia. Chibra usa doc_tipo/doc_referencia; Starken usa
# doc_tipo/doc_numero — cada template lee solo la clave que le corresponde.
def _documentos_previos(request):
    tipos = request.POST.getlist("doc_tipo")
    referencias = request.POST.getlist("doc_referencia")
    numeros = request.POST.getlist("doc_numero")
    total = max(len(tipos), len(referencias), len(numeros))
    return [{
        "tipo": tipos[i] if i < len(tipos) else "",
        "referencia": referencias[i] if i < len(referencias) else "",
        "numero": numeros[i] if i < len(numeros) else "",
    } for i in range(total)]


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

    observaciones_sugeridas = " | ".join(
        f"{p.origen}-{p.num_pedido}: {p.observaciones.strip()}"
        for p in pedidos if p.observaciones and p.observaciones.strip()
    )
    contexto = {"pedidos": pedidos, "courier": courier, "ids_texto": ids_texto,
                "observaciones_sugeridas": observaciones_sugeridas,
                "post": {}, "bultos_previos": [], "documentos_previos": []}
    if courier == Courier.STARKEN:
        try:
            contexto["agencias_starken"] = starken_client.listar_agencias()
        except Exception:
            contexto["agencias_starken"] = []  # degrada a input manual si la API de agencias falla

    if request.method == "POST":
        parsear = PARSEAR_DESPACHO.get(courier)
        if not parsear:
            messages.error(request, f"No hay integración de despacho para {courier}.")
        else:
            try:
                # Cada parser lee del POST lo suyo y valida (lanza ValueError si falta algo).
                bultos, destinatario, datos_courier = parsear(request)
                envio, notificaciones_fallidas = despachar_pedidos(
                    pedidos, courier, bultos, destinatario, datos_courier, request.user)
            except Exception as exc:  # validación del parser, o error HTTP/API del courier → mostrarlo en pantalla, no 500
                messages.error(request, str(exc).replace("[!] Error: ", ""))
            else:
                messages.success(request, f"Envío #{envio.id} despachado a {courier}.")
                for pedido, error in notificaciones_fallidas:
                    messages.warning(request, f"{pedido.origen}-{pedido.num_pedido} despachado pero no se notificó: {error}")
                return redirect("pedidos:despachos")

        # Llegó acá solo si falló (parser inexistente, validación, o la API del courier) — se
        # vuelve a mostrar el MISMO formulario con lo que el usuario ya había tipeado, en vez de
        # perderlo con un redirect (que dispara un GET nuevo desde cero, sin el body del POST).
        contexto["post"] = request.POST
        contexto["bultos_previos"] = _bultos_previos(request)
        contexto["documentos_previos"] = _documentos_previos(request)

    return render(request, "pedidos/armar_despacho.html", contexto)
