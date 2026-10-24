
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.db import transaction
from django.template.defaultfilters import escape
from django.urls import reverse
from django.utils import timezone
from .models import BookingAttachment
from urllib.parse import urlencode
from django.core import signing
from datetime import date
from decimal import Decimal

logger = logging.getLogger(__name__)

def send_booking_change_proposal_email(request, booking, proposal, raw_token):
    """
    Envía al huésped una propuesta de cambio con formato HTML y texto.
    Incluye el motivo y los adjuntos, si existen.
    Devuelve True si el envío se confirma y False si falla.
    """
    try:
        recipient_email = (booking.guest_email or "").strip()

        if not recipient_email:
            logger.error(
                "La reserva %s no tiene un email de huésped.",
                booking.pk,
            )
            return False

        proposal_url = request.build_absolute_uri(
            reverse(
                "booking_change_proposal_detail",
                kwargs={"token": raw_token},
            )
        )

        reason = (proposal.reason or "").strip()
        property_title = booking.property.title
        guest_name = booking.guest_first_name or "huésped"
        owner_phone = booking.property.owner.phone_number

        original_total = booking.total_price
        proposed_total = proposal.proposed_total_price
        expiry = timezone.localtime(proposal.expires_at)

        # Obtener los archivos adjuntos de esta propuesta.
        proposal_attachments = BookingAttachment.objects.filter(
            change_proposal=proposal
        )

        attachment_items = []

        for attachment in proposal_attachments:
            download_path = reverse(
                "download_booking_proposal_attachment",
                kwargs={"attachment_id": attachment.pk},
            )
            download_path += "?" + urlencode({"token": raw_token})

            attachment_items.append({
                "name": (
                    attachment.original_filename
                    or attachment.file.name.split("/")[-1]
                ),
                "url": request.build_absolute_uri(download_path),
            })

        subject = f"Propuesta de cambio de reserva | {property_title}"

        # Texto plano.
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

MOTIVO DEL CAMBIO
{reason or 'No se ha indicado un motivo.'}

La propuesta caduca el {expiry:%d/%m/%Y a las %H:%M}.

