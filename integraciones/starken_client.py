import requests, base64
from django.conf import settings
from utils import validar_rut, normalizar_telefono_cl

TIPO_ENTREGA_AGENCIA = 1 #Para envíos a agencia de starken
TIPO_ENTREGA_DOMICILIO = 2 #Para envíos a domicilio del cliente
TIPO_ENCARGO_DEFAULT = "29" #Package in kilograms (Diccionario_H2H_Parametros_de_Entrada, hoja "Package classification")
TIPO_SALIDA_BASE64_10X10 = 6 #Determinar el tamaño de la etiqueta
VALOR_DECLARADO_MINIMO_CON_DOCUMENTO = 50000 #Sobre este monto, Starken exige un documento de referencia (Diccionario de Entrada)

"""
Helpers
"""
#Uniforma los errores de red y HTTP de Starken en un mensaje legible para Logística. Van separados
#a propósito: no llegar a Starken (DNS caído, timeout) no es lo mismo que Starken SÍ responder pero
#con un HTTP de error (400/403/500) — bug real detectado 2026-08-18, un 400 real (endpoint/método mal
#armado) se mostraba como "no se pudo conectar", escondiendo el detalle que hacía falta para depurar.
def _solicitud(metodo, url, **kwargs):
    try:
        respuesta = metodo(url, timeout=30, **kwargs)
    except requests.exceptions.RequestException as exc:
        raise ValueError(f"[!] Error: no se pudo conectar con Starken. Revisa la conexión o el ambiente configurado ({url}).") from exc

    try:
        respuesta.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise ValueError(
            f"[!] Error: Starken respondió HTTP {respuesta.status_code} en {url}. Detalle: {respuesta.text[:300]}"
        ) from exc
    return respuesta
# Sirve para gestionar los documentos (maximo 5) que se pueden incorporar en starken
def _referencias_documentos(documentos):
    #Starken no acepta una lista de documentos: son 5 campos fijos con nombre (tipoDocumentoN/
    #numeroDocumentoN/generaEtiquetaDocumentoN, N del 1 al 5), no un arreglo.
    if len(documentos) > 5:
        raise ValueError(f"[!] Error: Starken admite máximo 5 documentos de referencia por OF (se enviaron {len(documentos)}).")

    campos = {}
    for numero_slot in range(1, 6):
        documento = documentos[numero_slot - 1] if numero_slot <= len(documentos) else None
        campos[f"tipoDocumento{numero_slot}"] = documento["tipo"] if documento else ""
        campos[f"numeroDocumento{numero_slot}"] = documento["numero"] if documento else ""
        campos[f"generaEtiquetaDocumento{numero_slot}"] = "N"
    return campos

