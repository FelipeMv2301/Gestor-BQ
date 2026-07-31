import re
from collections import defaultdict
from django.conf import settings
from ejecutivos.models import Ejecutivo
from pedidos.services import obtener_datos_contacto_sap
from integraciones import sap_client
from .models import Cotizacion
import logging
logger = logging.getLogger(__name__)

SELECT_COTIZACION = (
    "DocEntry,DocNum,CardCode,CardName,SalesPersonCode,DocDate,DocDueDate,UpdateDate,"
    "DocTotal,VatSum,DocumentStatus,Cancelled,ContactPersonCode,U_TipoVenta,U_BQ_AREA,DocumentLines"
)


def sincronizar_cotizaciones_sap(after=None, before=None):
    cookies = sap_client.obtener_cookies_sap()
    cache_bp = {}
    mapa_ejecutivos = {e.codigo_sap: e for e in Ejecutivo.objects.all()}

    filtros = []
    if after:
        filtros.append(f"UpdateDate ge '{after}'")
    if before:
        filtros.append(f"UpdateDate le '{before}'")
    filtro = " and ".join(filtros)

    params = {"$select": SELECT_COTIZACION}
    if filtro:
        params["$filter"] = filtro

    cotizaciones = sap_client.obtener_todas_las_paginas(
        f"{settings.SAP_URL}/Quotations",
        params,
        cookies,
    )
    
    creadas, actualizadas = _guardar_cotizaciones(cotizaciones, cache_bp, cookies, mapa_ejecutivos)
    return {"creadas": creadas, "actualizadas": actualizadas}


def refrescar_cotizaciones_abiertas():
    # Refresca las que aún pueden cambiar de estado: ABIERTO + PARCIAL.
    docnums = list(
        Cotizacion.objects.filter(
            estado__in=[Cotizacion.Estado.ABIERTO, Cotizacion.Estado.PARCIAL]
        ).values_list("docnum", flat=True)
    )
    if not docnums:
        return {"refrescadas": 0}

    cookies = sap_client.obtener_cookies_sap()
    cache_bp = {}
    mapa_ejecutivos = {e.codigo_sap: e for e in Ejecutivo.objects.all()}

    # 1) Refrescar los datos propios de la cotización (por si se anuló/cambió en SAP)
    for inicio in range(0, len(docnums), 40):
        lote = docnums[inicio:inicio + 40]
        filtro = " or ".join(f"DocNum eq {docnum}" for docnum in lote)
        try:
            cotizaciones_sap = sap_client.obtener_todas_las_paginas(
                f"{settings.SAP_URL}/Quotations",
                {"$select": SELECT_COTIZACION, "$filter": filtro},
                cookies,
            )
        except Exception as exc:
            logger.warning("Error refrescando lote de cotizaciones: %s", exc)
            continue
        _guardar_cotizaciones(cotizaciones_sap, cache_bp, cookies, mapa_ejecutivos)

    # 2) Recalcular facturación + estado (ABIERTO/PARCIAL/COMPLETADO) con datos frescos
    cotizaciones = list(Cotizacion.objects.filter(docnum__in=docnums))
    refrescadas = actualizar_facturacion(cotizaciones, cookies)
    return {"refrescadas": refrescadas}






"""
helpers
"""

def _guardar_cotizaciones(cotizaciones, cache_bp, cookies, mapa_ejecutivos):
    creadas = 0
    actualizadas = 0
    for cotizacion in cotizaciones:
        cotizacion_guardada, fue_creada = Cotizacion.objects.update_or_create(
            docentry=cotizacion.get("DocEntry"),
            defaults={
                "docnum": str(cotizacion.get("DocNum")),
                **_mapear_cotizacion_sap(cotizacion, cache_bp, cookies, mapa_ejecutivos),
            },
        )
        if fue_creada:
            creadas += 1
        else:
            actualizadas += 1
    return creadas, actualizadas

