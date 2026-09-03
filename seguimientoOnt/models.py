from django.db import models
from django.conf import settings


class DespachoOntQuerySet(models.QuerySet):
    def buscar(self, texto):
        if not texto:
            return self
        return self.filter(
            models.Q(pedido__num_pedido__icontains=texto)
            | models.Q(pedido__nombre_contacto__icontains=texto)
            | models.Q(pedido__rut__icontains=texto)
            | models.Q(guia_despacho__icontains=texto)
        ).distinct()

    def con_accion(self, valores):
        return self.filter(accion__in=valores) if valores else self

    def con_fecha_compromiso(self, desde, hasta):
        qs = self
        if desde:
            qs = qs.filter(fecha_compromiso__gte=desde)
        if hasta:
            qs = qs.filter(fecha_compromiso__lte=hasta)
        return qs

    def con_fecha_despacho(self, desde, hasta):
        qs = self
        if desde:
            qs = qs.filter(fecha_despacho__gte=desde)
        if hasta:
            qs = qs.filter(fecha_despacho__lte=hasta)
        return qs


#Extensión 1:1 de un Pedido para el módulo de seguimiento del área ONT (ver
#backlog_proyecto/backlog-seguimiento-ont.md). Nace como reemplazo de la pestaña "Despachos ONT" de
#la planilla de Google Sheets que hoy se llena a mano — mismos campos, mismo flujo de trabajo.
#
#Los campos "automáticos" de la planilla (courier, OT, contacto, dirección, observaciones) NO se
#guardan acá — son properties que leen en vivo desde `pedido`/`pedido.envio`. Guardarlos como columna
#propia obligaría a sincronizarlos cada vez que el pedido cambia (editar, despachar, re-despachar tras
#incidencia, anular envío...) y es justo la fuente de bugs que Felipe quería evitar (2026-08-28): el
#courier/OT de un pedido solo se edita desde "Mis pedidos"/"Pedidos a Despachar", nunca desde acá.
class DespachoOnt(models.Model):
    objects = DespachoOntQuerySet.as_manager()

    class Accion(models.TextChoices):
        GUIA_LISTA = "GUIA_LISTA", "Guía lista"
        GUIA_PEDIDA = "GUIA_PEDIDA", "Guía pedida"
        PEDIR_GUIA = "PEDIR_GUIA", "Pedir guía"
        NO_ENVIAR_AUN = "NO_ENVIAR_AUN", "No enviar aún"
        ENTREGADO = "ENTREGADO", "Entregado"
        GARANTIA = "GARANTIA", "Garantía"

    pedido = models.OneToOneField(
        "pedidos.Pedido", on_delete=models.CASCADE, related_name="seguimiento_ont"
    )

    #Campos manuales — los llena el ejecutivo ONT o Logística, igual que en la planilla.
    accion = models.CharField(max_length=20, choices=Accion.choices, blank=True)
    fecha_compromiso = models.DateField(null=True, blank=True)
    #La planilla mezclaba "Semana X" con fechas reales y notas de retiro en tienda — se pidió dejarla
    #como fecha real, marcando con este flag cuándo es aproximada (se muestra "(aprox.)" en pantalla).
    fecha_compromiso_aproximada = models.BooleanField(default=False)
    fecha_despacho = models.DateField(null=True, blank=True)
    guia_despacho = models.CharField(max_length=100, blank=True)
    observaciones_ok = models.TextField(blank=True)
    confirmacion_cliente = models.BooleanField(default=False)
    retorno_documento = models.BooleanField(default=False)
    pedido_recibido = models.BooleanField(default=False)
    observaciones_entrega = models.TextField(blank=True)
    enviar = models.BooleanField(default=False)
    #Texto libre y no booleano a propósito: en la planilla real la mayoría de las filas trae
    #"TRUE"/"FALSE" pero alguna trae una nota larga en su lugar (ej. reintento de entrega) — no es
    #estrictamente un booleano en la práctica.
    confirmacion_carga = models.TextField(blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    modificado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_en"]

    def __str__(self):
        return f"Seguimiento ONT — {self.pedido.origen}-{self.pedido.num_pedido}"

    #--- Campos "automáticos": en vivo desde el pedido, nunca almacenados acá ---
    @property
    def courier(self):
        return self.pedido.get_courier_display()

    @property
    def ot(self):
        return self.pedido.envio.orden_transporte if self.pedido.envio_id else ""

    @property
    def envio_id(self):
        return self.pedido.envio_id

    @property
    def nombre_contacto(self):
        return self.pedido.nombre_contacto

    @property
    def telefono_contacto(self):
        return self.pedido.telefono_contacto

    @property
    def ciudad_destino(self):
        return self.pedido.direccion_ciudad

    @property
    def direccion_destino(self):
        partes = [self.pedido.direccion_calle, self.pedido.direccion_comuna, self.pedido.direccion_ciudad]
        return ", ".join(parte for parte in partes if parte)

    @property
    def observaciones(self):
        return self.pedido.observaciones
