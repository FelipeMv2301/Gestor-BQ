from django import forms
from .models import Pedido

INPUT = "w-full text-sm rounded-lg border border-linestrong bg-white px-3 py-2 focus:border-brand focus:outline-none"

class PedidoEditForm(forms.ModelForm):
    class Meta:
        model = Pedido
        fields = ["rut", "razon_social", "nombre_contacto", "telefono_contacto", "email_contacto",
                  "direccion_calle", "direccion_depto", "direccion_comuna", "direccion_ciudad",
                  "courier", "retirar_en", "observaciones"]
        labels = {
            "rut": "RUT", "razon_social": "Razón social", "nombre_contacto": "Contacto",
            "telefono_contacto": "Teléfono", "email_contacto": "Email", "direccion_calle": "Calle",
            "direccion_depto": "Depto / Of.", "direccion_comuna": "Comuna", "direccion_ciudad": "Ciudad",
            "courier": "Courier", "retirar_en": "Retiro en", "observaciones": "Observaciones",
        }

    def __init__(self, *args, permitidos=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Deja SOLO los campos que el rol puede editar (permisos.campos_editables)
        if permitidos is not None:
            for name in list(self.fields):
                if name not in permitidos:
                    self.fields.pop(name)
        for f in self.fields.values():
            if isinstance(f.widget, forms.Textarea):
                f.widget.attrs["rows"] = 3
            f.widget.attrs["class"] = INPUT