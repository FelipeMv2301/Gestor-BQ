from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib import messages
from pedidos.permisos import es_logistica
from cuentas.models import PerfilUsuario
from ejecutivos.models import Ejecutivo
from .models import EnvioCourier
from .services import parsear_bultos, ANULAR_COURIER, anular_envio_courier, marcar_incidencia_envio
from . import reportes
from integraciones.seguimiento import refrescar_estados_courier, actualizar_estado_courier, REFRESCAR_ESTADO_BATCH
from utils import Courier
from pedidos import permisos
from django.urls import reverse
from django.http import HttpResponse
from django.core.paginator import Paginator
import datetime
import io
from pypdf import PdfWriter
from integraciones.documentos import generar_documento, documentos_disponibles, ETIQUETAS_TIPO_DOCUMENTO
import hmac
import json
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt


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


#Batch: refresca el estado-courier de los MoveUP en 1 sola llamada a la API (ver seguimiento.py).
#Logística/Admin refrescan todos; el Ejecutivo solo los suyos (los que agrupan un pedido suyo).
@login_required
@require_POST
def refrescar_estados(request):
    if es_logistica(request.user):
        envios = EnvioCourier.objects.filter(courier__in=REFRESCAR_ESTADO_BATCH.keys())
        destino = "envios:lista"
    elif permisos.obtener_rol(request.user) == PerfilUsuario.Rol.EJECUTIVO:
        codigos = permisos.codigos_sap_usuario(request.user)
        envios = EnvioCourier.objects.de_ejecutivo(codigos).filter(courier__in=REFRESCAR_ESTADO_BATCH.keys())
        destino = "envios:mis_envios"
    else:
        return redirect("inicio")

    total = refrescar_estados_courier(envios)
    messages.success(request, f"Estados de courier actualizados ({total} envío/s).")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = reverse(destino)
    return resp


#Individual: refresca el estado-courier de UN envío (1 llamada). Para el botón del detalle.
#Puede hacerlo cualquiera que pueda VER el envío (Logística/Admin todos; Ejecutivo los suyos).
@login_required
@require_POST
def refrescar_estado_envio(request, pk):
    envio = get_object_or_404(EnvioCourier, pk=pk)
    if not permisos.puede_ver_envio(request.user, envio):
        return redirect("inicio")
    try:
        if actualizar_estado_courier(envio):
            messages.success(request, f"Estado actualizado: {envio.estado_courier or '—'}.")
        else:
            messages.info(request, "Este courier no tiene consulta de estado por API.")
    except Exception as exc:
        messages.error(request, f"No se pudo consultar el estado: {str(exc).replace('[!] Error: ', '')}")
    return redirect("envios:detalle", pk=pk)


#Anula la OF en el courier (hoy solo Starken, ver ANULAR_COURIER) y marca el envío como ANULADO.
#No todos los couriers admiten esto por integración — si no está en ANULAR_COURIER, se avisa en
#pantalla en vez de mostrar un botón que nunca funcionaría.
@login_required
@require_POST
def anular_envio(request, pk):
    if not es_logistica(request.user):
        return redirect("inicio")
    envio = get_object_or_404(EnvioCourier, pk=pk)
    try:
        anular_envio_courier(envio)
        messages.success(request, f"Envío #{envio.id} anulado en {envio.get_courier_display()}.")
    except Exception as exc:
        messages.error(request, f"No se pudo anular: {str(exc).replace('[!] Error: ', '')}")
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


"""
Reporte de envíos (por fecha / courier / ejecutivo) — descargable en Excel o imprimible a PDF.
"""

#Ejecutivos que el usuario puede elegir en el filtro: Logística/Admin ven todos; el Ejecutivo solo
#los suyos (mismos códigos SAP de su perfil).
def _ejecutivos_para(usuario):
    if es_logistica(usuario):
        return Ejecutivo.objects.order_by("nombre")
    if permisos.obtener_rol(usuario) == PerfilUsuario.Rol.EJECUTIVO:
        return Ejecutivo.objects.filter(
            codigo_sap__in=permisos.codigos_sap_usuario(usuario)).order_by("nombre")
    return Ejecutivo.objects.none()


#Lee y limpia los parámetros del reporte desde el GET (compartido por la vista imprimible y el Excel).
def _parametros_reporte(request):
    def _fecha(nombre):
        valor = (request.GET.get(nombre) or "").strip()
        try:
            return datetime.date.fromisoformat(valor) if valor else None
        except ValueError:
            return None

    couriers = request.GET.getlist("courier")
    ejecutivo_ids = [int(x) for x in request.GET.getlist("ejecutivo") if x.isdigit()]
    return _fecha("desde"), _fecha("hasta"), couriers, ejecutivo_ids


