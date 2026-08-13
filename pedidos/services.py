import logging
from integraciones import woo_client, sap_client, email_client
from django.conf import settings
from .models import Pedido, SkuCourier, Aviso
from ejecutivos.models import Ejecutivo
from django.forms.models import model_to_dict
from pedidosRechazados.models import PedidoRechazado
from . import permisos
import datetime
from django.db import transaction
from django.db.models import Q
from cuentas.models import PerfilUsuario
from utils import Courier

logger = logging.getLogger(__name__)

#Arma las opciones de courier+servicio combinadas en una sola ("CHIBRA|10" -> "Chibra — Express"),
#leyendo los servicios configurados en SkuCourier. Reusado por PedidoEditForm y por el select rápido
#de la tabla (_celda_courier.html) — un solo lugar decide qué combinaciones existen.
def opciones_courier_servicio():
    filas_servicio = (
        SkuCourier.objects.exclude(servicio_codigo="")
        .values_list("courier", "servicio_codigo", "servicio_nombre").distinct()
        .order_by("courier", "servicio_nombre")
    )
    etiquetas_courier = dict(Courier.choices)

    opciones = [("", "— Sin courier —")]
    couriers_con_servicio = set()
    for courier_valor, codigo, nombre in filas_servicio:
        etiqueta_courier = etiquetas_courier.get(courier_valor, courier_valor)
        opciones.append((f"{courier_valor}|{codigo}", f"{etiqueta_courier} — {nombre}"))
        couriers_con_servicio.add(courier_valor)
    # Solo la versión "pelada" de los couriers SIN servicios configurados: los que ya salieron con
    # sus variantes (ej. Chibra — Express/Terrestre) no se repiten sueltos.
    for courier_valor, etiqueta_courier in Courier.choices:
        if courier_valor in couriers_con_servicio:
            continue
        opciones.append((courier_valor, f"{etiqueta_courier}"))
    return opciones

"""
Funciones para WooCommerce
"""

#Herramienta que ayuda a estandarizar el mapeo de woo
def _mapear_pedido_woo(pedido_woo, mapa_comunas, ejecutivo_web):
    billing = pedido_woo.get("billing", {})
    shipping = pedido_woo.get("shipping", {})
    return{
        "tipo_entrega": definir_tipo_entrega_woo(pedido_woo),
        "ejecutivo": ejecutivo_web,
        "estado_comercial": Pedido.EstadoComercial.APROBADO,
        "rut": billing.get("tax_id", ""),
        "razon_social": billing.get("company", ""),
        "nombre_contacto": f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip(),
        "telefono_contacto": billing.get("phone", ""),
        "email_contacto": billing.get("email", ""),
        "direccion_calle": shipping.get("address_1", ""),
        "direccion_depto": shipping.get("address_2", ""),
        "direccion_comuna": mapa_comunas.get(shipping.get("state", ""), shipping.get("state", "")),
        "direccion_ciudad": shipping.get("city", ""),
        "observaciones": pedido_woo.get("customer_note", ""),
    }

#Valida si es Despacho o Retiro por pedido para WooCommerce
def definir_tipo_entrega_woo(pedido_woo):
    shipping_lines = pedido_woo.get("shipping_lines", [])
    metodo = shipping_lines[0].get("method_id", "") if shipping_lines else ""

    if "pickup" in metodo:
        return Pedido.TipoEntrega.RETIRO_BIOQUIMICA
    return Pedido.TipoEntrega.DESPACHO