Revisa la propuesta aquí:
{proposal_url}
"""

        if attachment_items:
            text_message += "\nARCHIVOS ADJUNTOS\n"
            for item in attachment_items:
                text_message += f"- {item['name']}\n  {item['url']}\n"

        if owner_phone:
            text_message += (
                f"\nSi tienes dudas, contacta con el alojamiento "
                f"en el teléfono {owner_phone}.\n"
            )

        text_message += (
            f"\nNotificación automática de {property_title}.\n"
        )

        # Escapar los valores dinámicos que se insertan en el HTML.
        safe_guest = escape(str(guest_name))
        safe_property = escape(str(property_title))
        safe_url = escape(proposal_url)
        safe_reason = escape(reason or "No se ha indicado un motivo.")
        safe_owner_phone = escape(str(owner_phone)) if owner_phone else ""

        reason_html = f"""
        <tr>
          <td style="padding:12px 32px 22px;">
            <h2 style="margin:0 0 12px;color:#263a33;font-size:18px;">
              Motivo del cambio
            </h2>
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0"
                   style="background:#f7f9f8;border-left:4px solid #527d69;">
              <tr>
                <td style="padding:16px;color:#52615d;font-size:14px;
                           line-height:1.8;white-space:pre-line;">
                  {safe_reason}
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """

        attachments_html = ""

        if attachment_items:
            attachment_cards = ""

            for item in attachment_items:
                filename = escape(item["name"])
                file_url = escape(item["url"])

                attachment_cards += f"""
                <tr>
                  <td style="padding:0 0 10px;">
                    <table role="presentation" width="100%" cellspacing="0"
                          cellpadding="0" border="0"
                          style="border:1px solid #e1e8e4;border-radius:9px;
                                  background:#ffffff;">
                      <tr>
                        <td width="54" valign="middle"
                            style="padding:14px 0 14px 14px;">
                          <table role="presentation" width="42" height="46"
                                cellspacing="0" cellpadding="0" border="0"
                                style="background:#edf6f1;border-radius:6px;">
                            <tr>
                              <td style="background-color:#e8f5e9;
                                        color:#2e7d32;
                                        width:48px;
                                        height:48px;
                                        text-align:center;
                                        vertical-align:middle;
                                        border-radius:8px;
                                        font-size:26px;">
                                  📄
                              </td>
                            </tr>
                          </table>
                        </td>
                        <td valign="middle"
                            style="padding:12px 10px 12px 12px;
                                  font-family:Arial,Helvetica,sans-serif;">
                          <p style="margin:0;color:#263a33;font-size:13px;
                                    font-weight:bold;line-height:1.5;
                                    word-break:break-word;">
                            {filename}
                          </p>
                          <p style="margin:4px 0 0;color:#7b8781;font-size:11px;">
                            Archivo adjunto a la propuesta
                          </p>
                        </td>
                        <td align="right" valign="middle"
                            style="padding:12px 14px 12px 4px;">
                          <a href="{file_url}"
                            style="display:inline-block;background:#173f35;
                                    color:#ffffff;text-decoration:none;
                                    padding:10px 12px;border-radius:5px;
                                    font-size:12px;font-weight:bold;
                                    white-space:nowrap;">
                            Descargar
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                """

            attachments_html = f"""
            <tr>
              <td style="padding:0 32px 24px;">
                <h2 style="margin:0 0 6px;color:#263a33;font-size:18px;">
                  Documentación adjunta
                </h2>
                <p style="margin:0 0 14px;color:#718078;font-size:13px;
                          line-height:1.6;">
                  Consulta o descarga los archivos incluidos en esta propuesta.
                </p>
                <table role="presentation" width="100%" cellspacing="0"
                      cellpadding="0" border="0">
                  {attachment_cards}
                </table>
              </td>
            </tr>
          """

        safe_expiry = expiry.strftime("%d/%m/%Y a las %H:%M")

        html_message = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Propuesta de cambio de reserva</title>
</head>
<body style="margin:0;padding:0;background:#f3f5f7;
             font-family:Arial,Helvetica,sans-serif;color:#263238;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
         style="background:#f3f5f7;padding:32px 12px;">
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
            <td style="padding:30px 32px 18px;">
              <p style="margin:0 0 12px;font-size:16px;">
                Hola {safe_guest},
              </p>
              <p style="margin:0;color:#52615d;font-size:15px;line-height:1.7;">
                <strong>{safe_property}</strong> te ha enviado una propuesta
                para modificar las condiciones de tu reserva.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 20px;">
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="border:1px solid #e3e9e6;border-radius:8px;">
                <tr>
                  <td colspan="2" style="padding:16px;background:#f7f9f8;
                                         font-weight:bold;">
                    Reserva actual
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#66736f;">Entrada</td>
                  <td align="right" style="padding:10px 16px;">
                    {booking.initial_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#66736f;">Salida</td>
                  <td align="right" style="padding:10px 16px;">
                    {booking.final_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#66736f;">Huéspedes</td>
                  <td align="right" style="padding:10px 16px;">
                    {booking.guest_count}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 16px;border-top:1px solid #e3e9e6;
                             font-weight:bold;">
                    Precio total actual
                  </td>
                  <td align="right" style="padding:14px 16px;
                                           border-top:1px solid #e3e9e6;
                                           font-weight:bold;">
                    {original_total:.2f} €
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 22px;">
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="border:1px solid #cfe3d8;border-radius:8px;">
                <tr>
                  <td colspan="2" style="padding:16px;background:#edf6f1;
                                         color:#173f35;font-weight:bold;">
                    Nueva propuesta
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#52615d;">Entrada</td>
                  <td align="right" style="padding:10px 16px;">
                    {proposal.proposed_initial_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#52615d;">Salida</td>
                  <td align="right" style="padding:10px 16px;">
                    {proposal.proposed_final_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#52615d;">Huéspedes</td>
                  <td align="right" style="padding:10px 16px;">
                    {proposal.proposed_guest_count}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 16px;border-top:1px solid #cfe3d8;
                             font-weight:bold;color:#173f35;">
                    Precio total propuesto
                  </td>
                  <td align="right" style="padding:14px 16px;
                                           border-top:1px solid #cfe3d8;
                                           font-weight:bold;color:#173f35;">
                    {proposed_total:.2f} €
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          {reason_html}

          {attachments_html}

          <tr>
            <td style="padding:0 32px 24px;">
              <div style="background:#fff8e8;border-radius:8px;padding:15px 17px;
                          color:#775b20;font-size:13px;line-height:1.6;">
                <strong>Plazo para responder</strong><br>
                Esta propuesta caduca el <strong>{safe_expiry}</strong>.
              </div>
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
                Notificación automática de {safe_property}.
                Si tienes dudas, contacta con el alojamiento
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

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
        )
        email.attach_alternative(html_message, "text/html")

        if email.send(fail_silently=False) != 1:
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

def send_booking_cancellation_request_email(request, booking, cancellation, raw_token):
    """
    Envía al huésped una solicitud de cancelación con formato HTML y texto.
    Incluye el motivo y los archivos adjuntos, si existen.
    Devuelve True si el envío se confirma y False si falla.
    """
    try:
        recipient_email = (booking.guest_email or "").strip()

        if not recipient_email:
            logger.error(
                "La reserva %s no tiene un email de huésped.",
                booking.pk,
            )
            return False

        response_url = request.build_absolute_uri(
            reverse(
                "booking_cancellation_request_detail",
                kwargs={"token": raw_token},
            )
        )

        reason = (cancellation.reason or "").strip()
        property_title = booking.property.title
        guest_name = booking.guest_first_name or "huésped"
        owner_phone = booking.property.owner.phone_number
        total_price = booking.total_price

        expiry = (
            timezone.localtime(cancellation.expires_at)
            if cancellation.expires_at
            else None
        )
        expiry_text = (
            expiry.strftime("%d/%m/%Y a las %H:%M")
            if expiry
            else "No indicada"
        )

        # Obtener los archivos adjuntos de esta solicitud.
        cancellation_attachments = BookingAttachment.objects.filter(
            cancellation_request=cancellation
        )

        attachment_items = []

        for attachment in cancellation_attachments:
            download_path = reverse(
                "download_booking_cancellation_attachment",
                kwargs={"attachment_id": attachment.pk},
            )
            download_path += "?" + urlencode({"token": raw_token})

            attachment_items.append({
                "name": (
                    attachment.original_filename
                    or attachment.file.name.split("/")[-1]
                ),
                "url": request.build_absolute_uri(download_path),
            })

        subject = (
            f"Solicitud de cancelación de reserva | {property_title}"
        )

        # ---------------------------------------------------------
        # TEXTO PLANO
        # ---------------------------------------------------------
        text_message = f"""Hola {guest_name},

El alojamiento {property_title} ha solicitado cancelar tu reserva.

RESERVA ACTUAL
Entrada: {booking.initial_date:%d/%m/%Y}
Salida: {booking.final_date:%d/%m/%Y}
Huéspedes: {booking.guest_count}
Importe total: {total_price:.2f} €

MOTIVO DE LA CANCELACIÓN
{reason or 'No se ha indicado un motivo.'}

FECHA LÍMITE PARA RESPONDER
{expiry_text}

Importante: tu reserva sigue activa. Recibir esta solicitud no cancela
automáticamente tu reserva.

