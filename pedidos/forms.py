from django import forms
from .models import Pedido, SkuCourier
from .services import opciones_courier_servicio

INPUT = "w-full text-sm rounded-lg border border-linestrong bg-field text-body px-3 py-2 focus:border-brand focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"

class PedidoEditForm(forms.ModelForm):
    class Meta:
        model = Pedido
        fields = ["rut", "razon_social", "nombre_contacto", "telefono_contacto", "email_contacto",
                  "direccion_calle", "direccion_depto", "direccion_comuna", "direccion_ciudad",
                  "tipo_entrega", "courier", "retirar_en", "observaciones"]
        labels = {
            "rut": "RUT", "razon_social": "Razón social", "nombre_contacto": "Contacto",
            "telefono_contacto": "Teléfono", "email_contacto": "Email", "direccion_calle": "Calle",
            "direccion_depto": "Depto / Of.", "direccion_comuna": "Comuna", "direccion_ciudad": "Ciudad",
            "tipo_entrega": "Tipo de entrega", "courier": "Courier", "retirar_en": "Retiro en",
            "observaciones": "Observaciones",
        }

    def __init__(self, *args, permitidos=None, **kwargs):
        super().__init__(*args, **kwargs)
        # El select de courier incluye el servicio (Express/Terrestre, etc.) como una sola opción,
        # armada desde SkuCourier — cada courier muestra solo SUS propios servicios configurados.
        if "courier" in self.fields:
            self.fields["courier"] = forms.ChoiceField(
                choices=opciones_courier_servicio(), required=False, label="Courier")
            if self.instance.courier:
                self.initial["courier"] = f"{self.instance.courier}|{self.instance.servicio_courier_codigo}"
        # Deja SOLO los campos que el rol puede editar (permisos.campos_editables)
        if permitidos is not None:
            for name in list(self.fields):
                if name not in permitidos:
                    self.fields.pop(name)
        for f in self.fields.values():
            if isinstance(f.widget, forms.Textarea):
                f.widget.attrs["rows"] = 3
            f.widget.attrs["class"] = INPUT
        # Marca la comuna para el selector buscable (Tom Select, ver base.html::initComunas)
        if "direccion_comuna" in self.fields:
            self.fields["direccion_comuna"].widget.attrs["data-comuna"] = "1"

    #El valor combinado "COURIER|CODIGO" reparte a los 3 campos reales del modelo. Si llega un valor
    #plano sin "|" (ej. el select rápido de la tabla, que solo cambia courier) no toca el servicio.
    def clean_courier(self):
        valor = self.cleaned_data.get("courier") or ""
        if "|" not in valor:
            return valor

        courier_valor, _, codigo = valor.partition("|")
        self.instance.servicio_courier_codigo = codigo
        if codigo:
            fila = SkuCourier.objects.filter(courier=courier_valor, servicio_codigo=codigo).first()
            self.instance.servicio_courier_nombre = fila.servicio_nombre if fila else ""
        else:
            self.instance.servicio_courier_nombre = ""
        return courier_valor


class SkuCourierForm(forms.ModelForm):
    class Meta:
        model = SkuCourier
        fields = ["sku", "courier", "servicio_codigo", "servicio_nombre"]
        labels = {
            "sku": "SKU (ItemCode SAP)", "courier": "Courier",
            "servicio_codigo": "Código de servicio (para la API del courier)",
            "servicio_nombre": "Nombre del servicio (para mostrar)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = INPUT