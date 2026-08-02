from django.db import models
from ejecutivos.models import Ejecutivo

#Traducción de códigos de SAP a etiqueta legible (portado de API-Planillas-1/comercial_service.py)
MAP_TIPO_VENTA = {
    "DIR": "Directa", "WEB": "WEB", "CA": "Compra Ágil", "LI": "Licitación",
    "ML": "Mercado Libre", "DM": "Disp Médicos", "CM": "Conv Marco", "PR": "Presencial",
    "LIP": "Licitación Privada", "AC": "Autocotización", "PP": "Prospecto Público",
}
MAP_AREAS = {
    "TRA": "Transaccional", "CON": "Consultivo", "MER": "Mercado Público",
    "BIO": "Biotecnología", "CLI": "Clínica", "SER": "Servicios", "WEB": "Web",
}


class Cotizacion(models.Model):
    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        PARCIAL = "PARCIAL", "Parcial"
        COMPLETADO = "COMPLETADO", "Completado"
        ANULADO = "ANULADO", "Anulado"

    docentry = models.IntegerField(
        unique=True
    )

    docnum = models.CharField(
        max_length=40,
        unique=True,
    )

    card_code = models.CharField(
        max_length=60
    )

    rut = models.CharField(
        max_length=40,
        blank=True,
    )

    card_name = models.CharField(
        max_length=400,
        blank=True,              
    )

    nombre_contacto = models.CharField(
        max_length=400,
        blank=True,
    )

    telefono = models.CharField(
        max_length=100,
        blank=True,
    )

    email = models.EmailField(
        blank=True
    )

    ejecutivo = models.ForeignKey(
        Ejecutivo, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL
    )

    tipo_venta = models.CharField(
        max_length=40,
        blank=True,
    )

    area_trabajo = models.CharField(
        max_length=40,
        blank=True,
    )

    neto = models.DecimalField(
        max_digits=20, 
        decimal_places=2, 
        default=0
    )

    iva = models.DecimalField(
        max_digits=20, 
        decimal_places=2, 
        default=0
    )

    total = models.DecimalField(
        max_digits=20, 
        decimal_places=2, 
        default=0
    )

    total_facturado = models.DecimalField(
        max_digits=20, 
        decimal_places=2, 
        default=0
    )

    fecha_contabilizacion = models.DateField(
        null=True, 
        blank=True
    )

    fecha_caducidad = models.DateField(
        null=True,
        blank=True
    )

    actualizado_sap = models.DateTimeField(
        null=True,
        blank=True
    )  # UpdateDate de SAP

    estado = models.CharField(
        max_length=20, 
        choices=Estado.choices, 
        default=Estado.ABIERTO
    )

    doc_status = models.CharField(
        max_length=20, 
        blank=True
    )

    cancelado = models.BooleanField(
        default=False
    )

    lineas = models.JSONField(
        default=list, 
        blank=True
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    modificado_en = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-docentry"]
        indexes = [
            models.Index(fields=["docnum"]),
            models.Index(fields=["ejecutivo"]),
            models.Index(fields=["estado"]),
            models.Index(fields=["fecha_caducidad"]),
        ]

    def __str__(self):
        return f"Cotización {self.docnum} — {self.card_name}"

    @property
    def tipo_venta_legible(self):
        return MAP_TIPO_VENTA.get(self.tipo_venta, self.tipo_venta)
    
    @property
    def diferencia(self):
        return self.neto - self.total_facturado

    @property
    def area_legible(self):
        return MAP_AREAS.get(self.area_trabajo, self.area_trabajo)