Puedes revisar la solicitud y aceptarla o rechazarla desde este enlace,
sin necesidad de iniciar sesión:
{response_url}
"""

        if attachment_items:
            text_message += "\nARCHIVOS ADJUNTOS\n"
            for item in attachment_items:
                text_message += (
                    f"- {item['name']}\n"
                    f"  Descargar: {item['url']}\n"
                )

        if owner_phone:
            text_message += (
                f"\nSi tienes dudas, contacta con el alojamiento "
                f"en el teléfono {owner_phone}.\n"
            )

        text_message += (
            f"\nNotificación automática de {property_title}.\n"
        )

        # ---------------------------------------------------------
        # VALORES HTML SEGUROS
        # ---------------------------------------------------------
        safe_guest = escape(str(guest_name))
        safe_property = escape(str(property_title))
        safe_url = escape(response_url)
        safe_reason = escape(
            reason or "No se ha indicado un motivo."
        )
        safe_expiry = escape(expiry_text)
        safe_owner_phone = (
            escape(str(owner_phone)) if owner_phone else ""
        )

        # ---------------------------------------------------------
        # BLOQUE HTML DEL MOTIVO
        # ---------------------------------------------------------
        reason_html = f"""
        <tr>
          <td style="padding:0 32px 22px;">
            <h2 style="margin:0 0 12px;color:#263a33;font-size:18px;">
              Motivo de la cancelación
            </h2>
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0" border="0"
                   style="background:#f7f9f8;
                          border-left:4px solid #527d69;">
              <tr>
                <td style="padding:16px;color:#52615d;font-size:14px;
                           line-height:1.8;white-space:pre-line;">
                  {safe_reason}
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """

        # ---------------------------------------------------------
        # BLOQUE HTML DE LOS ARCHIVOS ADJUNTOS
        # ---------------------------------------------------------
        attachments_html = ""

        if attachment_items:
            attachment_cards = ""

            for item in attachment_items:
                filename = escape(str(item["name"]))
                file_url = escape(item["url"])

                attachment_cards += f"""
                <tr>
                  <td style="padding:0 0 10px;">
                    <table role="presentation" width="100%"
                           cellspacing="0" cellpadding="0" border="0"
                           style="border:1px solid #e1e8e4;
                                  border-radius:9px;background:#ffffff;">
                      <tr>
                        <td width="54" valign="middle"
                            style="padding:14px 0 14px 14px;">
                          <table role="presentation" width="42" height="46"
                                 cellspacing="0" cellpadding="0" border="0"
                                 style="background:#edf6f1;border-radius:6px;">
                            <tr>
                              <td style="color:#2e7d32;text-align:center;
                                         vertical-align:middle;
                                         font-size:25px;">
                                &#128196;
                              </td>
                            </tr>
                          </table>
                        </td>
                        <td valign="middle"
                            style="padding:12px 10px 12px 12px;
                                   font-family:Arial,Helvetica,sans-serif;">
                          <p style="margin:0;color:#263a33;font-size:13px;
                                    font-weight:bold;line-height:1.5;
                                    word-break:break-word;">
                            {filename}
                          </p>
                          <p style="margin:4px 0 0;color:#7b8781;
                                    font-size:11px;">
                            Archivo adjunto a la solicitud
                          </p>
                        </td>
                        <td align="right" valign="middle"
                            style="padding:12px 14px 12px 4px;">
                          <a href="{file_url}"
                             style="display:inline-block;background:#173f35;
                                    color:#ffffff;text-decoration:none;
                                    padding:10px 12px;border-radius:5px;
                                    font-size:12px;font-weight:bold;
                                    white-space:nowrap;">
                            Descargar
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                """

            attachments_html = f"""
            <tr>
              <td style="padding:0 32px 24px;">
                <h2 style="margin:0 0 6px;color:#263a33;font-size:18px;">
                  Documentación adjunta
                </h2>
                <p style="margin:0 0 14px;color:#718078;font-size:13px;
                          line-height:1.6;">
                  Consulta o descarga los archivos incluidos en esta
                  solicitud de cancelación.
                </p>
                <table role="presentation" width="100%" cellspacing="0"
                       cellpadding="0" border="0">
                  {attachment_cards}
                </table>
              </td>
            </tr>
            """

        # ---------------------------------------------------------
        # HTML DEL CORREO
        # ---------------------------------------------------------
        html_message = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Solicitud de cancelación de reserva</title>
</head>
<body style="margin:0;padding:0;background:#f3f5f7;
             font-family:Arial,Helvetica,sans-serif;color:#263238;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
         border="0" style="background:#f3f5f7;padding:32px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellspacing="0"
               cellpadding="0" border="0"
               style="width:100%;max-width:600px;background:#ffffff;
                      border-radius:12px;overflow:hidden;">

          <tr>
            <td style="background:#173f35;padding:28px 32px;color:#ffffff;">
              <p style="margin:0;font-size:12px;letter-spacing:2px;
                        text-transform:uppercase;color:#d5e8df;">
                Notificación de reserva
              </p>
              <h1 style="margin:10px 0 0;font-size:25px;line-height:1.3;">
                Solicitud de cancelación
              </h1>
            </td>
          </tr>

          <tr>
            <td style="padding:30px 32px 20px;">
              <p style="margin:0 0 12px;font-size:16px;">
                Hola {safe_guest},
              </p>
              <p style="margin:0;color:#52615d;font-size:15px;
                        line-height:1.7;">
                El alojamiento <strong>{safe_property}</strong> ha solicitado
                cancelar tu reserva. Revisa los detalles y decide si aceptas
                o rechazas la solicitud.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 22px;">
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0" border="0"
                     style="border:1px solid #e3e9e6;border-radius:8px;">
                <tr>
                  <td colspan="2" style="padding:16px;background:#f7f9f8;
                                         font-weight:bold;">
                    Detalles de la reserva
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#66736f;">Entrada</td>
                  <td align="right" style="padding:10px 16px;">
                    {booking.initial_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#66736f;">Salida</td>
                  <td align="right" style="padding:10px 16px;">
                    {booking.final_date:%d/%m/%Y}
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#66736f;">Huéspedes</td>
                  <td align="right" style="padding:10px 16px;">
                    {booking.guest_count}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 16px;border-top:1px solid #e3e9e6;
                             font-weight:bold;">
                    Importe total
                  </td>
                  <td align="right"
                      style="padding:14px 16px;border-top:1px solid #e3e9e6;
                             font-weight:bold;">
                    {total_price:.2f} €
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          {reason_html}

          <tr>
            <td style="padding:0 32px 24px;">
              <div style="background:#fff8e8;border-radius:8px;
                          padding:15px 17px;color:#775b20;
                          font-size:13px;line-height:1.7;">
                <strong>Fecha límite para responder</strong><br>
                {safe_expiry}
              </div>
            </td>
          </tr>

          {attachments_html}

          <tr>
            <td style="padding:0 32px 24px;">
              <div style="background:#edf6f1;border-radius:8px;
                          padding:16px;color:#173f35;font-size:13px;
                          line-height:1.7;">
                <strong>Importante:</strong> tu reserva sigue activa.
                Recibir esta solicitud no la cancela automáticamente.
                Puedes aceptar o rechazar la solicitud desde el siguiente
                enlace, sin necesidad de iniciar sesión.
              </div>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 32px 30px;">
              <a href="{safe_url}"
                 style="display:inline-block;background:#173f35;
                        color:#ffffff;text-decoration:none;padding:15px 28px;
                        border-radius:6px;font-size:15px;font-weight:bold;">
                Revisar solicitud
              </a>
            </td>
          </tr>

          <tr>
            <td style="padding:22px 32px;background:#f7f9f8;
                       border-top:1px solid #e8eeeb;">
              <p style="margin:0;color:#65716c;font-size:12px;
                        line-height:1.7;">
                Notificación automática de {safe_property}.
                Si tienes dudas, contacta con el alojamiento
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

        # ---------------------------------------------------------
        # ENVÍO
        # ---------------------------------------------------------
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
        )
        email.attach_alternative(html_message, "text/html")

        if email.send(fail_silently=False) != 1:
            logger.error(
                "No se confirmó el envío de la solicitud de cancelación "
                "%s a %s.",
                cancellation.pk,
                recipient_email,
            )
            return False

        logger.info(
            "Correo de cancelación enviado. Solicitud=%s, destinatario=%s",
            cancellation.pk,
            recipient_email,
        )
        return True

    except Exception:
        logger.exception(
            "Error al enviar el correo de la solicitud de cancelación "
            "%s para la reserva %s.",
            cancellation.pk,
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

def send_booking_cancellation_proposal_status_email(booking, proposal, status):
    """
    Envía al propietario un correo HTML y de texto plano cuando una
    propuesta de cancelación se acepta, rechaza o caduca.

    Devuelve True si Django confirma el envío y False si falla.
    """
    from datetime import date
    from decimal import Decimal

    try:
        owner = booking.property.owner
        owner_email = (getattr(owner, "email", None) or "").strip()

        if not owner_email:
            logger.warning(
                "No se envió el aviso de cancelación: "
                "el propietario no tiene email."
            )
            return False

        status_content = {
            "accepted": {
                "subject": "Propuesta de cancelación aceptada",
                "heading": "Cancelación aceptada",
                "description": (
                    "La propuesta de cancelación ha sido aceptada. "
                    "La reserva ha quedado cancelada."
                ),
                "color": "#23734d",
                "background": "#edf6f1",
                "label": "ACEPTADA",
            },
            "rejected": {
                "subject": "Propuesta de cancelación rechazada",
                "heading": "Cancelación rechazada",
                "description": (
                    "La propuesta de cancelación ha sido rechazada. "
                    "La reserva conserva sus condiciones actuales."
                ),
                "color": "#a33b35",
                "background": "#fbeeed",
                "label": "RECHAZADA",
            },
            "expired": {
                "subject": "Propuesta de cancelación caducada",
                "heading": "Cancelación caducada",
                "description": (
                    "El plazo para responder a la propuesta de cancelación "
                    "ha terminado sin que se haya registrado una respuesta."
                ),
                "color": "#8a641c",
                "background": "#fff8e8",
                "label": "CADUCADA",
            },
            "cancelled": {
              "subject": "Solicitud de cancelación cerrada",
              "heading": "Solicitud de cancelación cerrada",
              "description": (
                  "La solicitud de cancelación se ha cerrado porque "
                  "la reserva ya no admite esta solicitud."
              ),
              "color": "#64748b",
              "background": "#f1f5f9",
              "label": "CERRADA",
          },
        }

        content = status_content.get(status)

        if content is None:
            logger.warning(
                "Estado desconocido para la notificación de cancelación: %s",
                status,
            )
            return False

        property_title = booking.property.title
        guest_name = (
            getattr(booking, "guest_first_name", None) or "Huésped"
        )

        # Recuperar las condiciones originales de la reserva, si existen.
        original = (
            getattr(proposal, "original_booking_snapshot", None) or {}
        )

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

        initial_date = format_date(
            original.get("initial_date") or booking.initial_date
        )
        final_date = format_date(
            original.get("final_date") or booking.final_date
        )
        guest_count = format_guest_count(
            original.get("guest_count") or booking.guest_count
        )
        total_price = format_price(
            original.get("total_price")
            if original.get("total_price") is not None
            else booking.total_price
        )

        # Motivo original de la solicitud, no de la respuesta.
        reason = (
            getattr(proposal, "reason", None)
            or ""
        )
        reason = str(reason).strip() or "No se ha indicado un motivo."

        safe_property = escape(str(property_title))
        safe_guest = escape(str(guest_name))
        safe_heading = escape(content["heading"])
        safe_description = escape(content["description"])
        safe_label = escape(content["label"])
        safe_reason = escape(reason)

        safe_color = content["color"]
        safe_background = content["background"]

        reservation_rows = [
            ("Fecha de entrada", initial_date),
            ("Fecha de salida", final_date),
            ("Número de huéspedes", guest_count),
            ("Precio total", total_price),
        ]

        def build_text_details(rows):
            return "\n".join(
                f"{label}: {value}" for label, value in rows
            )

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

        text_message = f"""Hola,