@login_required
def reporte_form(request):
    return render(request, "envios/reporte_form.html", {
        "courier_choices": Courier.choices,
        "ejecutivos": _ejecutivos_para(request.user),
    })


@login_required
def reporte_ver(request):
    desde, hasta, couriers, ejecutivo_ids = _parametros_reporte(request)
    filas = reportes.filas_reporte(desde, hasta, couriers, ejecutivo_ids, request.user)
    return render(request, "envios/reporte_ver.html", {
        "filas": filas,
        "desde": desde, "hasta": hasta,
        "total_valor": sum(f["valor_declarado"] for f in filas),
        "total_bultos": sum(f["n_bultos"] for f in filas),
    })


@login_required
def reporte_xlsx(request):
    desde, hasta, couriers, ejecutivo_ids = _parametros_reporte(request)
    filas = reportes.filas_reporte(desde, hasta, couriers, ejecutivo_ids, request.user)
    return reportes.exportar_xlsx(filas)

@login_required
def detalle_envio(request, pk):
    envio = get_object_or_404(EnvioCourier.objects.prefetch_related("pedidos"), pk=pk)
    if not permisos.puede_ver_envio(request.user, envio):
        return redirect("inicio")
    documentos = [(tipo, ETIQUETAS_TIPO_DOCUMENTO.get(tipo, tipo)) for tipo in documentos_disponibles(envio.courier)]
    return render(request, "envios/detalle_envio.html",
                {"envio": envio, "puede_gestionar": es_logistica(request.user),
                    "puede_refrescar": True, "documentos": documentos,
                    "puede_anular": envio.courier in ANULAR_COURIER,
                    "puede_marcar_incidencia": permisos.puede_marcar_incidencia(request.user, envio)})

@login_required
def descargar_documento(request, pk, tipo):
    envio = get_object_or_404(EnvioCourier, pk=pk)
    if not permisos.puede_ver_envio(request.user, envio):
        return redirect("inicio")

    if not envio.orden_transporte:
        messages.error(request, "Este envío no tiene orden de transporte todavía.")
        return redirect("envios:detalle", pk=pk)

    try:
        archivos = generar_documento(envio, tipo)
    except Exception as exc:
        messages.error(request, f"No se pudo generar el documento: {str(exc).replace('[!] Error: ', '')}")
        return redirect("envios:detalle", pk=pk)

    if len(archivos) == 1:
        contenido = archivos[0]
    else:
        # Multibultos: Starken puede devolver una etiqueta por bulto/encargo — se fusionan en un
        # solo PDF de N páginas para poder verlo/imprimirlo igual que el caso de un solo archivo,
        # en vez de forzar un .zip (que no tiene visor nativo en el navegador).
        writer = PdfWriter()
        for pdf_bytes in archivos:
            writer.append(io.BytesIO(pdf_bytes))
        buffer = io.BytesIO()
        writer.write(buffer)
        contenido = buffer.getvalue()

    respuesta = HttpResponse(contenido, content_type="application/pdf")
    respuesta["Content-Disposition"] = f'inline; filename="{tipo}_{envio.orden_transporte}.pdf"'
    return respuesta

@csrf_exempt
@require_POST
def webhook_estado_chibra(request):
    key_recibida = request.headers.get("X-API-KEY", "")
    if not hmac.compare_digest(key_recibida, settings.CHIBRA_WEBHOOK_API_KEY):
        return JsonResponse({"error": "no autorizado"}, status=401)

    try:
        datos = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido"}, status=400)

    orden_transporte = datos.get("orden_transporte")
    envio = EnvioCourier.objects.filter(courier=Courier.CHIBRA,
orden_transporte=orden_transporte).first()
    if not envio:
        return JsonResponse({"error": "envío no encontrado"}, status=404)

    estado = (datos.get("estado") or {}).get("descripcion") or ""
    envio.estado_courier = estado
    envio.estado_courier_actualizado = timezone.now()
    envio.save(update_fields=["estado_courier", "estado_courier_actualizado"])

    return JsonResponse({"ok": True})

@login_required
@require_POST
def marcar_incidencia(request, pk):
    envio = get_object_or_404(EnvioCourier, pk=pk)
    if not permisos.puede_marcar_incidencia(request.user, envio):
        return redirect("inicio")

    motivo = request.POST.get("motivo", "").strip()
    if not motivo:
        messages.error(request, "Tenés que indicar un motivo para reportar la incidencia.")
        return redirect("envios:detalle", pk=pk)

    marcar_incidencia_envio(envio, motivo, request.user)
    messages.success(request, "Incidencia reportada — los pedidos quedaron liberados para un nuevo despacho.")
    return redirect("envios:lista")