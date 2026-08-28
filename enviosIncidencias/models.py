from django.db import models
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from utils import Courier

class EnvioIncidencia(models.Model):
      courier = models.CharField(max_length=20, choices=Courier.choices)
      orden_transporte = models.CharField(max_length=100, blank=True)
      #DjangoJSONEncoder (no el json.JSONEncoder plano por default): el snapshot viene de model_to_dict()
      #sobre EnvioCourier, que incluye estado_courier_actualizado (DateTimeField real, no auto_now) — el
      #encoder default no sabe serializar datetime y tumbaba esto con un 500 en producción (envíos con
      #estado ya refrescado por el cron). Ver test_snapshot_de_envio_con_estado_courier_actualizado_no_revienta.
      snapshot = models.JSONField(encoder=DjangoJSONEncoder)
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