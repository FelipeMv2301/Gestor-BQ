from django.db import models
from django.conf import settings

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

    codigo_empleado_sap = models.IntegerField(
        blank=True,
        unique=True,
        null=True
    )
    
    activo = models.BooleanField(
        default=True
    )

    def __str__():
        pass
