import json
from django.core.management.base import BaseCommand
from django.conf import settings
from integraciones import sap_client


class Command(BaseCommand):
    help = "Sondeo: trae la última cotización de SAP y la imprime (para validar campos)."

    def _pedir(self, cookies, select):
        url = f"{settings.SAP_URL}/Quotations"
        params = {"$select": select, "$orderby": "DocEntry desc", "$top": 1}
        respuesta, _ = sap_client.solicitar_sap("GET", url, cookies, params=params)
        return respuesta

    def handle(self, *args, **options):
          cookies = sap_client.obtener_cookies_sap()

          url = f"{settings.SAP_URL}/Quotations"
          params = {
              "$select": "DocNum,DocTotal,VatSum,DocumentLines",
              "$filter": "VatSum gt 0",
              "$orderby": "DocEntry desc",
              "$top": 1,
          }
          respuesta, _ = sap_client.solicitar_sap("GET", url, cookies, params=params)
          self.stdout.write(f"HTTP {respuesta.status_code}")
          if respuesta.status_code != 200:
              self.stdout.write(respuesta.text)
              return

          valor = respuesta.json().get("value", [])
          if not valor:
              self.stdout.write("Sin cotizaciones con VatSum > 0.")
              return

          cot = valor[0]
          doc_total = cot.get("DocTotal")
          vat = cot.get("VatSum")
          self.stdout.write(f"DocNum={cot.get('DocNum')}  DocTotal={doc_total}  VatSum={vat}  "
                            f"DocTotal-VatSum={round((doc_total or 0) - (vat or 0), 2)}")

          # Primeras 2 líneas: para ver qué campos usar en LineaCotizacion
          for linea in (cot.get("DocumentLines") or [])[:2]:
              self.stdout.write(json.dumps(
                  {k: linea.get(k) for k in
                   ("ItemCode", "ItemDescription", "Quantity", "UnitPrice", "Price", "LineTotal", "PriceAfterVAT")},
                  indent=2, ensure_ascii=False, default=str))