{content["description"]}

ALOJAMIENTO
{property_title}

HUÉSPED
{guest_name}

DATOS DE LA RESERVA
{build_text_details(reservation_rows)}

MOTIVO DE LA CANCELACIÓN
{reason}

ESTADO DE LA PROPUESTA: {content["label"]}

Este es un aviso automático relacionado con la gestión de reservas.
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
                Hola,
              </p>
              <p style="margin:0;color:#52615d;font-size:14px;line-height:1.8;">
                {safe_description}
              </p>
              <p style="margin:18px 0 0;color:#52615d;font-size:14px;">
                <strong>Huésped:</strong> {safe_guest}
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
                Datos de la reserva
              </h2>
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="border:1px solid #e3e9e6;border-radius:9px;">
                {build_html_rows(reservation_rows)}
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 30px;">
              <h2 style="margin:0 0 12px;font-size:18px;color:#263a33;">
                Motivo de la cancelación
              </h2>
              <table role="presentation" width="100%" cellspacing="0"
                     cellpadding="0"
                     style="background:#f7f9f8;border:1px solid #e3e9e6;
                            border-radius:9px;">
                <tr>
                  <td style="padding:16px;color:#52615d;font-size:14px;
                             line-height:1.8;">
                    {safe_reason}
                  </td>
                </tr>
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
                "No se confirmó el envío del aviso de cancelación."
            )
            return False

        return True

    except Exception:
        logger.exception(
            "Error preparando o enviando el aviso de cancelación de reserva."
        )
        return False

