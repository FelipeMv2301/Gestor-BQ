from django.db import models
from ejecutivos.models import Ejecutivo



class Pedido(models.Model):

    class Meta:
        indexes = [
            models.Index(fields=["num_pedido"]),
            models.Index(fields=["ejecutivo"]),
            models.Index(fields=["estado_comercial"]),
            models.Index(fields=["estado_notificacion"]),
        ]

    #Normalizar tipos de entrega
    class TipoEntrega(models.TextChoices):
        RETIRO_BIOQUIMICA = "RETIRO_BIOQUIMICA", "Retiro en Bioquimica"
        DESPACHO = "DESPACHO", "Despacho"
    
    #Normalizar origen de pedido
    class Origen(models.TextChoices):
        SAP = "SAP", "SAP"
        WEB = "WEB", "WEB"

    #Campo mapeado de lo que viene en SAP
    class CrearEnvio(models.TextChoices):
        Y = "Y", "Si"
        N = "N", "No"

    #Listado de couriers (y los que se conectarán a las plataformas correspondientes)
    class Courier(models.TextChoices):
        CHIBRA = "CHIBRA", "Chibra"
        MOVEUP = "MOVEUP", "MoveUP"

    class EstadoComercial(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"

    class EstadoNotificacion(models.TextChoices):
        NO_NOTIFICADO = "NO_NOTIFICADO", "No notificado"
        NOTIFICADO = "NOTIFICADO", "Notificado"

    class RetirarEn(models.TextChoices):
        RETIRO_BODEGA_N3A = "RETIRO_BODEGA_N3A", "Retiro en Bodega (N3A)"
        RETIRO_TIENDA_S2 = "RETIRO_TIENDA_S2", "Retiro en Tienda (S2)"
        NO_APLICA = "NO_APLICA", "No aplica"
        
    origen = models.CharField(
        max_length=20,
        choices = Origen.choices
    )

    num_pedido = models.CharField(
        max_length=120,
        blank=False,
        null=False,
        unique=True
    )

    tipo_entrega = models.CharField(
        max_length=120,
        choices = TipoEntrega.choices
    )

    retirar_en = models.CharField(
        blank = True,
        max_length=120,
        choices = RetirarEn.choices
    )

    transportation_code = models.IntegerField(
        null=True,
        blank=True
    )

    #Nombre en SAP: U_BQ_TipoEntrega
    u_bq_tipo_entrega = models.CharField(
        max_length=120,
        blank=True,
    )

    #Nombre en SAP: U_BQ_CrearEnvio
    u_bq_crear_envio = models.CharField(
        max_length=10,
        choices = CrearEnvio.choices,
        blank=True
    )

    courier = models.CharField(
        max_length=20,
        choices = Courier.choices,
        blank=True
    )

    rut = models.CharField(
        max_length=120
    )

    razon_social = models.CharField(
        max_length=200, 
        blank=True
    )

    nombre_contacto = models.CharField(
        max_length=200, 
        blank=True
    )

    telefono_contacto = models.CharField(
        max_length=30, 
        blank=True
    )

    email_contacto = models.EmailField(
        blank=True
    )

    direccion_calle = models.CharField(
        max_length=200, 
        blank=True
    )  
    
    direccion_depto = models.CharField(
        max_length=120, 
        blank=True
    )

    direccion_comuna = models.CharField(
        max_length=100, 
        blank=True
    )

    direccion_ciudad = models.CharField(
        max_length=100, 
        blank=True
    )

    ejecutivo = models.ForeignKey(
        Ejecutivo,
        null=True,
        blank=True,
        on_delete=models.SET_NULL, 
    )

    estado_comercial = models.CharField(
        choices=EstadoComercial.choices,
        max_length=12,
        default=EstadoComercial.PENDIENTE,
    )

    estado_notificacion = models.CharField(
        max_length=15,
        choices=EstadoNotificacion.choices,
        default=EstadoNotificacion.NO_NOTIFICADO,
    )

    observaciones = models.TextField(
        blank=True
    )

    orden_transporte = models.CharField(
        max_length=200, 
        blank=True
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    modificado_en = models.DateTimeField(
        auto_now=True
    )
