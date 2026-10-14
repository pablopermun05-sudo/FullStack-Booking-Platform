
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
            "view_booking_change_proposal_by_token",
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
Precio total: {original_total:.2f} €

NUEVA PROPUESTA
Entrada: {proposal.proposed_initial_date:%d/%m/%Y}
Salida: {proposal.proposed_final_date:%d/%m/%Y}
Huéspedes: {proposal.proposed_guest_count}
Precio total propuesto: {proposed_total:.2f} €

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
        recipient_email = (
            booking.tenant.email.strip()
            if booking.tenant_id and booking.tenant.email
            else (booking.guest_email or "").strip()
        )

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
