from django.db import models

#Esto sirve para vincular nota de venta / pedido con el Ejecutivo
class Ejecutivo(models.Model):
    codigo_sap = models.IntegerField(
        unique=True
    )

    nombre = models.CharField(
        max_length=120
    )

    email = models.EmailField(
        blank=True
    )

    activo = models.BooleanField(
        default=True
    )

    #Marca los códigos SAP cuyos pedidos deben aparecer en el módulo de Seguimiento ONT
    #(seguimientoOnt.DespachoOnt) — hoy son los códigos 44 y 42, editable desde /admin/.
    es_ont = models.BooleanField(
        default=False
    )

    def __str__(self):
      return self.nombre