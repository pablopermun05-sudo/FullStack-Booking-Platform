
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.db import transaction
from django.template.defaultfilters import escape
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

def send_booking_change_proposal_email(request, booking, proposal, raw_token):
    """
    Envía al huésped una propuesta de cambio con formato HTML y texto.
    Devuelve True si Django confirma el envío y False si falla.
    """
    proposal_url = request.build_absolute_uri(
      reverse(
          "booking_change_proposal_detail",
          kwargs={"token": raw_token},
      )
  )

    property_title = booking.property.title

    # Teléfono del usuario propietario de la vivienda.
    owner_phone = booking.property.owner.phone_number
    safe_owner_phone = (
        escape(str(owner_phone))
        if owner_phone
        else None
    )

    guest_name = booking.guest_first_name or "huésped"
    original_total = booking.total_price
    proposed_total = proposal.proposed_total_price
    expiry = timezone.localtime(proposal.expires_at)

    subject = f"Propuesta de cambio de reserva | {property_title}"

    # Versión de texto plano.
    text_message = f"""Hola {guest_name},

El alojamiento {property_title} te ha enviado una propuesta para modificar tu reserva.

RESERVA ACTUAL
Entrada: {booking.initial_date:%d/%m/%Y}
Salida: {booking.final_date:%d/%m/%Y}
Huéspedes: {booking.guest_count}
Importe total original: {original_total:.2f} €

NUEVA PROPUESTA
Entrada: {proposal.proposed_initial_date:%d/%m/%Y}
Salida: {proposal.proposed_final_date:%d/%m/%Y}
Huéspedes: {proposal.proposed_guest_count}
Importe total propuesto: {proposed_total:.2f} €

La propuesta caduca el {expiry:%d/%m/%Y a las %H:%M}.

Revisa la propuesta y responde aquí:
{proposal_url}

Si tienes dudas, contacta con el alojamiento{f' en el teléfono {owner_phone}' if owner_phone else ''}.

Notificación automática de {property_title}.
"""

    # Escapar los datos dinámicos para el HTML.
    safe_guest = escape(guest_name)
    safe_property = escape(property_title)
    safe_url = escape(proposal_url)

    html_message = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Propuesta de cambio de reserva</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f5f7;
             font-family:Arial,Helvetica,sans-serif;color:#263238;">
  <div style="display:none;max-height:0;overflow:hidden;">
    Tienes una propuesta de cambio pendiente para tu reserva en {safe_property}.
  </div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
         style="background-color:#f3f5f7;padding:32px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0"
               style="width:100%;max-width:600px;background:#ffffff;
                      border-radius:12px;overflow:hidden;">
          <tr>
            <td style="background:#173f35;padding:28px 32px;color:#ffffff;">
              <p style="margin:0;font-size:12px;letter-spacing:2px;
                        text-transform:uppercase;color:#d5e8df;">
                Notificación de reserva
              </p>
              <h1 style="margin:10px 0 0;font-size:25px;line-height:1.3;">
                Propuesta de cambio
              </h1>
            </td>
          </tr>

          <tr>
            <td style="padding:30px 32px 12px;">
              <p style="margin:0 0 12px;font-size:16px;">
                Hola {safe_guest},
              </p>
              <p style="margin:0;color:#52615d;font-size:15px;line-height:1.7;">
                <strong>{safe_property}</strong> te ha enviado una propuesta
                para modificar las condiciones de tu reserva.
                Revisa los detalles antes de responder.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:18px 32px 8px;">
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="border:1px solid #e3e9e6;border-radius:8px;">
                <tr>
                  <td colspan="2"
                      style="padding:16px 18px;background:#f7f9f8;
                             font-size:14px;font-weight:bold;">
                    Reserva actual
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 18px;color:#66736f;font-size:14px;">
                    Entrada
                  </td>
                  <td align="right" style="padding:12px 18px;font-size:14px;">
                    {booking.initial_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 18px;color:#66736f;font-size:14px;">
                    Salida
                  </td>
                  <td align="right" style="padding:12px 18px;font-size:14px;">
                    {booking.final_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 18px;color:#66736f;font-size:14px;">
                    Huéspedes
                  </td>
                  <td align="right" style="padding:12px 18px;font-size:14px;">
                    {booking.guest_count}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 18px;border-top:1px solid #e3e9e6;
                             font-weight:bold;font-size:14px;">
                    Precio total actual
                  </td>
                  <td align="right"
                      style="padding:14px 18px;border-top:1px solid #e3e9e6;
                             font-weight:bold;font-size:15px;">
                    {original_total:.2f} €
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:12px 32px 18px;">
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="border:1px solid #cfe3d8;border-radius:8px;">
                <tr>
                  <td colspan="2"
                      style="padding:16px 18px;background:#edf6f1;
                             color:#173f35;font-size:14px;font-weight:bold;">
                    Nueva propuesta
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 18px;color:#52615d;font-size:14px;">
                    Entrada
                  </td>
                  <td align="right" style="padding:12px 18px;font-size:14px;">
                    {proposal.proposed_initial_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 18px;color:#52615d;font-size:14px;">
                    Salida
                  </td>
                  <td align="right" style="padding:12px 18px;font-size:14px;">
                    {proposal.proposed_final_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 18px;color:#52615d;font-size:14px;">
                    Huéspedes
                  </td>
                  <td align="right" style="padding:12px 18px;font-size:14px;">
                    {proposal.proposed_guest_count}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 18px;border-top:1px solid #cfe3d8;
                             font-weight:bold;font-size:14px;">
                    Precio total propuesto
                  </td>
                  <td align="right"
                      style="padding:14px 18px;border-top:1px solid #cfe3d8;
                             color:#173f35;font-weight:bold;font-size:20px;">
                    {proposed_total:.2f} €
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 24px;">
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="background:#fff8e8;border-radius:8px;">
                <tr>
                  <td style="padding:15px 17px;color:#775b20;font-size:13px;
                             line-height:1.6;">
                    <strong>Plazo para responder</strong><br>
                    Esta propuesta caduca el
                    <strong>{expiry:%d/%m/%Y a las %H:%M}</strong>.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 32px 30px;">
              <a href="{safe_url}"
                 style="display:inline-block;background:#173f35;color:#ffffff;
                        text-decoration:none;padding:15px 28px;
                        border-radius:6px;font-size:15px;font-weight:bold;">
                Revisar propuesta
              </a>
            </td>
          </tr>

          <tr>
            <td style="padding:22px 32px;background:#f7f9f8;
                       border-top:1px solid #e8eeeb;">
              <p style="margin:0;color:#65716c;font-size:12px;line-height:1.7;">
                Este mensaje es una notificación automática relacionada con
                tu reserva en {safe_property}. Si tienes dudas, contacta con
                el alojamiento
                {f'en el teléfono {safe_owner_phone}' if safe_owner_phone else ''}.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    try:
        
        recipient_email = (booking.guest_email or "").strip()

        if not recipient_email:
            logger.error(
                "La reserva %s no tiene un email de huésped.",
                booking.pk,
            )
            return False

        if not recipient_email:
            logger.error(
                "La reserva %s no tiene un email de destinatario.",
                booking.pk,
            )
            return False

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
        )
        email.attach_alternative(html_message, "text/html")

        sent_count = email.send(fail_silently=False)

        if sent_count != 1:
            logger.error(
                "No se confirmó el envío de la propuesta %s a %s.",
                proposal.pk,
                recipient_email,
            )
            return False

        return True

    except Exception:
        logger.exception(
            "Error al enviar el correo de la propuesta %s "
            "para la reserva %s.",
            proposal.pk,
            booking.pk,
        )
        return False

def send_booking_change_proposal_status_email(booking, proposal, status):
    """
    Envía al propietario un correo HTML y de texto plano cuando una
    propuesta de cambio de reserva se acepta, rechaza o caduca.

    Devuelve True si Django confirma el envío y False si falla.
    """
    from datetime import date
    from decimal import Decimal

    owner = booking.property.owner
    owner_email = (getattr(owner, "email", None) or "").strip()

    if not owner_email:
        logger.warning(
            "No se envió el aviso de cambio de reserva: "
            "el propietario no tiene email.",
        )
        return False

    status_content = {
        "accepted": {
            "subject": "Propuesta de cambio aceptada",
            "heading": "Propuesta aceptada",
            "description": (
                "El huésped ha aceptado la propuesta de cambio. "
                "Las nuevas condiciones se han aplicado a la reserva."
            ),
            "color": "#23734d",
            "background": "#edf6f1",
            "label": "ACEPTADA",
        },
        "rejected": {
            "subject": "Propuesta de cambio rechazada",
            "heading": "Propuesta rechazada",
            "description": (
                "El huésped ha rechazado la propuesta de cambio. "
                "La reserva conserva sus condiciones anteriores."
            ),
            "color": "#a33b35",
            "background": "#fbeeed",
            "label": "RECHAZADA",
        },
        "expired": {
            "subject": "Propuesta de cambio caducada",
            "heading": "Propuesta caducada",
            "description": (
                "El plazo para responder a la propuesta ha terminado "
                "sin que se haya registrado una respuesta."
            ),
            "color": "#8a641c",
            "background": "#fff8e8",
            "label": "CADUCADA",
        },
    }

    content = status_content.get(status)

    if content is None:
        logger.warning(
            "Estado desconocido para la notificación de cambio: %s",
            status,
        )
        return False

    property_title = booking.property.title
    guest_name = (
        getattr(booking, "guest_first_name", None) or "Huésped"
    )

    # Obtener la fotografía de las condiciones originales.
    original = proposal.original_booking_snapshot or {}

    def format_date(value):
        if not value:
            return "No disponible"

        if isinstance(value, str):
            try:
                value = date.fromisoformat(value)
            except ValueError:
                return value

        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")

        return str(value)

    def format_price(value):
        if value is None or value == "":
            return "No disponible"

        try:
            amount = Decimal(str(value))
            formatted = f"{amount:,.2f}"
            # Formato español: 1.234,56
            formatted = (
                formatted.replace(",", "_")
                .replace(".", ",")
                .replace("_", ".")
            )
            return f"{formatted} €"
        except (ValueError, TypeError, ArithmeticError):
            return f"{value} €"

    def format_guest_count(value):
        if value is None or value == "":
            return "No disponible"
        return str(value)

    original_initial_date = format_date(
        original.get("initial_date", booking.initial_date)
    )
    original_final_date = format_date(
        original.get("final_date", booking.final_date)
    )
    original_guest_count = format_guest_count(
        original.get("guest_count", booking.guest_count)
    )
    original_total_price = format_price(
        original.get("total_price", booking.total_price)
    )

    proposed_initial_date = format_date(proposal.proposed_initial_date)
    proposed_final_date = format_date(proposal.proposed_final_date)
    proposed_guest_count = format_guest_count(
        proposal.proposed_guest_count
    )
    proposed_total_price = format_price(proposal.proposed_total_price)

    safe_property = escape(str(property_title))
    safe_guest = escape(str(guest_name))
    safe_heading = escape(content["heading"])
    safe_description = escape(content["description"])
    safe_label = escape(content["label"])
    safe_color = content["color"]
    safe_background = content["background"]

    original_rows = [
        ("Fecha de entrada", original_initial_date),
        ("Fecha de salida", original_final_date),
        ("Número de huéspedes", original_guest_count),
        ("Precio total", original_total_price),
    ]

    proposed_rows = [
        ("Fecha de entrada", proposed_initial_date),
        ("Fecha de salida", proposed_final_date),
        ("Número de huéspedes", proposed_guest_count),
        ("Precio total", proposed_total_price),
    ]

    def build_text_details(rows):
        return "\n".join(f"{label}: {value}" for label, value in rows)

    def build_html_rows(rows):
        return "".join(
            f"""
            <tr>
              <td style="padding:12px 16px;color:#64736d;font-size:14px;
                         border-bottom:1px solid #e8eeeb;">
                {escape(label)}
              </td>
              <td align="right"
                  style="padding:12px 16px;color:#263a33;font-size:14px;
                         font-weight:600;border-bottom:1px solid #e8eeeb;">
                {escape(str(value))}
              </td>
            </tr>
            """
            for label, value in rows
        )

    subject = f'{content["subject"]} | {property_title}'

    text_message = f"""Hola {guest_name},

{content["description"]}

ALOJAMIENTO
{property_title}

RESERVA ANTERIOR
{build_text_details(original_rows)}

PROPUESTA DE CAMBIO
{build_text_details(proposed_rows)}

ESTADO: {content["label"]}

Este es un aviso automático relacionado con la gestión de tu alojamiento.
"""

    html_message = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{safe_heading}</title>
</head>
<body style="margin:0;padding:0;background:#f2f5f3;
             font-family:Arial,Helvetica,sans-serif;color:#263a33;">

  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
    {safe_heading} — {safe_property}
  </div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
         style="background:#f2f5f3;padding:32px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0"
               style="width:100%;max-width:600px;background:#ffffff;
                      border-radius:14px;overflow:hidden;">

          <tr>
            <td style="background:#173f35;padding:30px 32px;">
              <p style="margin:0;color:#d5e8df;font-size:11px;
                        letter-spacing:2px;text-transform:uppercase;">
                Gestión de reservas
              </p>
              <h1 style="margin:12px 0 0;color:#ffffff;font-size:25px;
                         line-height:1.35;">
                {safe_heading}
              </h1>
              <p style="margin:8px 0 0;color:#d5e8df;font-size:14px;">
                {safe_property}
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:28px 32px 18px;">
              <p style="margin:0 0 12px;font-size:16px;">
                Hola {safe_guest},
              </p>
              <p style="margin:0;color:#52615d;font-size:14px;line-height:1.8;">
                {safe_description}
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 26px;">
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="background:{safe_background};border-radius:9px;">
                <tr>
                  <td style="padding:17px 20px;">
                    <span style="display:inline-block;color:{safe_color};
                                 font-size:11px;font-weight:bold;
                                 letter-spacing:1.5px;">
                      ESTADO DE LA PROPUESTA
                    </span>
                    <p style="margin:7px 0 0;color:{safe_color};
                              font-size:20px;font-weight:bold;">
                      {safe_label}
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 26px;">
              <h2 style="margin:0 0 12px;font-size:18px;color:#263a33;">
                Reserva anterior
              </h2>
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="border:1px solid #e3e9e6;border-radius:9px;">
                {build_html_rows(original_rows)}
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 30px;">
              <h2 style="margin:0 0 12px;font-size:18px;color:#263a33;">
                Propuesta de cambio
              </h2>
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="border:1px solid #cfe1d8;border-radius:9px;">
                {build_html_rows(proposed_rows)}
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:22px 32px;background:#f7f9f8;
                       border-top:1px solid #e8eeeb;">
              <p style="margin:0;color:#65716c;font-size:12px;line-height:1.8;">
                Este mensaje es una notificación automática de la gestión
                de reservas de <strong>{safe_property}</strong>.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[owner_email],
        )
        email.attach_alternative(html_message, "text/html")

        sent_count = email.send(fail_silently=False)

        if sent_count != 1:
            logger.error(
                "No se confirmó el envío del aviso de cambio de reserva."
            )
            return False

        return True

    except Exception:
        logger.exception(
            "Error enviando el aviso de cambio de reserva."
        )
        return False

def send_forced_booking_change_email(booking, before_values, after_values):
    """
    Notifica al huésped que un administrador ha modificado su reserva.
    Devuelve True si el envío se confirma y False si falla.
    """
    from datetime import date
    from decimal import Decimal

    recipient_email = (booking.guest_email or "").strip()

    if not recipient_email:
        logger.warning(
            "No se envió el aviso de cambio forzado: "
            "la reserva %s no tiene email de huésped.",
            booking.pk,
        )
        return False

    property_title = booking.property.title
    guest_name = booking.guest_first_name or "huésped"
    reason = after_values.get("reason", "")

    def format_date(value):
        if not value:
            return "No disponible"
        try:
            if isinstance(value, str):
                value = date.fromisoformat(value)
            return value.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return str(value)

    def format_price(value):
        try:
            amount = Decimal(str(value))
            formatted = f"{amount:,.2f}"
            formatted = (
                formatted.replace(",", "_")
                .replace(".", ",")
                .replace("_", ".")
            )
            return f"{formatted} €"
        except (ValueError, TypeError, ArithmeticError):
            return "No disponible"

    old_initial = format_date(before_values.get("initial_date"))
    old_final = format_date(before_values.get("final_date"))
    old_guests = before_values.get("guest_count", "No disponible")
    old_total = format_price(before_values.get("total_price"))

    new_initial = format_date(after_values.get("initial_date"))
    new_final = format_date(after_values.get("final_date"))
    new_guests = after_values.get("guest_count", "No disponible")
    new_total = format_price(after_values.get("total_price"))

    safe_guest = escape(str(guest_name))
    safe_property = escape(str(property_title))
    safe_reason = escape(str(reason))

    subject = f"Cambio en tu reserva | {property_title}"

    text_message = f"""Hola {guest_name},

Te informamos de que el administrador ha realizado un cambio en tu reserva de {property_title}.

RESERVA ANTERIOR
Entrada: {old_initial}
Salida: {old_final}
Huéspedes: {old_guests}
Importe total: {old_total}

NUEVAS CONDICIONES
Entrada: {new_initial}
Salida: {new_final}
Huéspedes: {new_guests}
Importe total: {new_total}

Motivo del cambio:
{reason}

Si tienes dudas, contacta con el alojamiento.

Notificación automática de {property_title}.
"""

    
    html_message = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light">
  <title>Actualización de tu reserva</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f4f2;
             font-family:Arial,Helvetica,sans-serif;color:#263a33;">

  <div style="display:none;font-size:1px;color:#f1f4f2;max-height:0;
              max-width:0;opacity:0;overflow:hidden;">
    Tu reserva en {safe_property} ha sido actualizada.
  </div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
         border="0" style="background:#f1f4f2;width:100%;">
    <tr>
      <td align="center" style="padding:32px 12px;">

        <table role="presentation" width="600" cellspacing="0" cellpadding="0"
               border="0"
               style="width:100%;max-width:600px;background:#ffffff;
                      border-radius:12px;overflow:hidden;">

          <!-- Cabecera -->
          <tr>
            <td style="background:#173f35;padding:30px 32px 28px;">
              <p style="margin:0;color:#c9ded4;font-size:11px;
                        font-weight:bold;letter-spacing:2px;">
                NOTIFICACIÓN DE RESERVA
              </p>
              <h1 style="margin:14px 0 10px;color:#ffffff;font-size:26px;
                         line-height:1.3;font-weight:700;">
                Tu reserva ha sido actualizada
              </h1>
              <p style="margin:0;color:#e0ece6;font-size:14px;line-height:1.7;">
                Hola {safe_guest}, te informamos de un cambio en tu reserva.
              </p>
            </td>
          </tr>

          <!-- Estado -->
          <tr>
            <td style="padding:26px 32px 8px;">
              <table role="presentation" cellspacing="0" cellpadding="0"
                     border="0">
                <tr>
                  <td style="background:#eaf5ee;border:1px solid #cce5d4;
                             border-radius:20px;padding:9px 14px;">
                    <span style="color:#21663e;font-size:12px;
                                 font-weight:bold;">
                      &#10003;&nbsp; CAMBIO CONFIRMADO
                    </span>
                  </td>
                </tr>
              </table>
              <p style="margin:16px 0 0;color:#52615d;font-size:14px;
                        line-height:1.8;">
                El administrador ha actualizado las condiciones de tu reserva
                en <strong style="color:#263a33;">{safe_property}</strong>.
                A continuación encontrarás el resumen.
              </p>
            </td>
          </tr>

          <!-- Comparación de condiciones -->
          <tr>
            <td style="padding:22px 32px 8px;">
              <h2 style="margin:0 0 14px;color:#263a33;font-size:18px;">
                Resumen de la reserva
              </h2>

              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0" border="0"
                     style="border:1px solid #e1e8e4;border-radius:9px;">

                <tr>
                  <td colspan="2"
                      style="padding:15px 18px;background:#f7f9f8;
                             border-bottom:1px solid #e1e8e4;">
                    <p style="margin:0;color:#68766f;font-size:11px;
                              font-weight:bold;letter-spacing:1px;">
                      CONDICIONES ANTERIORES
                    </p>
                  </td>
                </tr>

                <tr>
                  <td style="padding:13px 18px;color:#68766f;font-size:13px;">
                    Fecha de entrada
                  </td>
                  <td align="right"
                      style="padding:13px 18px;color:#263a33;font-size:13px;">
                    {old_initial}
                  </td>
                </tr>
                <tr>
                  <td style="padding:13px 18px;color:#68766f;font-size:13px;">
                    Fecha de salida
                  </td>
                  <td align="right"
                      style="padding:13px 18px;color:#263a33;font-size:13px;">
                    {old_final}
                  </td>
                </tr>
                <tr>
                  <td style="padding:13px 18px;color:#68766f;font-size:13px;">
                    Número de huéspedes
                  </td>
                  <td align="right"
                      style="padding:13px 18px;color:#263a33;font-size:13px;">
                    {old_guests}
                  </td>
                </tr>
                <tr>
                  <td style="padding:13px 18px;color:#68766f;font-size:13px;
                             border-bottom:1px solid #e1e8e4;">
                    Importe total
                  </td>
                  <td align="right"
                      style="padding:13px 18px;color:#263a33;font-size:13px;
                             border-bottom:1px solid #e1e8e4;">
                    {old_total}
                  </td>
                </tr>

                <tr>
                  <td colspan="2"
                      style="padding:15px 18px;background:#edf6f0;
                             border-bottom:1px solid #d7e9dd;">
                    <p style="margin:0;color:#21663e;font-size:11px;
                              font-weight:bold;letter-spacing:1px;">
                      NUEVAS CONDICIONES
                    </p>
                  </td>
                </tr>

                <tr>
                  <td style="padding:14px 18px;color:#52615d;font-size:13px;">
                    Fecha de entrada
                  </td>
                  <td align="right"
                      style="padding:14px 18px;color:#173f35;font-size:13px;
                             font-weight:bold;">
                    {new_initial}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 18px;color:#52615d;font-size:13px;">
                    Fecha de salida
                  </td>
                  <td align="right"
                      style="padding:14px 18px;color:#173f35;font-size:13px;
                             font-weight:bold;">
                    {new_final}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 18px;color:#52615d;font-size:13px;">
                    Número de huéspedes
                  </td>
                  <td align="right"
                      style="padding:14px 18px;color:#173f35;font-size:13px;
                             font-weight:bold;">
                    {new_guests}
                  </td>
                </tr>
                <tr>
                  <td style="padding:15px 18px;background:#edf6f0;
                             border-top:1px solid #d7e9dd;
                             color:#173f35;font-size:13px;font-weight:bold;">
                    Importe total actualizado
                  </td>
                  <td align="right"
                      style="padding:15px 18px;background:#edf6f0;
                             border-top:1px solid #d7e9dd;
                             color:#173f35;font-size:16px;font-weight:bold;">
                    {new_total}
                  </td>
                </tr>

              </table>
            </td>
          </tr>

          <!-- Motivo -->
          <tr>
            <td style="padding:22px 32px 28px;">
              <h2 style="margin:0 0 12px;color:#263a33;font-size:18px;">
                Motivo del cambio
              </h2>
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0" border="0"
                     style="background:#f7f9f8;border-left:4px solid #527d69;">
                <tr>
                  <td style="padding:17px 18px;color:#52615d;font-size:14px;
                             line-height:1.8;white-space:pre-line;">
                    {safe_reason}
                  </td>
                </tr>
              </table>
              <p style="margin:20px 0 0;color:#52615d;font-size:13px;
                        line-height:1.8;">
                Si tienes alguna duda sobre este cambio, contacta con el
                alojamiento.
              </p>
            </td>
          </tr>

          <!-- Pie -->
          <tr>
            <td style="padding:22px 32px;background:#f7f9f8;
                       border-top:1px solid #e6ebe8;">
              <p style="margin:0;color:#68766f;font-size:12px;line-height:1.8;">
                Este es un mensaje automático relacionado con tu reserva en
                <strong>{safe_property}</strong>.
              </p>
              <p style="margin:10px 0 0;color:#89938e;font-size:11px;">
                Gracias por confiar en nosotros.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
        )
        email.attach_alternative(html_message, "text/html")

        if email.send(fail_silently=False) != 1:
            logger.error(
                "No se confirmó el correo de cambio forzado de la reserva %s.",
                booking.pk,
            )
            return False

        return True

    except Exception:
        logger.exception(
            "Error al notificar el cambio forzado de la reserva %s.",
            booking.pk,
        )
        return False