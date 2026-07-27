from django import forms
from .models import PerfilUsuario

INPUT = "w-full text-sm rounded-lg border border-linestrong bg-field text-body px-3 py-2 focus:border-brand focus:outline-none"


class PerfilUsuarioForm(forms.ModelForm):
    class Meta:
        model = PerfilUsuario
        fields = ["rol", "codigo_empleado_sap"]
        labels = {"rol": "Rol", "codigo_empleado_sap": "Código SAP"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rol"].required = False
        for f in self.fields.values():
            f.widget.attrs["class"] = INPUT