def emitir_of(pedidos, bultos, destinatario, datos_courier):
    numero_bultos = sum(b["cantidad"] for b in bultos)
    kilos = sum(b["peso"] * b["cantidad"] for b in bultos)
    #Multibultos (FAQ del manual): sumar UNA dimensión y tomar el máximo de las otras dos. El largo
    #se suma por BULTO FÍSICO, no por fila del formulario — una fila con cantidad=3 cuenta 3 veces
    #(bug real detectado 2026-08-18: antes solo sumaba el largo de la fila una vez, subestimando el
    #volumen declarado a Starken cuando una fila agrupaba más de un bulto idéntico).
    largo = sum(float(b.get("largo") or 0) * b["cantidad"] for b in bultos)
    ancho = max((float(b.get("ancho") or 0) for b in bultos), default=0)
    alto = max((float(b.get("alto") or 0) for b in bultos), default=0)

    codigo_agencia = datos_courier.get("codigo_agencia_destino")
    tipo_entrega = TIPO_ENTREGA_AGENCIA if codigo_agencia else TIPO_ENTREGA_DOMICILIO
    comuna_destino = f"@{codigo_agencia}" if codigo_agencia else destinatario["comuna"]

    rut_cuerpo, _, rut_dv = destinatario["rut"].partition("-")
    rut_dv = rut_dv.upper()  #Starken espera el DV en mayúscula ("K"); un "k" tipeado por Logística pasa validar_rut pero llegaría en minúscula si no se normaliza aquí.

    if not validar_rut(destinatario["rut"]):
        raise ValueError(f"[!] Error: RUT inválido para emitir la OF en Starken: {destinatario['rut']}")

    valor_declarado = int(datos_courier.get("valor_declarado") or 0)
    documentos = datos_courier.get("documentos") or []
    if valor_declarado > VALOR_DECLARADO_MINIMO_CON_DOCUMENTO and not documentos:
        valor_formateado = f"{valor_declarado:,}".replace(",", ".")
        minimo_formateado = f"{VALOR_DECLARADO_MINIMO_CON_DOCUMENTO:,}".replace(",", ".")
        raise ValueError(
            f"[!] Error: el valor declarado (${valor_formateado}) supera ${minimo_formateado} — Starken "
            "exige agregar al menos un documento de referencia (factura, guía o boleta)."
        )

    payload = {
        "rutEmpresaEmisora": settings.STARKEN_RUT_EMPRESA_EMISORA,
        "rutUsuarioEmisor": settings.STARKEN_RUT_USUARIO_EMISOR,
        "claveUsuarioEmisor": settings.STARKEN_CLAVE_USUARIO_EMISOR,
        "rutRemitente": settings.STARKEN_RUT_REMITENTE,
        "dvRemitente": settings.STARKEN_DV_REMITENTE,
        "nombreRazonSocialRemitente": settings.STARKEN_RAZON_SOCIAL_REMITENTE,
        "apellidoPaternoRemitente": ".",
        "apellidoMaternoRemitente": ".",
        "direccionRemitente": settings.STARKEN_DIRECCION_REMITENTE,
        "numeracionDireccionRemitente": settings.STARKEN_NUMERACION_DIRECCION_REMITENTE,
        "departamentoRemitente": "",
        "emailRemitente": settings.STARKEN_EMAIL_REMITENTE,
        "telefonoRemitente": settings.STARKEN_TELEFONO_REMITENTE,
        "comunaRemitente": settings.STARKEN_COMUNA_REMITENTE,
        "rutDestinatario": rut_cuerpo,
        "dvRutDestinatario": rut_dv,
        #El manual separa nombre/apellidoPaterno/apellidoMaterno del destinatario; nosotros solo
        #tenemos el nombre completo en un string (mismo dato que usan Chibra/MoveUP). Se manda todo
        #en nombreRazonSocialDestinatario y "." en los apellidos — confirmar en QA si Starken lo acepta así.
        "nombreRazonSocialDestinatario": destinatario["nombre"],
        "apellidoPaternoDestinatario": ".",
        "apellidoMaternoDestinatario": ".",
        "direccionDestinatario": destinatario["direccion"],
        "numeracionDireccionDestinatario": destinatario.get("numero") or "",
        "departamentoDireccionDestinatario": destinatario.get("depto") or "",
        "comunaDestino": comuna_destino,
        "telefonoDestinatario": normalizar_telefono_cl(destinatario.get("telefono") or ""),
        "emailDestinatario": destinatario.get("email") or "",
        "nombreContactoDestinatario": destinatario["nombre"],
        "tipoEntrega": tipo_entrega,
        "tipoPago": "2",
        "numeroCtaCte": settings.STARKEN_NUMERO_CTA_CTE,
        "dvNumeroCtaCte": settings.STARKEN_DV_NUMERO_CTA_CTE,
        "centroCostoCtaCte": settings.STARKEN_CENTRO_COSTO_CTA_CTE,
        "valorDeclarado": str(int(datos_courier.get("valor_declarado") or 0)),
        "contenido": datos_courier.get("contenido") or "MERCADERIA",
        "kilosTotal": str(kilos),
        "alto": str(alto),
        "ancho": str(ancho),
        "largo": str(largo),
        "tipoServicio": datos_courier.get("servicio") or "0",
        **_referencias_documentos(documentos),
        "tipoEncargo1": TIPO_ENCARGO_DEFAULT,
        "cantidadEncargo1": str(numero_bultos),
        "tipoEncargo2": "", "cantidadEncargo2": "",
        "tipoEncargo3": "", "cantidadEncargo3": "",
        "tipoEncargo4": "", "cantidadEncargo4": "",
        "tipoEncargo5": "", "cantidadEncargo5": "",
        "observacion": datos_courier.get("observaciones") or "",
    }

    respuesta = _solicitud(requests.post, settings.STARKEN_BASE_URL, json=payload)
    datos = respuesta.json()

    if datos.get("codigoError") != 0:
        raise ValueError(f"[!] Error de Starken: {datos.get('descripcionError', 'sin detalle')}")

    #nroOrdenFlete viene en notación científica (ej. 2.22607751E8) — convertir antes de guardar.
    return {"numero_orden_flete": str(int(float(datos["nroOrdenFlete"])))}

