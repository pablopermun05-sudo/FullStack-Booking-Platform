document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('booking-change-form');

    if (!form) {
        return;
    }

    const submitButton = document.getElementById('submit-change-proposal');
    const messageBox = document.getElementById('booking-change-message');

    const proposalMode = document.getElementById('mode-proposal');
    const forcedMode = document.getElementById('mode-forced');

    const forcedFields = document.getElementById('forced-change-fields');
    const forceReason = document.getElementById('force-reason');
    const forceConfirmation = document.getElementById('force-confirmation');

    const proposalReasonFields = document.getElementById('proposal-reason-fields');
    const proposalReason = document.getElementById('proposal-reason');

    const initialDateInput = document.getElementById('proposed-initial-date');
    const finalDateInput = document.getElementById('proposed-final-date');
    const guestCountInput = document.getElementById('proposed-guest-count');
    
    // Mantener sincronizada la cotización al cambiar las fechas,
    // tanto para propuestas como para cambios forzados.
    form.addEventListener('bookingDatesChanged', () => {
        const startDate = initialDateInput.value;
        const endDate = finalDateInput.value;

        if (
            startDate &&
            endDate &&
            typeof updateProposedBookingPrice === 'function'
        ) {
            updateProposedBookingPrice(startDate, endDate);
        }
    });

    const originalInitialDate = form.dataset.initialDate;
    const originalFinalDate = form.dataset.finalDate;

    // La cantidad original de huéspedes se obtiene del valor inicial del campo.
    const originalGuestCount = Number(guestCountInput.defaultValue);

    function updateChangeMode() {
        // Si no existe el selector de cambio forzado,
        // el usuario solo puede proponer cambios.
        const isForced = forcedMode ? forcedMode.checked : false;

        if (forcedFields) {
            forcedFields.classList.toggle('d-none', !isForced);
        }

        if (proposalReasonFields) {
            proposalReasonFields.classList.toggle('d-none', isForced);
        }

        if (proposalReason) {
            proposalReason.required = !isForced;
        }

        if (forceReason) {
            forceReason.required = isForced;
        }

        if (forceConfirmation) {
            forceConfirmation.required = isForced;
        }

        submitButton.innerHTML = isForced
            ? 'Confirmar cambio forzado'
            : 'Enviar propuesta de cambio';
    }

    
    function updatePriceDifference() {
        const totalElement = document.getElementById('proposed-total-price');
        const proposedTotalLabel = document.getElementById('proposed-total-price-label');

        if (!proposedTotalLabel || !totalElement) {
            return;
        }

        const proposedText = totalElement.textContent.trim();

        // Si todavía no hay cotización, mostrar un guion.
        proposedTotalLabel.textContent = proposedText || '-';
    }

    const proposedTotalElement = document.getElementById('proposed-total-price');

    if (proposedTotalElement) {
        new MutationObserver(() => {
            updatePriceDifference();
        }).observe(proposedTotalElement, {
            childList: true,
            characterData: true,
            subtree: true
        });
    }

    // Mostrar el guion al cargar el formulario.
    updatePriceDifference();

    if (proposalMode) {
        proposalMode.addEventListener('change', updateChangeMode);
    }

    if (forcedMode) {
        forcedMode.addEventListener('change', updateChangeMode);
    }

    updateChangeMode();

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
        const isForced = forcedMode ? forcedMode.checked : false;

        submitButton.textContent = isForced
            ? 'Aplicando cambio...'
            : 'Enviando propuesta...';

        try {
            const formData = new FormData();

            formData.append('proposed_initial_date', proposedInitialDate);
            formData.append('proposed_final_date', proposedFinalDate);
            formData.append('proposed_guest_count', String(proposedGuestCount));

            let endpoint = form.dataset.proposalUrl;

            if (isForced) {
                endpoint = form.dataset.forceUrl;

                formData.append('force_reason', forceReason.value.trim());

                if (forceConfirmation.checked) {
                    formData.append('force_confirmation', 'on');
                }
            } else {
                formData.append('reason', proposalReason.value.trim());
            }

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json'
                },
                body: formData,
                credentials: 'same-origin'
            });

            const contentType = response.headers.get('content-type') || '';

            if (!contentType.includes('application/json')) {
                throw new Error(
                    `El servidor devolvió una respuesta inesperada (HTTP ${response.status}).`
                );
            }

            const data = await response.json();

            if (!response.ok || data.success !== true) {
                const errorMessage = data.message || data.error || 'No se pudo realizar el cambio.';
                throw new Error(
                    Array.isArray(errorMessage)
                        ? errorMessage.join(' ')
                        : errorMessage
                );
            }

            let successMessage = data.message;

            if (isForced) {
                successMessage = 'La reserva se ha modificado correctamente.';
            }

            showMessage(
                successMessage || 'La operación se ha completado correctamente.',
                'success'
            );

        } catch (error) {
            showMessage(
                error.message || 'Ha ocurrido un error al procesar el cambio.'
            );
        } finally {
            submitButton.disabled = false;
            updateChangeMode();
        }
    });
});