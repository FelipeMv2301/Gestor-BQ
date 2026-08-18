from django.db import models
from django.db.models import Q
from utils import Courier

"""
Modelo que engloba todo lo que será envios y la conexión con los distintos courier.
"""

#Mismo patrón que PedidoQuerySet (pedidos/models.py) — filtros usados por la vista de Envíos.
class EnvioCourierQuerySet(models.QuerySet):
    def buscar(self, texto):
        if not texto:
            return self
        return self.filter(
            Q(orden_transporte__icontains=texto) | Q(pedidos__num_pedido__icontains=texto)
            | Q(pedidos__rut__icontains=texto)
        ).distinct()

    def con_courier(self, valores):
        return self.filter(courier__in=valores) if valores else self

    #Origen vive en Pedido, no en EnvioCourier — filtra por los pedidos que agrupa el envío.
    def con_origen(self, valores):
        return self.filter(pedidos__origen__in=valores).distinct() if valores else self

    #Scope del ejecutivo: solo envíos que agrupan al menos un pedido suyo. Recibe la lista de códigos
    #SAP del perfil (permisos.codigos_sap_usuario). Sin códigos → nada.
    def de_ejecutivo(self, codigos_sap):
        return self.filter(pedidos__ejecutivo__codigo_sap__in=codigos_sap).distinct() if codigos_sap else self.none()

    #Rango de fechas por creado_en (fecha del despacho). Cada extremo es opcional.
    def con_fecha(self, desde, hasta):
        qs = self
        if desde:
            qs = qs.filter(creado_en__date__gte=desde)
        if hasta:
            qs = qs.filter(creado_en__date__lte=hasta)
        return qs

    #Filtro elegible del reporte: envíos que agrupan un pedido de alguno de estos ejecutivos (por pk).
    #Vacío = sin filtro (todos los que el scope de rol ya dejó ver).
    def con_ejecutivos(self, ejecutivo_ids):
        return self.filter(pedidos__ejecutivo_id__in=ejecutivo_ids).distinct() if ejecutivo_ids else self


class EnvioCourier(models.Model):
    objects = EnvioCourierQuerySet.as_manager()

    #Entrega un estado general de pedido, que intenta dar claridad del seguimiento (no es el seguimiento de la plataforma como tal)
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        DESPACHADO = "DESPACHADO", "Despachado"
        ENTREGADO = "ENTREGADO", "Entregado"
        ERROR = "ERROR", "Error"

    courier = models.CharField(max_length=20, choices=Courier.choices)
    estado = models.CharField(max_length=30, choices=Estado.choices, default=Estado.PENDIENTE)
    orden_transporte = models.CharField(max_length=100, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    datos_courier = models.JSONField(blank=True, default=dict)
    estado_courier = models.CharField(max_length=60, blank=True)          # lo que reporta el courier (ej. "Programado")
    estado_courier_actualizado = models.DateTimeField(null=True, blank=True)  # cuándo se consultó por última vez

    def __str__(self):
        detalle_envio = f"#{self.id} - {self.courier} - {self.estado}"
        if self.orden_transporte:
          detalle_envio += f" - {self.orden_transporte}"
        return detalle_envio

    #Portal interno donde Logística gestiona el envío (o None si no hay). Import local, ver arriba.
    @property
    def url_portal_courier(self):
        from integraciones.seguimiento import url_portal_courier
        return url_portal_courier(self)

    #Link de seguimiento público, el que ve el cliente final (o None si no hay).
    @property
    def url_seguimiento_publico(self):
        from integraciones.seguimiento import url_seguimiento_publico
        return url_seguimiento_publico(self)
