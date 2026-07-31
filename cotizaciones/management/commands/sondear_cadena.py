from django.core.management.base import BaseCommand
from django.conf import settings
from integraciones import sap_client
from cotizaciones.models import Cotizacion

SELECT_DOC = "DocEntry,DocNum,DocDate,Cancelled,CardCode,DocumentLines"


class Command(BaseCommand):
    help = "Sondeo C3: traza Cotización→NV→Guía→Factura a NIVEL DE LÍNEA (SPK-C1)."

    def add_arguments(self, parser):
        parser.add_argument("--docentry", type=int, default=None)

    def _traer(self, entidad, card_code, fecha_desde, cookies):
        filtro = f"CardCode eq '{card_code}' and DocDate ge '{fecha_desde}'"
        return sap_client.obtener_todas_las_paginas(
            f"{settings.SAP_URL}/{entidad}",
            {"$select": SELECT_DOC, "$filter": filtro},
            cookies,
        )

    def _indexar(self, docs):
        # {DocEntry: {LineNum: linea}} — para buscar la línea base exacta.
        idx = {}
        for d in docs:
            idx[d.get("DocEntry")] = {l.get("LineNum"): l for l in (d.get("DocumentLines") or [])}
        return idx

    def _traza_a_cotizacion(self, bt, be, bl, idx, docentry_cot, depth=0):
        # ¿La línea (BaseType, BaseEntry, BaseLine) traza hasta una línea de nuestra cotización?
        # idx = {13: {...facturas}, 15: {...guías}, 17: {...órdenes}} indexadas por DocEntry→LineNum.
        if depth > 5 or be is None:
            return False
        if bt == 23:                      # base = Cotización
            return be == docentry_cot
        linea = idx.get(bt, {}).get(be, {}).get(bl)  # base = Factura(13)/Guía(15)/Orden(17)
        if not linea:
            return False
        return self._traza_a_cotizacion(linea.get("BaseType"), linea.get("BaseEntry"),
                                        linea.get("BaseLine"), idx, docentry_cot, depth + 1)

    def _sumar(self, docs, idx, docentry_cot):
        total, docnums, detalle = 0.0, set(), []
        for d in docs:
            if d.get("Cancelled") == "tYES":
                continue
            for l in (d.get("DocumentLines") or []):
                if self._traza_a_cotizacion(l.get("BaseType"), l.get("BaseEntry"),
                                            l.get("BaseLine"), idx, docentry_cot):
                    total += (l.get("LineTotal") or 0)
                    docnums.add(d.get("DocNum"))
                    detalle.append((d.get("DocNum"), l.get("ItemCode"), l.get("Quantity"),
                                    l.get("LineTotal"), l.get("BaseType")))
        return total, docnums, detalle

    def handle(self, *args, **options):
        cookies = sap_client.obtener_cookies_sap()
        docentry = options["docentry"]
        cot = (Cotizacion.objects.get(docentry=docentry) if docentry
               else Cotizacion.objects.filter(doc_status="bost_Close").first())
        if not cot:
            self.stdout.write("Sin cotización para probar.")
            return

        card_code, fecha = cot.card_code, cot.fecha_contabilizacion.isoformat()
        self.stdout.write(f"Cotización DocNum={cot.docnum} DocEntry={cot.docentry} "
                          f"CardCode={card_code} neto={cot.neto}")

        self.stdout.write("[COTIZACIÓN — líneas]")
        for l in (cot.lineas or []):
            self.stdout.write(f"  LineNum={l.get('LineNum')} {l.get('ItemCode')} "
                              f"qty={l.get('Quantity')} LineTotal={l.get('LineTotal')}")

        idx_orden = self._indexar(self._traer("Orders", card_code, fecha, cookies))
        idx_guia = self._indexar(self._traer("DeliveryNotes", card_code, fecha, cookies))
        facturas = self._traer("Invoices", card_code, fecha, cookies)
        notas = self._traer("CreditNotes", card_code, fecha, cookies)
        # idx por BaseType: la NC referencia la Factura(13), la Factura la Guía(15)/Orden(17)
        idx = {13: self._indexar(facturas), 15: idx_guia, 17: idx_orden}

        fact_total, fact_nums, fact_det = self._sumar(facturas, idx, cot.docentry)
        nc_total, nc_nums, _ = self._sumar(notas, idx, cot.docentry)
        total_facturado = fact_total - nc_total

        self.stdout.write("\n[FACTURAS — líneas ligadas] (DocNum, ItemCode, qty, LineTotal, BaseType)")
        for fila in fact_det:
            self.stdout.write(f"  {fila}")
        self.stdout.write(f"[FACT] ligadas={sorted(fact_nums)} → {round(fact_total, 2)}")
        self.stdout.write(f"[NC]   ligadas={sorted(nc_nums)} → {round(nc_total, 2)}")
        self.stdout.write(f"\n[RESULTADO]")
        self.stdout.write(f"  total_facturado = {round(total_facturado, 2)}")
        self.stdout.write(f"  neto cotización = {cot.neto}")
        self.stdout.write(f"  diferencia      = {round(float(cot.neto) - total_facturado, 2)}")
