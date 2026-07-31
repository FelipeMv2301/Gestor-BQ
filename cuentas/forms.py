from django import forms
from .models import PerfilUsuario

INPUT = "w-full text-sm rounded-lg border border-linestrong bg-field text-body px-3 py-2 focus:border-brand focus:outline-none"


class PerfilUsuarioForm(forms.ModelForm):
    class Meta:
        model = PerfilUsuario
        fields = ["rol", "codigo_empleado_sap", "ve_todas_cotizaciones"]
        labels = {"rol": "Rol", "codigo_empleado_sap": "Código SAP",
                  "ve_todas_cotizaciones": "Ve todas las cotizaciones"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rol"].required = False
        for name, f in self.fields.items():
            if name == "ve_todas_cotizaciones":
                f.widget.attrs["class"] = "accent-brand w-4 h-4"   # checkbox, no el INPUT de texto
            else:
                f.widget.attrs["class"] = INPUT
