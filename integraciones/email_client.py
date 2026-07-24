import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings
from pedidos.models import Pedido
import datetime


def _generar_direccion(pedido):
    partes = [pedido.direccion_calle, pedido.direccion_comuna, pedido.direccion_ciudad]
    return ", ".join(parte for parte in partes if parte)


#Genera el link de seguimiento según el transportista. Chibra/MoveUP no tienen (sin documentación pública),
#queda en blanco a propósito hasta que se confirme una URL real.
def _generar_track_url(courier, folio):
    if not folio:
        return ""

    courier = courier.lower()
    if "starken" in courier:
        return f"https://www.starken.cl/seguimiento?codigo={folio}"
    if "chilexpress" in courier:
        return f"https://www.chilexpress.cl/seguimiento-envio?transporte={folio}"
    return ""


def _template_retiro(pedido):
    anio = datetime.datetime.now().year

    es_bodega = pedido.retirar_en == Pedido.RetirarEn.RETIRO_BODEGA_N3A
    direccion = "Av. Til Til 2756, Macul, Región Metropolitana, Bodega N3A" if es_bodega else "Av. Til Til 2756, Macul, Región Metropolitana, Bodega S2"

    razon_social_line = ""
    if pedido.razon_social:
        razon_social_line = f'<p style="font-size: 16px; margin-bottom: 25px;">Empresa / Razón Social: <strong>{pedido.razon_social}</strong></p>'

    promo_html = ""
    if settings.EMAIL_PROMO_ACTIVA and settings.EMAIL_PICKUP_PROMO_IMG_URL:
        promo_html = f'''
        <div style="text-align: center; margin-top: 25px;">
          <img src="{settings.EMAIL_PICKUP_PROMO_IMG_URL}" alt="Promoción retiro en tienda" style="max-width: 100%; height: auto; border-radius: 8px;">
        </div>'''

    return f"""
    <div style="font-family: 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
      <div style="background-color: #004a99; padding: 30px; text-align: center;">
        <img src="https://drive.google.com/uc?export=view&id=1WZwK5e0Q2qgUfAvKCqVHrd0oKA2d0CM_" alt="Bioquímica.cl" style="max-height: 80px; width: auto;">
      </div>
      <div style="padding: 35px; color: #333; line-height: 1.6;">
        <h1 style="color: #00b0ca; font-size: 26px; margin-top: 0; margin-bottom: 20px;">¡Tu pedido está listo para retiro! 🎉</h1>
        <p style="font-size: 16px; margin-bottom: 25px;">Hola <strong>{pedido.nombre_contacto}</strong>,</p>
        {razon_social_line}
        <p style="font-size: 16px; margin-bottom: 25px;">¡Buenas noticias! Tu pedido <strong>#{pedido.num_pedido}</strong> ya ha sido preparado y te espera en nuestras instalaciones.</p>
        <div style="background-color: #f9f9f9; border-left: 4px solid #00b0ca; padding: 20px; margin-bottom: 25px;">
          <h3 style="margin-top: 0; font-size: 18px; color: #000;">📍 ¿Dónde retirar?</h3>
          <p style="margin-bottom: 10px; font-size: 16px;">{direccion}</p>
          <a href="https://maps.app.goo.gl/9T8vLd6W5J2vJt8q9" target="_blank" style="background-color: #00b0ca; color: white; padding: 10px 15px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold; font-size: 14px;">Ver en Google Maps</a>
        </div>
        <div style="margin-bottom: 25px;">
          <h3 style="margin-top: 0; font-size: 18px; color: #000;">🕒 Horarios de retiro</h3>
          <p style="margin-bottom: 0; font-size: 15px;"><strong>Lunes a Jueves:</strong> 08:30 a 16:30 hrs.</p>
          <p style="margin-top: 5px; font-size: 15px;"><strong>Viernes:</strong> 08:30 a 15:00 hrs.</p>
        </div>
        <div style="background-color: #fff3cd; color: #856404; padding: 20px; border-radius: 8px; font-size: 14px; border: 1px solid #ffeeba;">
          <strong>⚠️ Importante antes de venir:</strong>
          <p style="margin-bottom: 0;">Para poder entregar tu pedido, debes presentar el <b>número de pedido</b> y tu <b>documento de identidad</b>.</p>
          <p style="margin-top: 10px;">Si retira otra persona, por favor avisar previamente a <a href="mailto:ventas@bioquimica.cl" style="color: #856404; font-weight: bold;">ventas@bioquimica.cl</a>.</p>
        </div>
        {promo_html}
      </div>
      <div style="background-color: #f1f1f1; padding: 25px; text-align: center; color: #666; font-size: 13px;">
        <p style="margin: 0 0 10px 0;">¿Necesitas ayuda? Escríbenos a <a href="mailto:web@bioquimica.cl" style="color: #00b0ca; text-decoration: none;">web@bioquimica.cl</a></p>
        <p style="margin: 0;">© {anio} Bioquimica.cl. Todos los derechos reservados.</p>
      </div>
    </div>
    """