def send_forced_booking_change_email(booking, before_values, after_values, audit=None, request=None):
    """Notifica al huésped un cambio forzado de reserva."""

    recipient_email = (booking.guest_email or "").strip()

    if not recipient_email:
        logger.error(
            "La reserva %s no tiene un email de huésped.",
            booking.pk,
        )
        return False

    property_title = booking.property.title
    guest_name = booking.guest_first_name or "huésped"
    reason = (after_values.get("reason") or "").strip()
    owner_phone = getattr(booking.property.owner, "phone_number", None)

    def format_date(value):
        if not value or value == "—":
            return "—"
        try:
            return date.fromisoformat(str(value)).strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            return str(value)

    def format_price(value):
        try:
            if value is None or value == "—":
                return "—"
            return f"{Decimal(str(value)):.2f} €"
        except (TypeError, ValueError, ArithmeticError):
            return str(value)

    def get_value(values, key):
        value = values.get(key, "—")
        return "—" if value is None or value == "" else value

    # Obtener los archivos adjuntos de este cambio forzado.
    forced_attachments = (
        BookingAttachment.objects.filter(change_audit=audit)
        if audit is not None
        else BookingAttachment.objects.none()
    )

    attachment_items = []

    for attachment in forced_attachments:
        if request is None:
            logger.warning(
                "No se puede crear el enlace de descarga del adjunto %s "
                "porque no se recibió request.",
                attachment.pk,
            )
            continue

        token = signing.dumps(
            {
                "attachment_id": attachment.pk,
                "audit_id": audit.pk,
            },
            salt="forced-booking-attachment",
        )

        download_path = reverse(
            "download_forced_booking_attachment",
            kwargs={
                "attachment_id": attachment.pk,
                "token": token,
            },
        )

        attachment_items.append({
            "name": (
                attachment.original_filename
                or attachment.file.name.split("/")[-1]
            ),
            "url": request.build_absolute_uri(download_path),
        })

    # Datos de la reserva anterior y de la reserva actual.
    reservation_fields = (
        ("Entrada", "initial_date", format_date),
        ("Salida", "final_date", format_date),
        ("Huéspedes", "guest_count", str),
        ("Precio total", "total_price", format_price),
    )

    # Texto plano.
    text_message = f"""Hola {guest_name},

El alojamiento {property_title} ha realizado un cambio en las condiciones de tu reserva.

RESERVA: {booking.pk}

RESERVA ANTERIOR
"""

    for label, field, formatter in reservation_fields:
        value = formatter(get_value(before_values, field))
        text_message += f"{label}: {value}\n"

    text_message += "\nRESERVA ACTUAL\n"

    for label, field, formatter in reservation_fields:
        value = formatter(get_value(after_values, field))
        text_message += f"{label}: {value}\n"

    if reason:
        text_message += f"\nMOTIVO DEL CAMBIO\n{reason}\n"

    if attachment_items:
        text_message += "\nDOCUMENTACIÓN ADJUNTA\n"
        for item in attachment_items:
            text_message += f"- {item['name']}\n  {item['url']}\n"

    if owner_phone:
        text_message += (
            f"\nSi tienes dudas, contacta con el alojamiento "
            f"en el teléfono {owner_phone}.\n"
        )

    text_message += (
        f"\nNotificación automática de {property_title}.\n"
    )

    # Escapar los valores dinámicos insertados en el HTML.
    safe_guest = escape(str(guest_name))
    safe_property = escape(str(property_title))
    safe_reason = escape(reason or "No se ha indicado un motivo.")
    safe_owner_phone = escape(str(owner_phone)) if owner_phone else ""

    # HTML del motivo.
    reason_html = ""

    if reason:
        reason_html = f"""
        <tr>
          <td style="padding:12px 32px 22px;">
            <h2 style="margin:0 0 12px;color:#263a33;font-size:18px;">
              Motivo del cambio
            </h2>
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0"
                   style="background:#f7f9f8;border-left:4px solid #527d69;">
              <tr>
                <td style="padding:16px;color:#52615d;font-size:14px;
                           line-height:1.8;white-space:pre-line;">
                  {safe_reason}
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """

    # Generar las tablas HTML de la reserva anterior y la actual.
    def build_reservation_table(title, values, highlighted=False):
        background = "#edf6f1" if highlighted else "#f7f9f8"
        border_color = "#cfe3d8" if highlighted else "#e3e9e6"
        title_color = "#173f35" if highlighted else "#263a33"

        rows_html = ""

        for label, field, formatter in reservation_fields:
            value = formatter(get_value(values, field))

            rows_html += f"""
            <tr>
              <td style="padding:10px 16px;color:#52615d;
                         border-bottom:1px solid {border_color};
                         font-size:14px;">
                {escape(label)}
              </td>
              <td align="right"
                  style="padding:10px 16px;color:{title_color};
                         border-bottom:1px solid {border_color};
                         font-size:14px;font-weight:bold;">
                {escape(str(value))}
              </td>
            </tr>
            """

        return f"""
        <tr>
          <td style="padding:0 32px 20px;">
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0"
                   style="border:1px solid {border_color};border-radius:8px;">
              <tr>
                <td colspan="2"
                    style="padding:16px;background:{background};
                           color:{title_color};font-weight:bold;">
                  {escape(title)}
                </td>
              </tr>
              {rows_html}
            </table>
          </td>
        </tr>
        """

    previous_reservation_html = build_reservation_table(
        "Reserva anterior",
        before_values,
    )

    current_reservation_html = build_reservation_table(
        "Reserva actual",
        after_values,
        highlighted=True,
    )

    # Tarjetas HTML de archivos adjuntos.
    attachments_html = ""

    if attachment_items:
        attachment_cards = ""

        for item in attachment_items:
            filename = escape(str(item["name"]))
            file_url = escape(str(item["url"]))

            attachment_cards += f"""
            <tr>
              <td style="padding:0 0 10px;">
                <table role="presentation" width="100%" cellspacing="0"
                       cellpadding="0" border="0"
                       style="border:1px solid #e1e8e4;border-radius:9px;
                              background:#ffffff;">
                  <tr>
                    <td width="54" valign="middle"
                        style="padding:14px 0 14px 14px;">
                      <table role="presentation" width="42" height="46"
                             cellspacing="0" cellpadding="0" border="0"
                             style="background:#edf6f1;border-radius:6px;">
                        <tr>
                          <td style="background-color:#e8f5e9;color:#2e7d32;
                                     width:48px;height:48px;text-align:center;
                                     vertical-align:middle;border-radius:8px;
                                     font-size:26px;">
                            📄
                          </td>
                        </tr>
                      </table>
                    </td>
                    <td valign="middle"
                        style="padding:12px 10px 12px 12px;
                               font-family:Arial,Helvetica,sans-serif;">
                      <p style="margin:0;color:#263a33;font-size:13px;
                                font-weight:bold;line-height:1.5;
                                word-break:break-word;">
                        {filename}
                      </p>
                      <p style="margin:4px 0 0;color:#7b8781;font-size:11px;">
                        Archivo adjunto al cambio de reserva
                      </p>
                    </td>
                    <td align="right" valign="middle"
                        style="padding:12px 14px 12px 4px;">
                      <a href="{file_url}"
                         style="display:inline-block;background:#173f35;
                                color:#ffffff;text-decoration:none;
                                padding:10px 12px;border-radius:5px;
                                font-size:12px;font-weight:bold;
                                white-space:nowrap;">
                        Descargar
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """

        attachments_html = f"""
        <tr>
          <td style="padding:0 32px 24px;">
            <h2 style="margin:0 0 6px;color:#263a33;font-size:18px;">
              Documentación adjunta
            </h2>
            <p style="margin:0 0 14px;color:#718078;font-size:13px;
                      line-height:1.6;">
              Consulta o descarga los archivos relacionados con este cambio.
            </p>
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0" border="0">
              {attachment_cards}
            </table>
          </td>
        </tr>
        """

    # Plantilla HTML.
    html_message = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Actualización de tu reserva</title>
    </head>
    <body style="margin:0;padding:0;background:#f3f5f7;
                 font-family:Arial,Helvetica,sans-serif;color:#263238;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
             style="background:#f3f5f7;padding:32px 12px;">
        <tr>
          <td align="center">
            <table role="presentation" width="600" cellspacing="0"
                   cellpadding="0"
                   style="width:100%;max-width:600px;background:#ffffff;
                          border-radius:12px;overflow:hidden;">
              <tr>
                <td style="background:#173f35;padding:28px 32px;color:#ffffff;">
                  <p style="margin:0;font-size:12px;letter-spacing:2px;
                            text-transform:uppercase;color:#d5e8df;">
                    Notificación de reserva
                  </p>
                  <h1 style="margin:10px 0 0;font-size:25px;line-height:1.3;">
                    Actualización de tu reserva
                  </h1>
                </td>
              </tr>

              <tr>
                <td style="padding:30px 32px 18px;">
                  <p style="margin:0 0 12px;font-size:16px;">
                    Hola {safe_guest},
                  </p>
                  <p style="margin:0;color:#52615d;font-size:15px;line-height:1.7;">
                    <strong>{safe_property}</strong> ha realizado un cambio
                    en las condiciones de tu reserva.
                  </p>
                </td>
              </tr>

              {previous_reservation_html}

              {current_reservation_html}

              {reason_html}

              {attachments_html}

              <tr>
                <td style="padding:22px 32px;background:#f7f9f8;
                           border-top:1px solid #e8eeeb;">
                  <p style="margin:0;color:#65716c;font-size:12px;line-height:1.7;">
                    Notificación automática de {safe_property}.
                    Si tienes dudas, contacta con el alojamiento
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

    email = EmailMultiAlternatives(
        subject=f"Actualización de tu reserva | {property_title}",
        body=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
    )
    email.attach_alternative(html_message, "text/html")

    try:
        result = email.send(fail_silently=False)
    except Exception:
        logger.exception(
            "Error al enviar el correo de cambio forzado de la reserva %s.",
            booking.pk,
        )
        return False

    if result != 1:
        logger.error(
            "No se confirmó el envío del cambio forzado de la reserva %s a %s.",
            booking.pk,
            recipient_email,
        )
        return False

    return True
  
