document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('booking-change-form');

    if (!form) {
        return;
    }

    const submitButton = document.getElementById('submit-change-proposal');
    const messageBox = document.getElementById('booking-change-message');

    const initialDateInput = document.getElementById('proposed-initial-date');
    const finalDateInput = document.getElementById('proposed-final-date');
    const guestCountInput = document.getElementById('proposed-guest-count');

    const originalInitialDate = form.dataset.initialDate;
    const originalFinalDate = form.dataset.finalDate;

    // La cantidad original de huéspedes se obtiene del valor inicial del campo.
    const originalGuestCount = Number(guestCountInput.defaultValue);

    function showMessage(message, type = 'danger') {
        messageBox.textContent = message;
        messageBox.className = `alert alert-${type}`;
        messageBox.classList.remove('d-none');
    }

    function getCsrfToken() {
        return form.querySelector('[name="csrfmiddlewaretoken"]').value;
    }

    submitButton.addEventListener('click', async () => {
        messageBox.classList.add('d-none');

        const proposedInitialDate = initialDateInput.value;
        const proposedFinalDate = finalDateInput.value;
        const proposedGuestCount = Number(guestCountInput.value);

        // Comprobar si realmente ha cambiado algún campo.
        const dateChanged =
            proposedInitialDate !== originalInitialDate ||
            proposedFinalDate !== originalFinalDate;

        const guestCountChanged =
            proposedGuestCount !== originalGuestCount;

        if (!dateChanged && !guestCountChanged) {
            alert(
                'No se ha enviado la propuesta porque no has cambiado ' +
                'ninguna condición de la reserva. Modifica las fechas ' +
                'o el número de huéspedes antes de continuar.'
            );
            return;
        }

        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        submitButton.disabled = true;

        const originalButtonText = submitButton.innerHTML;
        submitButton.textContent = 'Enviando propuesta...';

        try {
            const formData = new FormData();

            formData.append('proposed_initial_date', proposedInitialDate);
            formData.append('proposed_final_date', proposedFinalDate);
            formData.append('proposed_guest_count', String(proposedGuestCount));

            const response = await fetch(form.dataset.proposalUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData,
                credentials: 'same-origin'
            });

            const contentType = response.headers.get('content-type') || '';

            if (!contentType.includes('application/json')) {
                const responseText = await response.text();

                console.error('Respuesta inesperada del servidor:', {
                    status: response.status,
                    url: response.url,
                    contentType,
                    body: responseText.slice(0, 1000)
                });

                throw new Error(
                    `El servidor ha devuelto una respuesta HTML en lugar de JSON (HTTP ${response.status}). Revisa la consola.`
                );
            }

            const data = await response.json();

            if (!response.ok || data.success !== true) {
                const errorMessage = data.message || data.error;
                const message = Array.isArray(errorMessage)
                    ? errorMessage.join(' ')
                    : errorMessage;

                throw new Error(
                    message || 'No se ha podido enviar la propuesta.'
                );
            }

            showMessage(
                data.message || 'La propuesta de cambio se ha enviado correctamente.',
                'success'
            );

        } catch (error) {
            showMessage(
                error.message || 'Ha ocurrido un error al enviar la propuesta.'
            );
        } finally {
            submitButton.disabled = false;
            submitButton.innerHTML = originalButtonText;
        }
    });
});