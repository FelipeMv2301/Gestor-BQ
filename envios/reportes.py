import openpyxl
from openpyxl.styles import Font
from django.http import HttpResponse
from django.utils import timezone
from .models import EnvioCourier
from pedidos import permisos
from cuentas.models import PerfilUsuario

"""
Reporte de envíos por fecha / courier / ejecutivo.

Arma las filas UNA sola vez (fuente única): las consumen tanto la vista imprimible (→ PDF por el
navegador) como la exportación a Excel. Reusa el scope de permisos y los filtros del
EnvioCourierQuerySet — este módulo no reimplementa lógica de visibilidad ni de filtrado.
"""


#Scope de rol: Logística/Admin ven todos los envíos; el Ejecutivo solo los que agrupan un pedido suyo.
#Es la misma regla que el resto de la app (permisos), aplicada sobre EnvioCourier.
def _visibles_para(usuario):
    if permisos.es_logistica(usuario):
        return EnvioCourier.objects.all()
    if permisos.obtener_rol(usuario) == PerfilUsuario.Rol.EJECUTIVO:
        return EnvioCourier.objects.de_ejecutivo(permisos.codigos_sap_usuario(usuario))
    return EnvioCourier.objects.none()


#Castea a entero seguro (el valor declarado se guarda como texto en datos_courier JSON). "" / None → 0.
def _a_entero(valor):
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return 0


#Medidas por bulto "LxAxA" (largo x ancho x alto), solo las que traen dimensiones. Vacío cuando no
#aplican (MoveUP / modo simple de Chibra no capturan medidas), por eso "si aplican".
def _formatear_medidas(bultos):
    partes = []
    for bulto in bultos:
        alto, ancho, largo = bulto.get("alto"), bulto.get("ancho"), bulto.get("largo")
        if alto or ancho or largo:
            partes.append(f"{largo or 0}x{ancho or 0}x{alto or 0}")
    return " / ".join(partes)


#Mismas filas que un envío normal, armadas desde EnvioIncidencia (el envío original ya se borró —
#todo sale del snapshot). "Estado Courier" se reusa para marcar que es una incidencia, en vez de
#agregar una columna nueva solo para esto.
def _filas_incidencias(desde, hasta, couriers, ejecutivo_ids, usuario):
    from enviosIncidencias.models import EnvioIncidencia
    from ejecutivos.models import Ejecutivo

    incidencias = permisos.incidencias_visibles(usuario)
    if desde:
        incidencias = incidencias.filter(registrado_en__date__gte=desde)
    if hasta:
        incidencias = incidencias.filter(registrado_en__date__lte=hasta)
    if couriers:
        incidencias = incidencias.filter(courier__in=couriers)

    nombres_ejecutivo = dict(Ejecutivo.objects.values_list("pk", "nombre"))

    filas = []
    for incidencia in incidencias:
        pedidos = incidencia.pedidos_incluidos or []
        if ejecutivo_ids and not any(p.get("ejecutivo_id") in ejecutivo_ids for p in pedidos):
            continue
        datos = (incidencia.snapshot or {}).get("datos_courier") or {}
        bultos = datos.get("bultos") or []
        filas.append({
            "fecha": incidencia.registrado_en,
            "courier": incidencia.get_courier_display(),
            "ot": incidencia.orden_transporte,
            "pedidos": ", ".join(f"{p.get('origen')}-{p.get('num_pedido')}" for p in pedidos),
            "ejecutivo": ", ".join(sorted({
                nombres_ejecutivo[p["ejecutivo_id"]] for p in pedidos if p.get("ejecutivo_id") in nombres_ejecutivo
            })),
            "medidas": _formatear_medidas(bultos),
            "n_bultos": sum(int(b.get("cantidad") or 0) for b in bultos),
            "valor_declarado": _a_entero(datos.get("valor_declarado")),
            "estado_courier": f"INCIDENCIA: {incidencia.motivo}",
        })
    return filas


#Devuelve la lista de filas del reporte (una por envío/OT). Cada fila es un dict con las columnas que
#pide el negocio: OT, pedidos agrupados, medidas, N° bultos, valor declarado (+ fecha/courier/ejecutivo).
#incluir_incidencias suma también los envíos archivados por incidencia (checkbox del formulario).
def filas_reporte(desde, hasta, couriers, ejecutivo_ids, usuario, incluir_incidencias=False):
    envios = (
        _visibles_para(usuario)
        .con_fecha(desde, hasta)
        .con_courier(couriers)
        .con_ejecutivos(ejecutivo_ids)
        .prefetch_related("pedidos", "pedidos__ejecutivo")
        .order_by("-creado_en")
    )

    filas = []
    for envio in envios:
        pedidos = list(envio.pedidos.all())
        datos = envio.datos_courier or {}
        bultos = datos.get("bultos") or []
        filas.append({
            "fecha": envio.creado_en,
            "courier": envio.get_courier_display(),
            "ot": envio.orden_transporte,
            "pedidos": ", ".join(f"{p.origen}-{p.num_pedido}" for p in pedidos),
            "ejecutivo": ", ".join(sorted({p.ejecutivo.nombre for p in pedidos if p.ejecutivo_id})),
            "medidas": _formatear_medidas(bultos),
            "n_bultos": sum(int(b.get("cantidad") or 0) for b in bultos),
            "valor_declarado": _a_entero(datos.get("valor_declarado")),
            "estado_courier": envio.estado_courier,
        })

    if incluir_incidencias:
        filas += _filas_incidencias(desde, hasta, couriers, ejecutivo_ids, usuario)
        filas.sort(key=lambda f: f["fecha"], reverse=True)

    return filas


#Columnas del reporte: (encabezado visible, clave en la fila). Mismo orden en Excel y en el HTML
#imprimible — un solo lugar define qué se muestra y en qué orden.
COLUMNAS = [
    ("Fecha", "fecha"),
    ("Courier", "courier"),
    ("OT", "ot"),
    ("Pedidos", "pedidos"),
    ("Ejecutivo", "ejecutivo"),
    ("Medidas (LxAxA)", "medidas"),
    ("N° Bultos", "n_bultos"),
    ("Valor Declarado", "valor_declarado"),
    ("Estado Courier", "estado_courier"),
]

#Anchos de columna del Excel (en el mismo orden que COLUMNAS), para que no salga todo apretado.
_ANCHOS = [17, 12, 16, 26, 22, 18, 10, 16, 16]


#Valor de una celda para el Excel. La fecha es datetime tz-aware → openpyxl no la acepta; la pasamos
#a texto local legible.
def _valor_celda(fila, clave):
    valor = fila.get(clave)
    if clave == "fecha" and valor:
        return timezone.localtime(valor).strftime("%Y-%m-%d %H:%M")
    return valor


#Genera el .xlsx descargable a partir de las filas ya armadas (misma fuente que el HTML imprimible).
def exportar_xlsx(filas):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Envíos"

    hoja.append([encabezado for encabezado, _ in COLUMNAS])
    for celda in hoja[1]:
        celda.font = Font(bold=True)

    for fila in filas:
        hoja.append([_valor_celda(fila, clave) for _, clave in COLUMNAS])

    for indice, ancho in enumerate(_ANCHOS, start=1):
        hoja.column_dimensions[openpyxl.utils.get_column_letter(indice)].width = ancho

    respuesta = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    respuesta["Content-Disposition"] = 'attachment; filename="reporte_envios.xlsx"'
    libro.save(respuesta)
    return respuesta