def generar_etiqueta(numero_orden_flete, tipo_salida=TIPO_SALIDA_BASE64_10X10):
    respuesta = _solicitud(
        requests.post, settings.STARKEN_ETIQUETA_URL,
        auth=(settings.STARKEN_ETIQUETA_USER, settings.STARKEN_ETIQUETA_PASSWORD),
        params={"ordenFlete": numero_orden_flete, "tipoSalida": tipo_salida},
    )
    datos = respuesta.json()

    if datos.get("status") != 200:
        raise ValueError(f"[!] Error de Starken al generar etiqueta: {datos.get('message', 'sin detalle')}")

    #data es un arreglo de strings Base64 (uno por bulto/encargo, ver manual sección "Generación de etiqueta").
    return [base64.b64decode(etiqueta) for etiqueta in datos["data"]]


#Agencias con PickUp habilitado (delivery=true), para el selector de "retiro en agencia" del formulario
#de despacho. code_dls es el código que va en comunaDestino ("@<code_dls>") al emitir la OF.
def listar_agencias():
    respuesta = _solicitud(
        requests.get, settings.STARKEN_AGENCY_URL,
        headers={"Authorization": settings.STARKEN_AGENCY_TOKEN},
    )
    return [a for a in respuesta.json() if a.get("delivery")]

def consultar_estado(orden_flete):
    respuesta = _solicitud(
        requests.post, settings.STARKEN_SEGUIMIENTO_URL,
        headers={"Rut": settings.STARKEN_SEGUIMIENTO_RUT, "Clave": settings.STARKEN_SEGUIMIENTO_CLAVE},
        json={"ordenFlete": int(orden_flete)},
    )
    return respuesta.json().get("estadoFlete") or ""

#Seguimiento MASIVO (Etracking): una sola llamada para varias OF, para el botón "Actualizar estados"
#en lote (mismo rol que moveup_client.consultar_envios en el batch de MoveUP). Esquema de auth propio
#(api-key/cli-rut/password) — distinto del Rut/Clave que usa consultar_estado (individual).
def consultar_estados_batch(ordenes_flete):
    respuesta = _solicitud(
        requests.post, settings.STARKEN_ETRACKING_URL,
        headers={
            "api-key": settings.STARKEN_ETRACKING_API_KEY,
            "cli-rut": settings.STARKEN_ETRACKING_CLI_RUT,
            "password": settings.STARKEN_ETRACKING_PASSWORD,
        },
        json={
            "tracking": [{"numeroDocumento": "", "numeroOrdenFlete": str(of), "tipoDocumento": ""} for of in ordenes_flete],
            "rutEmpresa": settings.STARKEN_RUT_EMPRESA_EMISORA,
        },
    )
    filas = respuesta.json().get("listaResumenRedestinacion", {}).get("ordenFlete") or []
    #codigoSalida distinto de 1 = esa consulta puntual no fue correcta (ej. OF no encontrada) — se
    #omite esa fila sin tumbar el resto del lote.
    return {
        str(fila["numeroOrdenFlete"]): fila.get("estadoOrdenFlete") or ""
        for fila in filas if fila.get("codigoSalida") == 1
    }

#Anula una OF. Dos llamadas: login (usuario STK Pro Empresa, token JWT nuevo cada vez — no se
#reusa ni se cachea) y anulación (Bearer del paso anterior). Solo anula OF sin movimientos
#operativos y del mismo RUT del usuario — Starken puede rechazar con estado "NO_OK" y motivo.
def anular_of(numero_of):
    respuesta_login = _solicitud(
        requests.post, settings.STARKEN_ANULACION_LOGIN_URL,
        json={
            "application": {"code": "PRO"},
            "run": settings.STARKEN_ANULACION_RUN,
            "rut_master": settings.STARKEN_ANULACION_RUT_MASTER,
            "password": settings.STARKEN_ANULACION_PASSWORD,
        },
    )
    token = respuesta_login.json().get("token")
    if not token:
        raise ValueError("[!] Error: Starken no devolvió token de sesión para anular la OF.")

    respuesta = _solicitud(
        requests.post, settings.STARKEN_ANULACION_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={"numerosOrden": [int(numero_of)]},
    )
    filas = respuesta.json().get("data") or []
    fila = next((f for f in filas if str(f.get("numeroOrden")) == str(numero_of)), None)

    if not fila or fila.get("estado") != "OK":
        motivo = fila.get("mensaje") if fila else "sin respuesta de Starken para esa OF"
        raise ValueError(f"[!] Error de Starken al anular la OF {numero_of}: {motivo}")