def guardar_pedidos_woo(after=None, before=None):
    mapa_comunas = woo_client.obtener_mapa_comunas()
    pedidos_woo = []
    ejecutivo_web = Ejecutivo.objects.filter(codigo_sap=settings.EJECUTIVO_WEB_SAP).first() #Llama a web a través del codigo_sap de la DB y lo mapea automáticamente

    #Llama y filtra a los que pertenezcan a estos dos estados de Woo
    for status in ("processing", "completed"):
        pedidos_woo.extend(woo_client.obtener_pedidos_woo(status, after=after, before=before)) #Llama la función creada en integraciones

    #Almacena la cantidad de pedidos creados y actualizados para control
    creados = 0
    omitidos = 0

    #Captura data de facturación y de envío
    for pedido_woo in pedidos_woo:
        num_pedido = str(pedido_woo.get("number"))

        if pedido_ya_existe(Pedido.Origen.WEB, num_pedido):
            omitidos += 1
            continue

        if pedido_fue_rechazado(Pedido.Origen.WEB, num_pedido):
            omitidos += 1
            continue

        Pedido.objects.create(
            num_pedido=num_pedido,
            origen=Pedido.Origen.WEB,
            **_mapear_pedido_woo(pedido_woo, mapa_comunas, ejecutivo_web),
        )
        creados += 1
    
    return {"creados": creados, "omitidos":omitidos}

def guardar_un_pedido_woo(num_pedido, ignorar_rechazado=False):
    pedido_woo = woo_client.obtener_un_pedido_woo(num_pedido)
    if pedido_woo is None:
        raise ValueError(f"[!] Error: No se encontró el pedido WEB-{num_pedido} en WooCommerce.")

    if pedido_ya_existe(Pedido.Origen.WEB, num_pedido):
       raise ValueError(f"[!] Error: El pedido WEB-{num_pedido} ya existe. Puedes editarlo en la misma aplicación.")

    if not ignorar_rechazado and pedido_fue_rechazado(Pedido.Origen.WEB, num_pedido):
        raise ValueError(f"[!] Error: El pedido WEB-{num_pedido} ya fue rechazado antes, no se puede volver a ingresar.")
    
    mapa_comunas = woo_client.obtener_mapa_comunas()
    ejecutivo_web = Ejecutivo.objects.filter(codigo_sap=settings.EJECUTIVO_WEB_SAP).first()

    billing = pedido_woo.get("billing" ,{})
    shipping = pedido_woo.get("shipping", {})

    Pedido.objects.create(
        num_pedido=str(pedido_woo.get("number")),
        origen=Pedido.Origen.WEB,
        **_mapear_pedido_woo(pedido_woo, mapa_comunas, ejecutivo_web),
    )
    return f"Pedido WEB-{num_pedido} creado desde WooCommerce."
    


"""
Funciones para SAP
"""

#Herramienta que ayuda a estandarizar el mapeo de SAP
def _mapear_orden_sap(orden, cache_bp, cookies, mapa_sku=None, mapa_ejecutivos=None):
    if mapa_sku is None:
        mapa_sku = _armar_mapa_sku()

    if mapa_ejecutivos is None:
        mapa_ejecutivos = {e.codigo_sap: e for e in Ejecutivo.objects.all()}

    addr_ext = orden.get("AddressExtension") or {}
    nombre, telefono, email = obtener_datos_contacto_sap(orden, cache_bp, cookies)
    deteccion = detectar_courier_sap(orden, mapa_sku)
    return{
        "estado_comercial": Pedido.EstadoComercial.APROBADO,  # mismo trato que Woo (_mapear_pedido_woo): pasa directo a Logística
        "tipo_entrega": definir_tipo_entrega_sap(orden),
        "nombre_contacto": nombre,
        "telefono_contacto": telefono,
        "email_contacto": email,
        "courier": deteccion["courier"],
        "servicio_courier_codigo": deteccion["servicio_codigo"],
        "servicio_courier_nombre": deteccion["servicio_nombre"],
        "transportation_code": orden.get("TransportationCode"),
        "u_bq_tipo_entrega": orden.get("U_BQ_TipoEntrega") or "",
        "u_bq_crear_envio": orden.get("U_BQ_CrearEnvio") or "",
        "rut": limpiar_rut_sap(orden.get("CardCode")),
        "razon_social": orden.get("CardName") or "",
        "direccion_calle": addr_ext.get("ShipToStreet") or "",
        #`or ""` y NO `.get("ShipToCounty", "")`: el default de .get solo aplica si la clave FALTA, y
        #SAP manda la clave presente con valor null en NV sin dirección de destino. Eso metía None en
        #un CharField sin null=True → NotNullViolation, que en Postgres tumbaba la ingesta entera
        #(en la carga individual salía como 500). Detectado con la NV 2601790 el 2026-08-13.
        "direccion_comuna": addr_ext.get("ShipToCounty") or "",
        "direccion_ciudad": addr_ext.get("ShipToCity") or "",
        "ejecutivo": mapa_ejecutivos.get(orden.get("SalesPersonCode")),
        "observaciones": orden.get("Comments") or "",
    }


