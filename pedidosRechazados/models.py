from django.db import models
from django.conf import settings

class PedidoRechazado(models.Model):

    origen = models.CharField(
        max_length=30, 
        blank=True
    )

    num_pedido = models.CharField(
        max_length=120
    )

    motivo = models.TextField(
        blank=True,
    )

    snapshot = models.JSONField()

    rechazado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    rechazado_en = models.DateTimeField(
        auto_now_add=True
    )