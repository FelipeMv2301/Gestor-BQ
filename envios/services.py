from .models import EnvioCourier
from integraciones import chibra_client, moveup_client, starken_client
from pedidos.models import Pedido
from pedidos.services  import notificar_pedido
from django.db import transaction
from utils import Courier, normalizar_telefono_cl, es_movil_cl


"""
Helpers
"""
def _despachar_chibra(pedidos, destinatario, datos_courier):
    resultado = chibra_client.documentar_envio(
        pedidos, datos_courier.get("bultos", []), destinatario, datos_courier
    )
    return {"orden_transporte": resultado["numero_envio"]}

def _despachar_starken(pedidos, destinatario, datos_courier):
    resultado = starken_client.emitir_of(
        pedidos, datos_courier.get("bultos", []), destinatario, datos_courier
    )
    return {"orden_transporte": resultado["numero_orden_flete"]}

def _despachar_sin_integracion(pedidos, destinatario, datos_courier):
    # Sin API: el envío se crea igual; la OT es la que ingresó Logística (o vacía).
    return {"orden_transporte": datos_courier.get("orden_transporte", "")}

def _parsear_despacho_simple(request):
    # Bultos opcionales: solo se arma un bulto si ingresaron cantidad o peso; si no, lista vacía.
    cantidad = request.POST.get("simple_cantidad")
    peso = request.POST.get("simple_peso_total")
    bultos = []
    if cantidad or peso:
        bultos = [{"tipo": "CAJA", "cantidad": int(cantidad or 1),
                    "alto": "", "ancho": "", "largo": "",
                    "peso": float(peso or 0), "tipo_contenido": "SECO"}]
    datos_courier = {
        "orden_transporte": (request.POST.get("orden_transporte") or "").strip(),
        "valor_declarado": request.POST.get("valor_declarado") or 0,
        "observaciones": request.POST.get("observaciones") or "",
    }
    return bultos, {}, datos_courier   # destinatario {} → estos couriers no arman payload

def _despachar_moveup(pedidos, destinatario, datos_courier):
    # MoveUP no tiene campo de referencia externa → las referencias de pedido (num_pedido / DocNum SAP)
    # van en observations, como hace MoveUP mismo ("OrderNumber: ...").
    refs = ", ".join(f"{p.origen}-{p.num_pedido}" for p in pedidos)
    obs_operador = datos_courier.get("observaciones") or ""
    observations = f"Pedidos: {refs}"
    if obs_operador:
        observations += f" | {obs_operador}"

    paquete = {
        "recipientName": destinatario.get("nombre") or "",
        "recipientAddress": destinatario.get("direccion") or "",
        "recipientAddressNumber": destinatario.get("numero") or "",
        "recipientHouseNumber": destinatario.get("depto") or "",
        "recipientCommune": destinatario.get("comuna") or "",
        "recipientPhone": normalizar_telefono_cl(destinatario.get("telefono") or ""),
        "recipientEmail": destinatario.get("email") or "",
        "packagePrice": int(datos_courier.get("valor_declarado") or 0),
        "packageSize": int(datos_courier.get("package_size") or moveup_client.PACKAGE_SIZE_CAJA),
        "packageQuantity": int(datos_courier.get("cantidad") or 1),
        "observations": observations,
    }

    creados = moveup_client.crear_paquetes(paquete)
    primero = creados[0] if creados else {}
    return {"orden_transporte": str(primero.get("id") or "")}

SELECCIONAR_COURIER = {
    Courier.CHIBRA: _despachar_chibra,
    Courier.MOVEUP: _despachar_moveup,
    Courier.BIOQUIMICACL: _despachar_sin_integracion,
    Courier.CYS: _despachar_sin_integracion,
    Courier.STARKEN: _despachar_starken
}

def _parsear_despacho_chibra(request):
    bultos = parsear_bultos(request)
    destinatario = {
        "nombre": request.POST.get("destinatario_nombre"),
        "rut": request.POST.get("destinatario_rut"),
        "direccion": request.POST.get("destinatario_direccion"),
        "comuna": request.POST.get("destinatario_comuna"),
        "telefono": request.POST.get("destinatario_telefono"),
        "email": request.POST.get("destinatario_email"),
    }

    tipos_doc = request.POST.getlist("doc_tipo")
    refs_doc = request.POST.getlist("doc_referencia")
    documentos = [{"tipo": t.strip(), "referencia": r.strip()}
                  for t, r in zip(tipos_doc, refs_doc) if t.strip() and r.strip()]

    datos_courier = {
        "centro": request.POST.get("centro"),
        "servicio": request.POST.get("servicio"),
        "valor_declarado": request.POST.get("valor_declarado") or 0,
        "volumen_total": request.POST.get("volumen_total"),
        "observaciones": request.POST.get("observaciones"),
        "documentos": documentos,   # cedibles → chibra_client los pone en TIPOS_DOCUMENTO
    }

    return bultos, destinatario, datos_courier