#Traduce campos de SAP en texto legible por el gestor-bq
def definir_tipo_entrega_sap(orden):
    if orden.get("TransportationCode") == 3:
        return Pedido.TipoEntrega.RETIRO_BIOQUIMICA
    return Pedido.TipoEntrega.DESPACHO

#Arma el mapa sku -> {courier, servicio_codigo, servicio_nombre} desde SkuCourier.
def _armar_mapa_sku():
    return {
        s.sku: {"courier": s.courier, "servicio_codigo": s.servicio_codigo, "servicio_nombre": s.servicio_nombre}
        for s in SkuCourier.objects.all()
    }

#Detecta courier + servicio a través del SKU del despacho.
def detectar_courier_sap(orden, mapa_sku):
    for linea in (orden.get("DocumentLines") or []):
        item_code = (linea.get("ItemCode") or "").upper()
        if item_code in mapa_sku:
            return mapa_sku[item_code]
    return {"courier": "", "servicio_codigo": "", "servicio_nombre": ""}

def limpiar_rut_sap(card_code):
      if not card_code:
          return ""
      texto = str(card_code).strip()
      if texto.upper().startswith("CN"):
          return texto[2:]
      return texto

def obtener_datos_contacto_sap(orden, cache_bp, cookies):
      card_code = orden.get("CardCode")
      contact_code = orden.get("ContactPersonCode")

      if card_code not in cache_bp:
          cache_bp[card_code] = sap_client.obtener_business_partner(card_code, cookies)
      bp = cache_bp[card_code]

      contactos = bp.get("ContactEmployees") or []
      contacto = next((c for c in contactos if c.get("InternalCode") == contact_code), None)

      if contacto:
          nombre = f"{contacto.get('FirstName', '')} {contacto.get('LastName', '')}".strip()
          email = contacto.get("E_Mail") or bp.get("EmailAddress") or ""
          telefono = contacto.get("MobilePhone") or contacto.get("Phone1") or bp.get("Phone1") or ""
      else:
          nombre = ""
          email = bp.get("EmailAddress") or ""
          telefono = bp.get("Phone1") or ""

      return nombre, telefono, email

