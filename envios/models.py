from django.db import models

"""
Modelo que engloba todo lo que será envios y la conexión con los distintos courier.
"""

class EnvioCourier(models.Model):

    #Entrega un estado general de pedido, que intenta dar claridad del seguimiento (no es el seguimiento de la plataforma como tal)
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        DESPACHADO = "DESPACHADO", "Despachado"
        ENTREGADO = "ENTREGADO", "Entregado"
        ERROR = "ERROR", "Error"

    class Courier(models.TextChoices):
        CHIBRA = "CHIBRA", "Chibra"
        MOVEUP = "MOVEUP", "MoveUP"

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
