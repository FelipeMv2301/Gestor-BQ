from django.db import models
from django.conf import settings
from utils import Courier

class EnvioIncidencia(models.Model):
      courier = models.CharField(max_length=20, choices=Courier.choices)
      orden_transporte = models.CharField(max_length=100, blank=True)
      snapshot = models.JSONField()
      pedidos_incluidos = models.JSONField(default=list)
      motivo = models.TextField(blank=True)
      registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
  null=True)
      registrado_en = models.DateTimeField(auto_now_add=True)

      def __str__(self):
          detalle = f"Incidencia #{self.id} - {self.courier}"
          if self.orden_transporte:
              detalle += f" - {self.orden_transporte}"
          return detalle