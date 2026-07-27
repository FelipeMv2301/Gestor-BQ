from utils import COMUNAS_CL


# Expone datos de referencia estáticos a TODOS los templates (ej. lista de comunas para
# el selector buscable Tom Select). Así el <script id="comunas-data"> vive en base.html
# —siempre presente, no depende de un form cargado por HTMX—.
def datos_referencia(request):
    return {"COMUNAS_CL": COMUNAS_CL}
