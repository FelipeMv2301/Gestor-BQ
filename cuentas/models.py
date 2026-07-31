from django.db import models
from django.conf import settings
from ejecutivos.models import Ejecutivo

class PerfilUsuario(models.Model):
    #Hace que los roles sean llamables desde varios lugares
    class Rol(models.TextChoices):
        EJECUTIVO = "EJECUTIVO", "Ejecutivo"
        LOGISTICA = "LOGISTICA", "Logística"
        ADMIN = "ADMIN", "Administrador"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil"
    )

    rol = models.CharField(
        max_length=30,
        choices=Rol.choices,
        null=True,
        blank=True,
    )

    #Legacy: código único escalar. Se mantiene como fallback durante la transición a `ejecutivos` (M2M).
    #No borrar todavía — `codigos_sap` cae de vuelta a este si la M2M está vacía.
    codigo_empleado_sap = models.IntegerField(
        blank=True,
        unique=True,
        null=True
    )

    #Un perfil puede gestionar varios canales SAP → varios Ejecutivo (cada uno con su codigo_sap).
    #Fuente de verdad de la visibilidad; se lee siempre vía la property `codigos_sap`.
    ejecutivos = models.ManyToManyField(
        Ejecutivo,
        blank=True,
        related_name="perfiles",
    )

    activo = models.BooleanField(
        default=True
    )

    ve_todas_cotizaciones = models.BooleanField(
        default=False,
        help_text="Supervisor comercial: ve las cotizaciones de todos los ejecutivos.",
    )

    def __str__(self):
        return self.usuario.email

    #Único punto de verdad de los códigos SAP del perfil. Prefiere la M2M; si está vacía, cae al
    #escalar legacy. Todo filtro de visibilidad debe usar esto con `__in` (nunca el escalar directo).
    @property
    def codigos_sap(self):
        codigos = list(self.ejecutivos.values_list("codigo_sap", flat=True))
        if codigos:
            return codigos
        return [self.codigo_empleado_sap] if self.codigo_empleado_sap is not None else []
