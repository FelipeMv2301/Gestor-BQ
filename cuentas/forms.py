from django import forms
from .models import PerfilUsuario
from ejecutivos.models import Ejecutivo

INPUT = "w-full text-sm rounded-lg border border-linestrong bg-field text-body px-3 py-2 focus:border-brand focus:outline-none"


class PerfilUsuarioForm(forms.ModelForm):
    #Códigos SAP a mano: uno o varios separados por coma. Se resuelven a Ejecutivo y se guardan en la M2M.
    codigos_sap = forms.CharField(
        required=False,
        label="Códigos SAP",
        help_text="Uno o varios, separados por coma. Ej: 10, 20",
    )

    class Meta:
        model = PerfilUsuario
        fields = ["rol", "ve_todas_cotizaciones"]   # `ejecutivos` (M2M) se maneja vía el campo de texto codigos_sap
        labels = {"rol": "Rol", "ve_todas_cotizaciones": "Ve todas las cotizaciones"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rol"].required = False
        #Prefill: los códigos actuales del perfil, para editarlos in situ
        if self.instance and self.instance.pk:
            self.fields["codigos_sap"].initial = ", ".join(str(c) for c in self.instance.codigos_sap)
        for name, f in self.fields.items():
            if name == "ve_todas_cotizaciones":
                f.widget.attrs["class"] = "accent-brand w-4 h-4"   # checkbox, no el INPUT de texto
            else:
                f.widget.attrs["class"] = INPUT
        self.fields["codigos_sap"].widget.attrs["placeholder"] = "10, 20"

    #Parsea el texto → lista de Ejecutivo. Valida que cada código sea numérico y exista.
    #Varios perfiles SÍ pueden compartir el mismo código (decisión de Felipe 2026-09-02: visibilidad
    #compartida de los pedidos de ese código entre todos sus dueños) — ya no se valida "ocupado".
    def clean_codigos_sap(self):
        crudo = (self.cleaned_data.get("codigos_sap") or "").strip()
        if not crudo:
            return []

        ejecutivos = []
        vistos = set()
        for parte in crudo.replace(";", ",").split(","):
            parte = parte.strip()
            if not parte:
                continue
            if not parte.isdigit():
                raise forms.ValidationError(f"'{parte}' no es un código válido (solo números).")
            codigo = int(parte)
            if codigo in vistos:
                continue
            vistos.add(codigo)

            ejecutivo = Ejecutivo.objects.filter(codigo_sap=codigo).first()
            if not ejecutivo:
                raise forms.ValidationError(f"No existe un ejecutivo con código SAP {codigo}.")
            ejecutivos.append(ejecutivo)
        return ejecutivos

    def save(self, commit=True):
        perfil = super().save(commit=False)
        #El Admin ahora gestiona los códigos por la M2M; el escalar legacy deja de aplicar a este perfil
        #(así, si borra todos los códigos, `codigos_sap` no cae de vuelta al escalar viejo).
        perfil.codigo_empleado_sap = None
        if commit:
            perfil.save()
            perfil.ejecutivos.set(self.cleaned_data.get("codigos_sap", []))
        return perfil
