from collections import defaultdict
from django.conf import settings
from django.utils import timezone
from utils import Courier
from integraciones import moveup_client, starken_client

"""
Seguimiento de envíos por courier (URL de tracking + estado por API).

Un registro por capacidad; cada courier se inscribe solo en las que soporta. El .get(courier)
degrada con gracia (courier sin entrada → None / "—", no rompe). Sumar un courier custom = registrar
su función solo en las capacidades que tenga.

Ojo: este módulo NO importa envios.models (recibe objetos `envio` y hace envio.save()), para que el
modelo pueda importar url_portal_courier/url_seguimiento_publico en properties sin ciclo de imports.
"""

# --- Portal interno del courier (donde LOGÍSTICA gestiona/opera los envíos) ---
PORTAL_COURIER_URL = {
    Courier.CHIBRA: lambda envio: f"{settings.CHIBRA_BASE_URL.rstrip('/')}/gts/priv/expediciones/busqueda_avanzada.seam",   # panel privado de gestión
    Courier.MOVEUP: lambda envio: "https://moveuplogistica.firebaseapp.com/client/packages/view-packages",   # panel de gestión de paquetes
    Courier.STARKEN: lambda envio: "https://starkenpro.cl/dashboard-pro",   # portal STK Pro Empresa
}

# --- Seguimiento público (el que ve el CLIENTE FINAL para rastrear su pedido) ---
SEGUIMIENTO_PUBLICO_URL = {
    Courier.STARKEN: lambda envio: f"https://www.starken.cl/seguimiento?codigo={envio.orden_transporte}",
    # Chibra/MoveUP: sin seguimiento público documentado todavía.
}

def url_portal_courier(envio):
    fn = PORTAL_COURIER_URL.get(envio.courier)
    return fn(envio) if fn and envio.orden_transporte else None


def url_seguimiento_publico(envio):
    fn = SEGUIMIENTO_PUBLICO_URL.get(envio.courier)
    return fn(envio) if fn and envio.orden_transporte else None


# --- Estado por API: individual (para el botón "refrescar este" del detalle, 1 llamada) ---
CONSULTAR_ESTADO_COURIER = {
    Courier.MOVEUP: lambda envio: moveup_client.estado_paquete(envio.orden_transporte),
    Courier.STARKEN: lambda envio: starken_client.consultar_estado(envio.orden_transporte),
    # Chibra: cuando tengan API de estado
}


def actualizar_estado_courier(envio):
    # Refresca UN envío (1 llamada a la API). Para el detalle individual.
    fn = CONSULTAR_ESTADO_COURIER.get(envio.courier)
    if not fn or not envio.orden_transporte:
        return False
    envio.estado_courier = fn(envio) or ""
    envio.estado_courier_actualizado = timezone.now()
    envio.save(update_fields=["estado_courier", "estado_courier_actualizado"])
    return True


# --- Estado por API: batch (para la lista / cron) — 1 sola llamada por courier, no O(N) ---
def _refrescar_estado_moveup_batch(envios):
    envios = list(envios)
    if not envios:
        return 0
    fecha_min = min(e.creado_en for e in envios).date().isoformat()
    hoy = timezone.now().date().isoformat()
    paquetes = moveup_client.consultar_envios(desde=fecha_min, hasta=hoy)   # 1 sola /search
    por_id = {str(p.get("id")): (p.get("packageStatus") or "") for p in paquetes}

    actualizados = 0
    for envio in envios:
        estado = por_id.get(str(envio.orden_transporte))
        if estado is not None:   # solo si MoveUP conoce ese id (si no, no pisar)
            envio.estado_courier = estado
            envio.estado_courier_actualizado = timezone.now()
            envio.save(update_fields=["estado_courier", "estado_courier_actualizado"])
            actualizados += 1
    return actualizados


#Starken: 1 sola llamada a Etracking para todas las OF del lote (mismo criterio que MoveUP).
def _refrescar_estado_starken_batch(envios):
    envios = [e for e in envios if e.orden_transporte]
    if not envios:
        return 0

    estados = starken_client.consultar_estados_batch([e.orden_transporte for e in envios])

    actualizados = 0
    for envio in envios:
        estado = estados.get(str(envio.orden_transporte))
        if estado is not None:   # solo si Starken devolvió esa OF (codigoSalida == 1), no pisar si no
            envio.estado_courier = estado
            envio.estado_courier_actualizado = timezone.now()
            envio.save(update_fields=["estado_courier", "estado_courier_actualizado"])
            actualizados += 1
    return actualizados


REFRESCAR_ESTADO_BATCH = {
    Courier.MOVEUP: _refrescar_estado_moveup_batch,
    Courier.STARKEN: _refrescar_estado_starken_batch,
}


def refrescar_estados_courier(envios):
    # Agrupa por courier y usa el batch de cada uno (MoveUP = 1 sola /search por corrida).
    por_courier = defaultdict(list)
    for envio in envios:
        por_courier[envio.courier].append(envio)

    total = 0
    for courier, lote in por_courier.items():
        fn = REFRESCAR_ESTADO_BATCH.get(courier)
        if fn:
            try:
                total += fn(lote)
            except Exception:
                pass   # un courier que falle no tumba a los demás
    return total