def guardar_pedidos_sap(after=None, before=None):
    cookies = sap_client.obtener_cookies_sap()
    cache_bp = {}

    mapa_sku = _armar_mapa_sku()
    mapa_ejecutivos = {e.codigo_sap: e for e in Ejecutivo.objects.all()}

    #El retiro en Bioquímica (TransportationCode 3) entra SIEMPRE, sin exigir U_BQ_CrearEnvio: el campo
    #se llama "Crear Envío" y en un retiro no hay envío que crear, así que Comercial lo deja en 'N' con
    #toda lógica y el pedido nunca llegaba a Logística (visto en vivo: NV 2601820 y 2601832, retiros
    #reales excluidos solo por el flag). El flag queda como compuerta únicamente de la rama de courier.
    #Decisión de Felipe 2026-08-13; reemplaza la del 2026-07-22, que lo exigía para ambas ramas.
    #El `Cancelled eq 'tNO'` va en la rama de retiro porque, al sacarle el flag, esa rama quedaba sin
    #ninguna compuerta y entraban también los retiros anulados. La rama de courier no lo lleva: ahí el
    #flag ya acota, y agregarlo cambiaría un comportamiento que hoy funciona.
    filtro = sap_client.agregar_rango_fechas(
        "(TransportationCode eq 3 and Cancelled eq 'tNO')"
        " or (U_BQ_CrearEnvio eq 'Y' and TransportationCode eq 1"
        " and (U_BQ_TipoEntrega eq 'HOME' or U_BQ_TipoEntrega eq 'BRANCH'))",
        "UpdateDate",
        after=after,
        before=before,
    )

    ordenes = sap_client.obtener_todas_las_paginas(

        f"{settings.SAP_URL}/Orders",
        {
            "$select": "DocNum,TransportationCode,U_BQ_TipoEntrega,U_BQ_CrearEnvio,CardCode,CardName,AddressExtension,SalesPersonCode,Comments,ContactPersonCode,DocumentLines",
            "$filter": filtro,
        },
        cookies,
    )

    creados = 0
    omitidos = 0
    fallidos = 0

    for orden in ordenes:
        num_pedido = str(orden.get("DocNum"))

        if pedido_ya_existe(Pedido.Origen.SAP, num_pedido):
            omitidos += 1
            continue
        if pedido_fue_rechazado(Pedido.Origen.SAP, num_pedido):
            omitidos += 1
            continue

        #Una NV con datos que el modelo no acepta no puede matar el lote entero. Antes, cualquier
        #excepción acá abortaba el `for` y las órdenes que venían DESPUÉS no se procesaban nunca
        #(el cron solo dejaba un "falló la sincronización" sin decir en qué NV). Ahora se cuenta,
        #se loguea con su DocNum y se sigue. El `atomic` de a una es un savepoint: sin él, un
        #INSERT fallido deja la transacción abortada y las consultas siguientes también revientan.
        try:
            with transaction.atomic():
                Pedido.objects.create(
                    num_pedido=num_pedido,
                    origen=Pedido.Origen.SAP,
                    **_mapear_orden_sap(orden, cache_bp, cookies, mapa_sku, mapa_ejecutivos),
                )
        except Exception:
            fallidos += 1
            logger.exception("Ingesta SAP: la NV %s falló, se omite y se sigue con el resto.", num_pedido)
            continue

        creados += 1

    return {"creados": creados, "omitidos": omitidos, "fallidos": fallidos}

def guardar_un_pedido_sap(num_pedido, ignorar_rechazado=False):
    cookies = sap_client.obtener_cookies_sap()
    orden = sap_client.obtener_un_resultado(
        f"{settings.SAP_URL}/Orders",
        {
            "$select": "DocNum,TransportationCode,U_BQ_TipoEntrega,U_BQ_CrearEnvio,CardCode,CardName,AddressExtension,SalesPersonCode,Comments,ContactPersonCode,DocumentLines",
            "$filter": f"DocNum eq {num_pedido}",
        },
        cookies,
    )
    if orden is None:
        raise ValueError(f"[!] Error: No se encontró el pedido SAP-{num_pedido} en SAP.")
    
    if pedido_ya_existe(Pedido.Origen.SAP, num_pedido):
        raise ValueError(f"[!] Error: El pedido SAP-{num_pedido} ya existe. Puedes editarlo en la misma aplicación.")

    if not ignorar_rechazado and pedido_fue_rechazado(Pedido.Origen.SAP, num_pedido):
        raise ValueError(f"[!] Error: El pedido SAP-{num_pedido} ya fue rechazado antes, no se puede volver a ingresar.")

    cache_bp = {}
    Pedido.objects.create(
        num_pedido=str(orden.get("DocNum")),
        origen=Pedido.Origen.SAP,
        **_mapear_orden_sap(orden, cache_bp, cookies),
    )
    return f"Pedido SAP-{num_pedido} creado desde SAP."


"""
Acciones del equipo
"""

#Arma un Snapshot del pedido rechazado
def rechazar_pedido(pedido, motivo, usuario):
    if not permisos.puede_rechazar(usuario, pedido):
        raise PermissionError("[!] Error: Solo un Administrador puede rechazar/cancelar un pedido.")

    snapshot = model_to_dict(pedido)  # copia todos los campos del Pedido a un dict

    with transaction.atomic():
        PedidoRechazado.objects.create(
            origen=pedido.origen, num_pedido=pedido.num_pedido,
            snapshot=snapshot, motivo=motivo, rechazado_por=usuario,
        )
        _avisar_ejecutivo(pedido, Aviso.Tipo.ANULADO,
                          f"Tu pedido {pedido.origen}-{pedido.num_pedido} fue anulado."
                          + (f" Motivo: {motivo}" if motivo else ""))
        pedido.delete()

