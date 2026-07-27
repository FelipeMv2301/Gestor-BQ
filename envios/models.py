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

    def __str__(self):
        detalle_envio = f"#{self.id} - {self.courier} - {self.estado}"
        if self.orden_transporte:
          detalle_envio += f" - {self.orden_transporte}"
        return detalle_envio
