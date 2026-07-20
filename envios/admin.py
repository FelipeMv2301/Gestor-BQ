from django.contrib import admin
from .models import EnvioCourier
from django.utils.html import format_html, escape
from django.utils.safestring import mark_safe

@admin.register(EnvioCourier)
class EnvioCourierAdmin(admin.ModelAdmin):
    list_display = ("id", "courier", "estado", "orden_transporte", "datos_courier_formateado", "creado_en", "actualizado_en")

    #Permite darle una estructura más visible a los datos que se rescaten (envien y regresen) del courier.
    def datos_courier_formateado(self, obj):
        if not obj.datos_courier:
            return "-"
        lineas = []
        for clave, valor in obj.datos_courier.items():
            if isinstance(valor, list):
                partes_bulto = []
                for bulto in valor:
                    texto_bulto = ""
                    for campo, dato in bulto.items():
                        texto_bulto += f"{campo}={dato} "
                    partes_bulto.append(texto_bulto.strip())
                valor_texto = " / ".join(partes_bulto)
            else:
                valor_texto = valor
            lineas.append(escape(f"{clave}: {valor_texto}"))

        return mark_safe("<br>".join(lineas))
