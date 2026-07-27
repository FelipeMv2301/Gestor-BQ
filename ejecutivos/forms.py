from django import forms
from .models import Ejecutivo

INPUT = "w-full text-sm rounded-lg border border-linestrong bg-field text-body px-3 py-2 focus:border-brand focus:outline-none"

class EjecutivoForm(forms.ModelForm):
    class Meta:
        model = Ejecutivo
        fields = ["codigo_sap", "nombre", "email", "activo"]
        labels = {
            "codigo_sap": "Código SAP", "nombre": "Nombre",
            "email": "Email", "activo": "Activo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, f in self.fields.items():
            if name == "activo":
                continue  # checkbox, no le pisamos la clase
            f.widget.attrs["class"] = INPUT