def _parsear_despacho_moveup(request):
    destinatario = {
        "nombre": request.POST.get("destinatario_nombre"),
        "rut": request.POST.get("destinatario_rut"),
        "comuna": request.POST.get("destinatario_comuna"),
        "telefono": request.POST.get("destinatario_telefono"),
        "email": request.POST.get("destinatario_email"),
        "direccion": request.POST.get("moveup_calle"),
        "numero": request.POST.get("moveup_numero"),
        "depto": request.POST.get("moveup_depto"),
    }

    datos_courier = {
        "package_size": request.POST.get("package_size"),
        "cantidad": request.POST.get("cantidad") or 1,
        "valor_declarado": request.POST.get("valor_declarado") or 0,
        "observaciones": request.POST.get("observaciones"),
    }

    faltantes = [etiqueta for campo, etiqueta in
                [("nombre", "Nombre"), ("direccion", "Calle"), ("numero", "Número"), ("comuna", "Comuna")]
                if not (destinatario.get(campo) or "").strip()]
    if faltantes:
          raise ValueError(f"Faltan datos para MoveUP: {', '.join(faltantes)}.")

    #MoveUP solo acepta el móvil como 9 dígitos partiendo en 9 (sin +56). Normalizamos los formatos
    #buenos-pero-sucios y validamos antes de despachar, para fallar con mensaje claro en vez de un 400.
    telefono = normalizar_telefono_cl(destinatario.get("telefono"))
    if not es_movil_cl(telefono):
        raise ValueError(
            f"Teléfono inválido para MoveUP (móvil de 9 dígitos partiendo en 9): {destinatario.get('telefono')}"
        )
    destinatario["telefono"] = telefono   # ya normalizado, listo para _despachar_moveup

    return [], destinatario, datos_courier

def _parsear_despacho_starken(request):
    bultos = parsear_bultos(request)
    codigo_agencia_destino = (request.POST.get("codigo_agencia_destino") or "").strip() or None
    destinatario = {
        "nombre": request.POST.get("destinatario_nombre"),
        "rut": request.POST.get("destinatario_rut"),
        "direccion": request.POST.get("starken_calle"),
        "numero": request.POST.get("starken_numero"),
        "depto": request.POST.get("starken_depto"),
        "comuna": request.POST.get("destinatario_comuna"),
        "telefono": request.POST.get("destinatario_telefono"),
        "email": request.POST.get("destinatario_email"),
    }

    # Retiro en agencia: la dirección del destinatario no aplica (se retira en la agencia,
    # identificada por su código) — solo se exige en modo domicilio.
    campos_requeridos = [("nombre", "Nombre")]
    if not codigo_agencia_destino:
        campos_requeridos += [("direccion", "Calle"), ("numero", "Número"), ("comuna", "Comuna")]
    faltantes = [etiqueta for campo, etiqueta in campos_requeridos if not (destinatario.get(campo) or "").strip()]
    if faltantes:
        raise ValueError(f"Faltan datos para Starken: {', '.join(faltantes)}.")

    tipos_doc = request.POST.getlist("doc_tipo")
    numeros_doc = request.POST.getlist("doc_numero")
    documentos = [{"tipo": t.strip(), "numero": n.strip()}
                for t, n in zip(tipos_doc, numeros_doc) if t.strip() and n.strip()]

    datos_courier = {
        "valor_declarado": request.POST.get("valor_declarado") or 0,
        "servicio": request.POST.get("servicio") or "0",
        "observaciones": request.POST.get("observaciones"),
        "documentos": documentos,
        "codigo_agencia_destino": codigo_agencia_destino,
        "contenido": (request.POST.get("contenido") or "").strip() or None,
    }

    return bultos, destinatario, datos_courier

PARSEAR_DESPACHO = {
    Courier.CHIBRA: _parsear_despacho_chibra,
    Courier.MOVEUP: _parsear_despacho_moveup,
    Courier.BIOQUIMICACL: _parsear_despacho_simple,
    Courier.CYS: _parsear_despacho_simple,
    Courier.STARKEN: _parsear_despacho_starken
}

#Registro por capacidad, igual criterio que SELECCIONAR_COURIER: un courier se inscribe solo si su
#integración admite anular una OF ya emitida. Chibra/MoveUP/CYS/Bioquimica.cl no están — no hay API
#de anulación documentada para ellos, así que la acción no aparece en el detalle del envío.
ANULAR_COURIER = {
    Courier.STARKEN: lambda envio: starken_client.anular_of(envio.orden_transporte),
}

def anular_envio_courier(envio):
    fn = ANULAR_COURIER.get(envio.courier)
    if not fn:
        raise ValueError(f"[!] Error: {envio.courier} no admite anulación por integración.")
    if not envio.orden_transporte:
        raise ValueError("[!] Error: este envío no tiene orden de transporte todavía.")

    fn(envio)
    envio.estado = EnvioCourier.Estado.ANULADO
    envio.save(update_fields=["estado", "actualizado_en"])

