#Paquete de vistas de pedidos, partido por tema (antes un solo views.py de ~500 líneas):
#  pedidos.py    -> pantallas por pedido (lista, detalle, editar, rechazar, anulados, tablero)
#  lote.py       -> acciones sobre selección múltiple (eliminar/notificar en lote)
#  despacho.py   -> armar_despacho (form de despacho a courier)
#  avisos.py     -> campana de avisos internos
#  panel.py      -> Panel Admin (sincronizar, SKU-Courier)
#Reexporta todo acá para que "from . import views" + "views.nombre_funcion" (pedidos/urls.py)
#sigan funcionando exactamente igual, sin tocar las urls.

from .pedidos import (
    mis_pedidos,
    detalle_pedido,
    detalle_cuerpo,
    editar,
    cambiar_courier,
    rechazar,
    duplicar,
    anulados,
    reingresar,
    editar_motivo_rechazado,
    eliminar_rechazado,
    notificar,
    tablero_logistica,
)
from .lote import (
    eliminar_lote,
    rechazar_lote,
    notificar_lote,
    duplicar_lote,
)
from .despacho import (
    armar_despacho,
)
from .avisos import (
    marcar_avisos_leidos,
    marcar_aviso_leido,
    descartar_aviso,
    avisos_campana,
)
from .panel import (
    panel_admin,
    sincronizar,
    cargar_individual,
    panel_skus,
    crear_sku,
    editar_sku,
    eliminar_sku,
)
