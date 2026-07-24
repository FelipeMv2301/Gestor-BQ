from django.db import models
from django.conf import settings
from ejecutivos.models import Ejecutivo
from django.db.models import Q

#Permite la creación y gestión de los filtros usados para las vistas
class PedidoQuerySet(models.QuerySet):
    def buscar(self, texto):
        if not texto:
            return self
        return self.filter(
            Q(num_pedido__icontains=texto) | Q(razon_social__icontains=texto)
            | Q(nombre_contacto__icontains=texto) | Q(rut__icontains=texto)
        )
    
    def con_estado_comercial(self, estado):
        return self.filter(estado_comercial=estado) if estado else self
    
    def con_notificacion(self, valores):
        return self.filter(estado_notificacion__in=valores) if valores else self
    
    def con_envio(self, valores):
        if "enviado" in valores and "sin" not in valores:
            return self.filter(envio__isnull=False)
        if "sin" in valores and "enviado" not in valores:
            return self.filter(envio__isnull=True)
        return self
    
    def con_origen(self, valores):
        return self.filter(origen__in=valores) if valores else self

    def con_tipo_entrega(self, valores):
        return self.filter(tipo_entrega__in=valores) if valores else self

    def con_courier(self, valores):
        return self.filter(courier__in=valores) if valores else self

class Pedido(models.Model):
    objects = PedidoQuerySet.as_manager()
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["origen", "num_pedido"],
                name="pedido_por_origen",
            )

        ]
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

    envio = models.ForeignKey(
        "envios.EnvioCourier", 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL, 
        related_name="pedidos"
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    modificado_en = models.DateTimeField(
        auto_now=True
    )

    #Estado de seguimiento unificado (comercial + logística + notificación + tipo de entrega).
    #Única fuente de verdad para el badge. Devuelve (etiqueta, clave_color) con clave ∈ pend/apro/noti.
    @property
    def estado_seguimiento(self):
        if self.estado_comercial == self.EstadoComercial.PENDIENTE:
            return ("Pendiente de carga", "pend")

        notificado = self.estado_notificacion == self.EstadoNotificacion.NOTIFICADO

        if self.tipo_entrega == self.TipoEntrega.RETIRO_BIOQUIMICA:
            if notificado:
                return ("Retiro disponible", "noti")
            return ("Preparando retiro", "apro")

        # Despacho
        if notificado:
            return ("Cargado a courier", "noti")
        if self.envio_id:
            return ("Despachado (sin notificar)", "apro")
        return ("Por despachar", "apro")

#Mapear los couriers por el SKU asignado en SAP
class SkuCourier(models.Model):
    class Sku(models.TextChoices):
        SGCHIBRA = "SGCHIBRA", "sgchibra"

    sku = models.CharField(
        max_length=120,
        choices=Sku.choices,
        unique=True,
    )

    courier = models.CharField(
        max_length=120, 
        choices=Pedido.Courier.choices
    )

    def __str__(self):
        return f"{self.sku} usa el courier {self.get_courier_display()}"
    
#Aviso interno: evento de un pedido dirigido a un usuario.
class Aviso(models.Model):
    class Tipo(models.TextChoices):
        NOTIFICADO = "NOTIFICADO", "Notificado"
        ANULADO = "ANULADO", "Anulado"

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="avisos")
    mensaje = models.CharField(max_length=255)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    # Denormalizados: sobreviven aunque el Pedido se borre al anular
    origen = models.CharField(max_length=20, blank=True)
    num_pedido = models.CharField(max_length=120, blank=True)
    pedido = models.ForeignKey(
        "pedidos.Pedido", null=True, blank=True, on_delete=models.SET_NULL, related_name="avisos")
    leida = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        indexes = [models.Index(fields=["destinatario", "leida"])]
    