def _template_despacho(pedido, folio, track_url):
    anio = datetime.datetime.now().year
    display_folio = folio if folio else "Sin definir"

    razon_social_line = ""
    if pedido.razon_social:
        razon_social_line = f'<p style="margin: 0 0 10px 0; font-size: 16px;"><strong>Razón Social:</strong> {pedido.razon_social}</p>'

    direccion = _generar_direccion(pedido)
    direccion_line = ""
    if direccion:
        direccion_line = f'<p style="margin: 0 0 10px 0; font-size: 16px;"><strong>Dirección de entrega:</strong> {direccion}</p>'

    tracking_html = f"""
    <div style="background-color: #f4f7f6; border-radius: 8px; padding: 20px; margin-bottom: 25px; border-left: 4px solid #95c11f;">
      {razon_social_line}
      {direccion_line}
      <p style="margin: 0 0 10px 0; font-size: 16px;"><strong>Estado:</strong> Despachado</p>
      <p style="margin: 0 0 10px 0; font-size: 16px;"><strong>Transportista:</strong> {pedido.get_courier_display()}</p>
      <p style="margin: 0 0 0 0; font-size: 16px;"><strong>Orden de transporte:</strong> {display_folio}</p>
    </div>
    """

    track_button_html = ""
    if track_url:
        track_button_html = f"""
        <div style="margin: 30px 0; text-align: center;">
          <a href="{track_url}" target="_blank" style="background-color: #00b0ca; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Hacer seguimiento a mi pedido</a>
        </div>
        """

    return f"""
    <div style="font-family: 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
      <div style="background-color: #004a99; padding: 30px; text-align: center;">
        <img src="https://drive.google.com/uc?export=view&id=1WZwK5e0Q2qgUfAvKCqVHrd0oKA2d0CM_" alt="Bioquímica.cl" style="max-height: 80px; width: auto;">
      </div>
      <div style="padding: 35px; color: #333; line-height: 1.6;">
        <h1 style="color: #00b0ca; font-size: 26px; margin-top: 0; margin-bottom: 20px;">¡Tu pedido va en camino! 🚚</h1>
        <p style="font-size: 16px; margin-bottom: 25px;">Hola <strong>{pedido.nombre_contacto}</strong>,</p>
        <p style="font-size: 16px; margin-bottom: 25px;">Te informamos que tu pedido <strong>#{pedido.num_pedido}</strong> ya ha sido procesado y entregado a nuestro servicio de transporte.</p>
        {tracking_html}
        {track_button_html}
        <p style="font-size: 15px; color: #555;">Recuerda que los tiempos de entrega dependen del transportista y tu ubicación. Te notificaremos si hay actualizaciones importantes en el seguimiento.</p>
        <div style="margin-top: 30px; text-align: center;">
          <p style="font-size: 14px; color: #777;">Si tienes dudas sobre tu despacho, no dudes en contactarnos.</p>
        </div>
      </div>
      <div style="background-color: #f1f1f1; padding: 25px; text-align: center; color: #666; font-size: 13px;">
        <p style="margin: 0 0 10px 0;">¿Necesitas ayuda? Escríbenos a <a href="mailto:web@bioquimica.cl" style="color: #00b0ca; text-decoration: none;">web@bioquimica.cl</a></p>
        <p style="margin: 0;">© {anio} Bioquimica.cl. Todos los derechos reservados.</p>
      </div>
    </div>
    """

def enviar_notificacion(pedido):
    if not settings.EMAIL_SENDER or not settings.EMAIL_PASSWORD:
        raise ValueError("[!] Error: faltan credenciales SMTP (EMAIL_SENDER/EMAIL_PASSWORD en .env).")

    if not pedido.email_contacto:
        raise ValueError(f"[!] Error: Pedido {pedido.origen}-{pedido.num_pedido} no tiene email de contacto.")

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Bioquímica.cl <{settings.EMAIL_SENDER}>"
    msg["To"] = pedido.email_contacto

    if pedido.tipo_entrega == Pedido.TipoEntrega.RETIRO_BIOQUIMICA:
        msg["Subject"] = f"¡Tu pedido #{pedido.num_pedido} está listo para retiro! 🎉"
        html = _template_retiro(pedido)
    else:
        if pedido.envio_id is None:
            raise ValueError(f"[!] Error: Pedido {pedido.origen}-{pedido.num_pedido} es Despacho pero no tiene un envío asignado todavía.")
        msg["Subject"] = f"¡Tu pedido #{pedido.num_pedido} va en camino! 🚚"
        folio = pedido.envio.orden_transporte
        track_url = _generar_track_url(pedido.get_courier_display(), folio)
        html = _template_despacho(pedido, folio, track_url)

    msg.attach(MIMEText(html, "html"))

    copia_oculta = [e.strip() for e in settings.EMAIL_BCC.split(",") if "@" in e]
    if pedido.ejecutivo and pedido.ejecutivo.email and pedido.ejecutivo.email != pedido.email_contacto and pedido.ejecutivo.email not in copia_oculta:
        copia_oculta.append(pedido.ejecutivo.email)

    destinatarios = [pedido.email_contacto] + copia_oculta

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(settings.EMAIL_SENDER, settings.EMAIL_PASSWORD)
        server.sendmail(settings.EMAIL_SENDER, destinatarios, msg.as_string())