def _mapear_cotizacion_sap(cotizacion, cache_bp, cookies, mapa_ejecutivos=None):
    if mapa_ejecutivos is None:
        mapa_ejecutivos = {e.codigo_sap: e for e in Ejecutivo.objects.all()}

    nombre, telefono, email = obtener_datos_contacto_sap(cotizacion, cache_bp, cookies)
    neto = (cotizacion.get("DocTotal") or 0) - (cotizacion.get("VatSum") or 0)
    doc_status = cotizacion.get("DocumentStatus") or ""
    cancelado = cotizacion.get("Cancelled") == "tYES"

    return {
        "card_code": cotizacion.get("CardCode") or "",
        "rut": re.sub(r"^[A-Za-z]+", "", str(cotizacion.get("CardCode") or "").strip()),
        "card_name": cotizacion.get("CardName") or "",
        "nombre_contacto": nombre,
        "telefono": telefono,
        "email": email,
        "ejecutivo": mapa_ejecutivos.get(cotizacion.get("SalesPersonCode")),
        "tipo_venta": cotizacion.get("U_TipoVenta") or "",
        "area_trabajo": cotizacion.get("U_BQ_AREA") or "",
        "neto": neto,
        "iva": cotizacion.get("VatSum") or 0,
        "total": cotizacion.get("DocTotal") or 0,
        "fecha_contabilizacion": cotizacion.get("DocDate"),
        "fecha_caducidad": cotizacion.get("DocDueDate"),
        "actualizado_sap": cotizacion.get("UpdateDate"),
        "lineas": cotizacion.get("DocumentLines") or [],
        # estado tentativo: en el sync no tenemos aún el facturado; el paso de facturación
        # (calcular_facturado) lo eleva a PARCIAL/COMPLETADO. total_facturado NO va en el mapper
        # (no se pisa en cada sync; lo actualiza el paso de facturación).
        "estado": Cotizacion.Estado.ANULADO if cancelado else Cotizacion.Estado.ABIERTO,
        "doc_status": doc_status,
        "cancelado": cancelado,
    }

def _calcular_estado(cancelado, total_facturado, neto):
    if cancelado:
        return Cotizacion.Estado.ANULADO
    if neto and total_facturado >= neto:
        return Cotizacion.Estado.COMPLETADO
    if total_facturado > 0:
        return Cotizacion.Estado.PARCIAL
    return Cotizacion.Estado.ABIERTO


"""
Trazado de facturación (C3) — portado del sondeo validado sondear_cadena.py.
"""

SELECT_CADENA = "DocEntry,DocNum,DocDate,DocTotal,Cancelled,CardCode,DocumentLines"


def _traer_docs(entidad, card_code, fecha_desde, cookies):
    # Filtro SOLO por cabecera (CardCode/DocDate) — SAP no acepta filtrar por líneas.
    filtro = f"CardCode eq '{card_code}' and DocDate ge '{fecha_desde}'"
    return sap_client.obtener_todas_las_paginas(
        f"{settings.SAP_URL}/{entidad}",
        {"$select": SELECT_CADENA, "$filter": filtro},
        cookies,
    )


def _indexar_lineas(docs):
    # {DocEntry: {LineNum: linea}} — para ubicar la línea base exacta por BaseLine.
    return {d.get("DocEntry"): {l.get("LineNum"): l for l in (d.get("DocumentLines") or [])}
            for d in docs}


def _traza_a_cotizacion(base_type, base_entry, base_line, idx, docentry_cot, depth=0):
    # ¿La línea sube (BaseType/BaseEntry/BaseLine) hasta una línea de la cotización?
    # idx = {13: facturas, 15: guías, 17: órdenes} indexadas por DocEntry→LineNum.
    if depth > 5 or base_entry is None:
        return False
    if base_type == 23:                       # base = Cotización
        return base_entry == docentry_cot
    linea = idx.get(base_type, {}).get(base_entry, {}).get(base_line)   # Factura(13)/Guía(15)/Orden(17)
    if not linea:
        return False
    return _traza_a_cotizacion(linea.get("BaseType"), linea.get("BaseEntry"),
                               linea.get("BaseLine"), idx, docentry_cot, depth + 1)