def send_forced_booking_cancellation_email(booking, before_values, after_values, cancellation=None, request=None):
    """Notifica al huésped la cancelación forzada de una reserva."""

    recipient_email = (booking.guest_email or "").strip()

    if not recipient_email:
        logger.error(
            "La reserva %s no tiene un email de huésped.",
            booking.pk,
        )
        return False

    property_title = booking.property.title
    guest_name = booking.guest_first_name or "huésped"
    reason = (after_values.get("reason") or "").strip()
    owner_phone = getattr(booking.property.owner, "phone_number", None)

    def format_date(value):
        if not value or value == "—":
            return "—"
        try:
            return date.fromisoformat(str(value)).strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            return str(value)

    def format_price(value):
        try:
            if value is None or value == "—":
                return "—"
            return f"{Decimal(str(value)):.2f} €"
        except (TypeError, ValueError, ArithmeticError):
            return str(value)

    def get_value(values, key):
        value = values.get(key, "—")
        return "—" if value is None or value == "" else value

    
    # Obtener los archivos adjuntos de esta cancelación forzada.
    forced_attachments = (
        BookingAttachment.objects.filter(cancellation_request=cancellation)
        if cancellation is not None
        else []
    )

    attachment_items = []

    for attachment in forced_attachments:
        if request is None:
            logger.warning(
                "No se puede crear el enlace de descarga del adjunto %s "
                "porque no se recibió request.",
                attachment.pk,
            )
            continue

        token = signing.dumps(
            {
                "attachment_id": attachment.pk,
                "cancellation_id": cancellation.pk,
            },
            salt="forced-booking-attachment",
        )

        download_path = reverse(
            "download_forced_booking_attachment",
            kwargs={
                "attachment_id": attachment.pk,
                "token": token,
            },
        )

        attachment_items.append({
            "name": (
                attachment.original_filename
                or attachment.file.name.split("/")[-1]
            ),
            "url": request.build_absolute_uri(download_path),
        })

    # Datos de la reserva cancelada.
    reservation_fields = (
        ("Entrada prevista", "initial_date", format_date),
        ("Salida prevista", "final_date", format_date),
        ("Huéspedes", "guest_count", str),
        ("Precio total", "total_price", format_price),
    )

    # Texto plano.
    text_message = f"""Hola {guest_name},

Te informamos de que el alojamiento {property_title} ha cancelado tu reserva de forma forzada.

RESERVA: {booking.pk}

DATOS DE LA RESERVA CANCELADA
"""

    for label, field, formatter in reservation_fields:
        value = formatter(get_value(before_values, field))
        text_message += f"{label}: {value}\n"

    if reason:
        text_message += f"\nMOTIVO DE LA CANCELACIÓN\n{reason}\n"

    if attachment_items:
        text_message += "\nDOCUMENTACIÓN ADJUNTA\n"
        for item in attachment_items:
            text_message += f"- {item['name']}\n  {item['url']}\n"

    if owner_phone:
        text_message += (
            f"\nSi tienes dudas sobre esta cancelación, contacta con el "
            f"alojamiento en el teléfono {owner_phone}.\n"
        )

    text_message += (
        f"\nEsta es una notificación automática de {property_title}.\n"
    )

    # Escapar los valores dinámicos insertados en el HTML.
    safe_guest = escape(str(guest_name))
    safe_property = escape(str(property_title))
    safe_reason = escape(reason or "No se ha indicado un motivo.")
    safe_owner_phone = escape(str(owner_phone)) if owner_phone else ""

    # HTML del motivo de la cancelación.
    reason_html = ""

    if reason:
        reason_html = f"""
        <tr>
          <td style="padding:12px 32px 22px;">
            <h2 style="margin:0 0 12px;color:#263a33;font-size:18px;">
              Motivo de la cancelación
            </h2>
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0"
                   style="background:#f7f9f8;border-left:4px solid #b85c5c;">
              <tr>
                <td style="padding:16px;color:#52615d;font-size:14px;
                           line-height:1.8;white-space:pre-line;">
                  {safe_reason}
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """

    # Generar la tabla HTML de la reserva cancelada.
    def build_reservation_table(title, values, highlighted=False):
        background = "#fff1f1" if highlighted else "#f7f9f8"
        border_color = "#eed5d5" if highlighted else "#e3e9e6"
        title_color = "#8b3030" if highlighted else "#263a33"

        rows_html = ""

        for label, field, formatter in reservation_fields:
            value = formatter(get_value(values, field))

            rows_html += f"""
            <tr>
              <td style="padding:10px 16px;color:#52615d;
                         border-bottom:1px solid {border_color};
                         font-size:14px;">
                {escape(label)}
              </td>
              <td align="right"
                  style="padding:10px 16px;color:{title_color};
                         border-bottom:1px solid {border_color};
                         font-size:14px;font-weight:bold;">
                {escape(str(value))}
              </td>
            </tr>
            """

        return f"""
        <tr>
          <td style="padding:0 32px 20px;">
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0"
                   style="border:1px solid {border_color};border-radius:8px;">
              <tr>
                <td colspan="2"
                    style="padding:16px;background:{background};
                           color:{title_color};font-weight:bold;">
                  {escape(title)}
                </td>
              </tr>
              {rows_html}
            </table>
          </td>
        </tr>
        """

    cancelled_reservation_html = build_reservation_table(
        "Reserva cancelada",
        before_values,
        highlighted=True,
    )

    # Tarjetas HTML de archivos adjuntos.
    attachments_html = ""

    if attachment_items:
        attachment_cards = ""

        for item in attachment_items:
            filename = escape(str(item["name"]))
            file_url = escape(str(item["url"]))

            attachment_cards += f"""
            <tr>
              <td style="padding:0 0 10px;">
                <table role="presentation" width="100%" cellspacing="0"
                       cellpadding="0" border="0"
                       style="border:1px solid #e1e8e4;border-radius:9px;
                              background:#ffffff;">
                  <tr>
                    <td width="54" valign="middle"
                        style="padding:14px 0 14px 14px;">
                      <table role="presentation" width="42" height="46"
                             cellspacing="0" cellpadding="0" border="0"
                             style="background:#edf6f1;border-radius:6px;">
                        <tr>
                          <td style="background-color:#e8f5e9;color:#2e7d32;
                                     width:48px;height:48px;text-align:center;
                                     vertical-align:middle;border-radius:8px;
                                     font-size:26px;">
                            📄
                          </td>
                        </tr>
                      </table>
                    </td>
                    <td valign="middle"
                        style="padding:12px 10px 12px 12px;
                               font-family:Arial,Helvetica,sans-serif;">
                      <p style="margin:0;color:#263a33;font-size:13px;
                                font-weight:bold;line-height:1.5;
                                word-break:break-word;">
                        {filename}
                      </p>
                      <p style="margin:4px 0 0;color:#7b8781;font-size:11px;">
                        Archivo adjunto a la cancelación de la reserva
                      </p>
                    </td>
                    <td align="right" valign="middle"
                        style="padding:12px 14px 12px 4px;">
                      <a href="{file_url}"
                         style="display:inline-block;background:#173f35;
                                color:#ffffff;text-decoration:none;
                                padding:10px 12px;border-radius:5px;
                                font-size:12px;font-weight:bold;
                                white-space:nowrap;">
                        Descargar
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """

        attachments_html = f"""
        <tr>
          <td style="padding:0 32px 24px;">
            <h2 style="margin:0 0 6px;color:#263a33;font-size:18px;">
              Documentación adjunta
            </h2>
            <p style="margin:0 0 14px;color:#718078;font-size:13px;
                      line-height:1.6;">
              Consulta o descarga los archivos relacionados con esta cancelación.
            </p>
            <table role="presentation" width="100%" cellspacing="0"
                   cellpadding="0" border="0">
              {attachment_cards}
            </table>
          </td>
        </tr>
        """

    # Plantilla HTML.
    html_message = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Cancelación de tu reserva</title>
    </head>
    <body style="margin:0;padding:0;background:#f3f5f7;
                 font-family:Arial,Helvetica,sans-serif;color:#263238;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
             style="background:#f3f5f7;padding:32px 12px;">
        <tr>
          <td align="center">
            <table role="presentation" width="600" cellspacing="0"
                   cellpadding="0"
                   style="width:100%;max-width:600px;background:#ffffff;
                          border-radius:12px;overflow:hidden;">
              <tr>
                <td style="background:#173f35;padding:28px 32px;color:#ffffff;">
                  <p style="margin:0;font-size:12px;letter-spacing:2px;
                            text-transform:uppercase;color:#d5e8df;">
                    Notificación de reserva
                  </p>
                  <h1 style="margin:10px 0 0;font-size:25px;line-height:1.3;">
                    Reserva cancelada
                  </h1>
                </td>
              </tr>

              <tr>
                <td style="padding:30px 32px 18px;">
                  <p style="margin:0 0 12px;font-size:16px;">
                    Hola {safe_guest},
                  </p>
                  <p style="margin:0;color:#52615d;font-size:15px;line-height:1.7;">
                    Te informamos de que <strong>{safe_property}</strong>
                    ha cancelado tu reserva de forma forzada.
                  </p>
                </td>
              </tr>

              {cancelled_reservation_html}

              {reason_html}

              {attachments_html}

              <tr>
                <td style="padding:22px 32px;background:#f7f9f8;
                           border-top:1px solid #e8eeeb;">
                  <p style="margin:0;color:#65716c;font-size:12px;line-height:1.7;">
                    Esta es una notificación automática de {safe_property}.
                    Si tienes dudas sobre la cancelación, contacta con el alojamiento
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

    email = EmailMultiAlternatives(
        subject=f"Cancelación de tu reserva | {property_title}",
        body=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
    )
    email.attach_alternative(html_message, "text/html")

    try:
        result = email.send(fail_silently=False)
    except Exception:
        logger.exception(
            "Error al enviar el correo de cancelación forzada de la reserva %s.",
            booking.pk,
        )
        return False

    if result != 1:
        logger.error(
            "No se confirmó el envío de la cancelación forzada de la reserva "
            "%s a %s.",
            booking.pk,
            recipient_email,
        )
        return False

    return True