from integraciones import woo_client, sap_client
from django.conf import settings
from .models import Pedido
from ejecutivos.models import Ejecutivo
from cuentas.models import PerfilUsuario
from django.forms.models import model_to_dict
from pedidosRechazados.models import PedidoRechazado
from . import permisos

"""
Funciones para WooCommerce
"""

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
    ejecutivo_web = Ejecutivo.objects.filter(codigo_sap=25).first() #Llama a web a través del codigo_sap de la DB y lo mapea automáticamente

    #Llama y filtra a los que pertenezcan a estos dos estados de Woo
    for status in ("processing", "completed"):
        pedidos_woo.extend(woo_client.obtener_pedidos_woo(status, after=after, before=before)) #Llama la función creada en integraciones

    #Almacena la cantidad de pedidos creados y actualizados para control
    creados = 0
    actualizados = 0

    #Captura data de facturación y de envío
    for pedido_woo in pedidos_woo:
        billing = pedido_woo.get("billing", {})
        shipping = pedido_woo.get("shipping", {})

        pedido, creado = Pedido.objects.update_or_create(
            num_pedido = str(pedido_woo.get("number")),
            origen = Pedido.Origen.WEB,
            defaults = {
                "tipo_entrega": definir_tipo_entrega_woo(pedido_woo),
                "ejecutivo": ejecutivo_web,
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
        )
        if creado:
            creados += 1
        
        else:
            actualizados += 1
    
    return {"creados": creados, "actualizados": actualizados}

"""
Funciones para SAP
"""

#Traduce campos de SAP en texto legible por el gestor-bq
def definir_tipo_entrega_sap(orden):
    if orden.get("TransportationCode") == 3:
        return Pedido.TipoEntrega.RETIRO_BIOQUIMICA
    return Pedido.TipoEntrega.DESPACHO

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
          nombre = contacto.get("Name") or f"{contacto.get('FirstName', '')} {contacto.get('LastName', '')}".strip()
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

    filtro = sap_client.agregar_rango_fechas(
        "TransportationCode eq 3 or (TransportationCode eq 1 and (U_BQ_TipoEntrega eq 'HOME' or U_BQ_TipoEntrega eq 'BRANCH'))", 
        "CreationDate", 
        after=after, 
        before=before,
    )

    ordenes = sap_client.obtener_todas_las_paginas(

        f"{settings.SAP_URL}/Orders",
        {
            "$select": "DocNum,TransportationCode,U_BQ_TipoEntrega,U_BQ_CrearEnvio,CardCode,CardName,AddressExtension,SalesPersonCode,Comments,ContactPersonCode",
            "$filter": filtro,
        },
        cookies,
    )

    creados = 0
    actualizados = 0

    for orden in ordenes:
        addr_ext = orden.get("AddressExtension") or {}
        codigo_ejecutivo = orden.get("SalesPersonCode")
        nombre_contacto, telefono_contacto, email_contacto = obtener_datos_contacto_sap(orden, cache_bp, cookies)

        pedido, creado = Pedido.objects.update_or_create(
            num_pedido = str(orden.get("DocNum")),
            origen = Pedido.Origen.SAP,
            defaults = {
                "tipo_entrega": definir_tipo_entrega_sap(orden),
                "nombre_contacto": nombre_contacto,
                "telefono_contacto": telefono_contacto,
                "email_contacto": email_contacto,
                "transportation_code": orden.get("TransportationCode"),
                "u_bq_tipo_entrega": orden.get("U_BQ_TipoEntrega") or "",
                "u_bq_crear_envio": orden.get("U_BQ_CrearEnvio") or "",
                "rut": limpiar_rut_sap(orden.get("CardCode")),
                "razon_social": orden.get("CardName") or "",
                "direccion_calle": addr_ext.get("ShipToStreet") or "",
                "direccion_comuna": addr_ext.get("ShipToCounty", ""),
                "direccion_ciudad": addr_ext.get("ShipToCity") or "",
                "ejecutivo": Ejecutivo.objects.filter(codigo_sap=codigo_ejecutivo).first(),
                "observaciones": orden.get("Comments") or "",
            }
        )

        if creado:
            creados += 1
        else:
            actualizados += 1
    
    return {"creados": creados, "actualizados": actualizados}

"""
Acciones del equipo
"""

#Esta función pasa un pedido de estado PENDIENTE a APROBADO, para que logística pueda trabajarlo. Solo el ejecutivo o admin pueden aprobar.
#Usa el archivo de permisos.py para evaluar que puede y que no puede hacer el usuario.
def aprobar_pedido(pedido, usuario):
      if not permisos.puede_aprobar(usuario, pedido):
          raise PermissionError("[!] Error: Solo el ejecutivo a cargo del pedido, o ADMIN, pueden aprobarlo.")

      if pedido.estado_comercial != Pedido.EstadoComercial.PENDIENTE:
          raise ValueError(f"[!] Error: Solo se puede aprobar un pedido en PENDIENTE. (Actual: {pedido.estado_comercial}).")

      if not pedido.courier:
          raise ValueError("[!] Error: Debes seleccionar un courier antes de aprobar.")

      contacto_valido = bool(pedido.telefono_contacto or pedido.email_contacto)
      direccion_valida = bool(pedido.direccion_calle and pedido.direccion_comuna)
      if not (contacto_valido and direccion_valida):
          raise ValueError("[!] Error: Faltan datos de contacto o dirección válidos.")

      pedido.estado_comercial = Pedido.EstadoComercial.APROBADO
      pedido.save(update_fields=["estado_comercial", "modificado_en"])
      return pedido

#Arma un Snapshot del pedido rechazado
def rechazar_pedido(pedido, motivo, usuario):
    if not permisos.puede_rechazar(usuario, pedido):
        raise PermissionError("[!] Error: Solo un Administrador puede rechazar/cancelar un pedido.")

    snapshot = model_to_dict(pedido)  # copia todos los campos del Pedido a un dict
    PedidoRechazado.objects.create(
        origen=pedido.origen,
        num_pedido=pedido.num_pedido,
        snapshot=snapshot,
        motivo=motivo,
        rechazado_por=usuario,
    )
    pedido.delete()