def _sumar_facturado(docs, idx, docentry_cot):
    # Σ LineTotal de las líneas de `docs` que trazan a la cotización (excluye anulados).
    total = 0.0
    for d in docs:
        if d.get("Cancelled") == "tYES":
            continue
        for l in (d.get("DocumentLines") or []):
            if _traza_a_cotizacion(l.get("BaseType"), l.get("BaseEntry"),
                                   l.get("BaseLine"), idx, docentry_cot):
                total += (l.get("LineTotal") or 0)
    return total


def calcular_facturado(cotizaciones, cookies):
    # {docentry: total_facturado} para una lista de Cotizacion, agrupando por cliente
    # (un solo pull de Orders/Guías/Facturas/NC por CardCode).
    resultado = {}
    por_cliente = defaultdict(list)
    for cot in cotizaciones:
        if cot.card_code and cot.fecha_contabilizacion:
            por_cliente[cot.card_code].append(cot)

    for card_code, cots in por_cliente.items():
        fecha_min = min(c.fecha_contabilizacion for c in cots).isoformat()
        facturas = _traer_docs("Invoices", card_code, fecha_min, cookies)
        notas = _traer_docs("CreditNotes", card_code, fecha_min, cookies)
        idx = {
            17: _indexar_lineas(_traer_docs("Orders", card_code, fecha_min, cookies)),
            15: _indexar_lineas(_traer_docs("DeliveryNotes", card_code, fecha_min, cookies)),
            13: _indexar_lineas(facturas),
        }
        for cot in cots:
            fact = _sumar_facturado(facturas, idx, cot.docentry)
            nc = _sumar_facturado(notas, idx, cot.docentry)
            resultado[cot.docentry] = round(fact - nc, 2)
    return resultado


def actualizar_facturacion(cotizaciones, cookies=None):
    # Calcula total_facturado + recomputa estado (por facturación) y guarda en lote.
    cotizaciones = list(cotizaciones)
    if not cotizaciones:
        return 0
    if cookies is None:
        cookies = sap_client.obtener_cookies_sap()
    facturado = calcular_facturado(cotizaciones, cookies)
    for cot in cotizaciones:
        cot.total_facturado = facturado.get(cot.docentry, 0)
        cot.estado = _calcular_estado(cot.cancelado, cot.total_facturado, cot.neto)
    Cotizacion.objects.bulk_update(cotizaciones, ["total_facturado", "estado"])
    return len(cotizaciones)


def documentos_asociados(cotizacion, cookies=None):
    # Devuelve los documentos de la cadena que trazan a la cotización (para el detalle).
    # {ordenes, facturas, notas} — cada uno lista de {docnum, fecha, total, cancelado}.
    vacio = {"ordenes": [], "facturas": [], "notas": []}
    if not (cotizacion.card_code and cotizacion.fecha_contabilizacion):
        return vacio
    if cookies is None:
        cookies = sap_client.obtener_cookies_sap()

    card_code = cotizacion.card_code
    fecha = cotizacion.fecha_contabilizacion.isoformat()
    docentry = cotizacion.docentry

    ordenes = _traer_docs("Orders", card_code, fecha, cookies)
    guias = _traer_docs("DeliveryNotes", card_code, fecha, cookies)
    facturas = _traer_docs("Invoices", card_code, fecha, cookies)
    notas = _traer_docs("CreditNotes", card_code, fecha, cookies)
    idx = {17: _indexar_lineas(ordenes), 15: _indexar_lineas(guias), 13: _indexar_lineas(facturas)}

    def referencia_cotizacion(doc):
        return any(_traza_a_cotizacion(l.get("BaseType"), l.get("BaseEntry"), l.get("BaseLine"), idx, docentry)
                   for l in (doc.get("DocumentLines") or []))

    def resumir(docs):
        return [{"docnum": d.get("DocNum"), "fecha": d.get("DocDate"),
                 "total": d.get("DocTotal"), "cancelado": d.get("Cancelled") == "tYES"}
                for d in docs if referencia_cotizacion(d)]

    return {"ordenes": resumir(ordenes), "facturas": resumir(facturas), "notas": resumir(notas)}