#Reingresa un pedido anulado desde la fuente (SAP/Woo). Borra el archivo solo si la re-ingesta tuvo éxito.
def reingresar_pedido(rechazado):
    if rechazado.origen == Pedido.Origen.SAP:
        mensaje = guardar_un_pedido_sap(rechazado.num_pedido, ignorar_rechazado=True)
    else:
        mensaje = guardar_un_pedido_woo(rechazado.num_pedido, ignorar_rechazado=True)
    rechazado.delete()
    return mensaje


def notificar_pedido(pedido, usuario):
    if not permisos.puede_notificar(usuario, pedido):
        raise PermissionError("[!] Error: Solo Logística o Admin pueden notificar, y solo sobre un pedido APROBADO.")
    
    if pedido.estado_notificacion == Pedido.EstadoNotificacion.NOTIFICADO:
        raise ValueError(f"[!] Error: Pedido N° {pedido.origen}-{pedido.num_pedido} ya fue notificado") 
    
    email_client.enviar_notificacion(pedido)

    pedido.estado_notificacion = Pedido.EstadoNotificacion.NOTIFICADO
    pedido.save(update_fields=["estado_notificacion", "modificado_en"])

    referencia = f"{pedido.origen}-{pedido.num_pedido}"
    if pedido.tipo_entrega == Pedido.TipoEntrega.RETIRO_BIOQUIMICA:
        mensaje = f"Tu pedido {referencia} está disponible para retiro y el cliente fue notificado."
    else:
        mensaje = f"Tu pedido {referencia} fue despachado a courier y el cliente notificado."
    _avisar_ejecutivo(pedido, Aviso.Tipo.NOTIFICADO, mensaje)
    return pedido

"""
Funciones reutilizables
"""

#Valida si un pedido está en la lista de rechazados
def pedido_fue_rechazado(origen, num_pedido):
    return PedidoRechazado.objects.filter(origen=origen, num_pedido=num_pedido).exists()

#Valida si un pedido ya existe en el sistema para evitar un upsert que pise la base de datos actual
def pedido_ya_existe(origen, num_pedido):
    return Pedido.objects.filter(origen=origen, num_pedido=num_pedido).exists()

#Crea un aviso para el/los usuario(s) dueños del pedido (fan-out por codigo_sap del ejecutivo).
#Matchea por la M2M `ejecutivos` o por el escalar legacy — un perfil puede tener el código en cualquiera.
def _avisar_ejecutivo(pedido, tipo, mensaje):
    if pedido.ejecutivo_id is None:
        return
    codigo = pedido.ejecutivo.codigo_sap
    perfiles = PerfilUsuario.objects.filter(
        Q(ejecutivos__codigo_sap=codigo) | Q(codigo_empleado_sap=codigo)
    ).select_related("usuario").distinct()
    Aviso.objects.bulk_create([
        Aviso(destinatario=p.usuario, tipo=tipo, mensaje=mensaje,
              origen=pedido.origen, num_pedido=pedido.num_pedido, pedido=pedido)
        for p in perfiles
    ])

#Para el cron: trae lo del día anterior + el actual (mismo filtro UpdateDate que ya usa guardar_pedidos_sap).
def sincronizar_sap_reciente():
    hoy = datetime.date.today()
    ayer = hoy - datetime.timedelta(days=1)
    return guardar_pedidos_sap(after=ayer.isoformat(), before=hoy.isoformat())

#Mismo criterio de rango que sincronizar_sap_reciente, pero Woo exige datetime ISO completo (con hora), no fecha simple.
def sincronizar_woo_reciente():
    hoy = datetime.date.today()
    ayer = hoy - datetime.timedelta(days=1)
    return guardar_pedidos_woo(after=f"{ayer.isoformat()}T00:00:00", before=f"{hoy.isoformat()}T23:59:59")