#Valida que un grupo de pedidos pueda agruparse en un solo despacho. Se usa apenas se selecciona
#el grupo (para fallar rápido, antes de mostrar el formulario) y de nuevo al confirmar el despacho.
#Devuelve el courier común (ya validado) para no volver a inferirlo con pedidos[0].
def validar_pedidos_para_despacho(pedidos):
    if not pedidos:
        raise ValueError("[!] Error: Selecciona al menos un pedido")

    destinatarios = {p.rut for p in pedidos}
    if len(destinatarios) > 1:
        raise ValueError("[!] Error: Los pedidos seleccionados tienen destinatarios distintos") #Revisar validación (puede causar errores innecesarios)

    couriers = {p.courier for p in pedidos}
    if len(couriers) > 1:
        raise ValueError("[!] Error: Los pedidos seleccionados no usan el mismo courier (puedes editarlo)")
    courier = couriers.pop()
    if not courier:
        raise ValueError("[!] Error: Los pedidos seleccionados no tienen courier asignado (puedes editarlo)")

    servicios = {p.servicio_courier_codigo for p in pedidos if p.servicio_courier_codigo}
    if len(servicios) > 1:
        raise ValueError("[!] Error: Los pedidos seleccionados detectaron distintos servicios de courier (ej. Express y Terrestre) — revisa antes de agrupar")

    for pedido in pedidos:
        if pedido.estado_comercial != Pedido.EstadoComercial.APROBADO:
            raise ValueError(f"Pedido N° {pedido.origen}-{pedido.num_pedido} no está APROBADO.")
        if pedido.envio_id is not None:
            raise ValueError(f"Pedido N° {pedido.origen}-{pedido.num_pedido} ya tiene un envío asignado.")
        contacto_valido = bool(pedido.telefono_contacto or pedido.email_contacto)
        direccion_valida = bool(pedido.direccion_calle and pedido.direccion_comuna)
        if not (contacto_valido and direccion_valida):
            raise ValueError(f"Pedido N° {pedido.origen}-{pedido.num_pedido} no tiene datos de contacto o dirección válidos (puedes editarlo).")

    return courier

def despachar_pedidos(pedidos, courier, bultos, destinatario, datos_courier, usuario):
    validar_pedidos_para_despacho(pedidos)   # re-valida por seguridad, aunque la vista ya haya chequeado

    courier_despacho = SELECCIONAR_COURIER.get(courier)

    if not courier_despacho:
        raise ValueError(f"[!] Error: No existe integración disponible para el courier {courier}.")
    
    datos_courier_completo = {**datos_courier, "bultos": bultos}
    resultado = courier_despacho(pedidos, destinatario, datos_courier_completo)
   
    with transaction.atomic():
        envio = EnvioCourier.objects.create(
            courier=courier,
            datos_courier=datos_courier_completo,
            orden_transporte=resultado["orden_transporte"],
            estado=EnvioCourier.Estado.DESPACHADO,
        )

        for pedido in pedidos:
            pedido.envio = envio
            pedido.save(update_fields=["envio"])

    notificaciones_fallidas = []
    for pedido in pedidos:
        try:
            notificar_pedido(pedido, usuario)
        except Exception as exc:  # incluye errores de SMTP (no solo PermissionError/ValueError) — que uno falle no bloquea al resto del lote
            notificaciones_fallidas.append((pedido, str(exc)))

    return envio, notificaciones_fallidas

#Lee los bultos del formulario de despachos, y lo estandariza en todo lugar que se vaya a utilizar
def parsear_bultos(request):
    if request.POST.get("modo_bultos") == "simple":
        cantidad = int(request.POST.get("simple_cantidad") or 1)
        peso_total = float(request.POST.get("simple_peso_total") or 0)
        peso_por_bulto = round(peso_total / cantidad, 2) if cantidad else peso_total
        return [{
            "tipo": "CAJA",
            "cantidad": cantidad,
            "alto": "",
            "ancho": "",
            "largo": "",
            "peso": peso_por_bulto,
            "tipo_contenido": request.POST.get("simple_tipo_contenido")
        }]

    tipos = request.POST.getlist("bulto_tipo")
    cantidades = request.POST.getlist("bulto_cantidad")
    altos = request.POST.getlist("bulto_alto")
    anchos = request.POST.getlist("bulto_ancho")
    largos = request.POST.getlist("bulto_largo")
    pesos = request.POST.getlist("bulto_peso")
    contenidos = request.POST.getlist("bulto_tipo_contenido")

    bultos = []
    for i in range(len(pesos)):
        bultos.append({
            "tipo": tipos[i],
            "cantidad": int(cantidades[i]),
            "alto": altos[i],
            "ancho": anchos[i],
            "largo": largos[i],
            "peso": float(pesos[i]),
            "tipo_contenido": contenidos[i],
        })
    return bultos