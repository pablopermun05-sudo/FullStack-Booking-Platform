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

    const attachmentsInput = document.getElementById('booking-attachments');
    const attachmentsList = document.getElementById('booking-attachments-list');

    const MAX_ATTACHMENTS = 5;
    const MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024;

    // Archivos importados: conserva la selección al abrir el selector
    // varias veces y permite quitar archivos antes de enviar el formulario.
    let selectedAttachments = [];

    function syncAttachmentsInput() {
        const dataTransfer = new DataTransfer();

        selectedAttachments.forEach(file => {
            dataTransfer.items.add(file);
        });

        attachmentsInput.files = dataTransfer.files;
    }

    function formatFileSize(bytes) {
        if (bytes < 1024 * 1024) {
            return `${(bytes / 1024).toFixed(0)} KB`;
        }

        return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
    }

    function renderAttachmentsList() {
        if (!attachmentsList) {
            return;
        }

        attachmentsList.replaceChildren();

        const header = document.createElement('div');
        header.className = 'booking-selected-files-header';

        const count = document.createElement('span');
        count.className = 'booking-selected-files-count';
        count.textContent =
            `Archivos importados (${selectedAttachments.length} de ${MAX_ATTACHMENTS})`;

        header.appendChild(count);
        attachmentsList.appendChild(header);

        if (selectedAttachments.length === 0) {
            const emptyMessage = document.createElement('p');
            emptyMessage.className = 'booking-selected-files-empty';
            emptyMessage.textContent = 'Todavía no has añadido ningún archivo.';
            attachmentsList.appendChild(emptyMessage);
            return;
        }

        const list = document.createElement('ul');
        list.className = 'booking-selected-files-list';

        selectedAttachments.forEach((file, index) => {
            const item = document.createElement('li');
            item.className = 'booking-selected-file';

            const icon = document.createElement('i');
            icon.className = 'bi bi-file-earmark-text booking-selected-file-icon';
            icon.setAttribute('aria-hidden', 'true');

            const details = document.createElement('div');
            details.className = 'booking-selected-file-details';

            const name = document.createElement('span');
            name.className = 'booking-selected-file-name';
            name.textContent = file.name;
            name.title = file.name;

            const size = document.createElement('span');
            size.className = 'booking-selected-file-size';
            size.textContent = formatFileSize(file.size);

            details.append(name, size);

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'booking-selected-file-remove';
            removeButton.setAttribute(
                'aria-label',
                `Quitar archivo ${file.name}`
            );
            removeButton.title = 'Quitar archivo';
            removeButton.innerHTML = '&times;';

            removeButton.addEventListener('click', () => {
                selectedAttachments.splice(index, 1);
                syncAttachmentsInput();
                renderAttachmentsList();
                messageBox.classList.add('d-none');
            });

            item.append(icon, details, removeButton);
            list.appendChild(item);
        });

        attachmentsList.appendChild(list);
    }


    if (attachmentsInput) {
        const dropzone = document.querySelector('.booking-attachments-dropzone');

        function addAttachments(files) {
            let validationMessage = '';

            for (const file of Array.from(files)) {
                const alreadySelected = selectedAttachments.some(
                    existing =>
                        existing.name === file.name &&
                        existing.size === file.size &&
                        existing.lastModified === file.lastModified
                );

                if (alreadySelected) {
                    continue;
                }

                if (file.size > MAX_ATTACHMENT_SIZE) {
                    validationMessage =
                        `El archivo "${file.name}" supera el límite de 10 MB.`;
                    continue;
                }

                if (selectedAttachments.length >= MAX_ATTACHMENTS) {
                    validationMessage =
                        'Solo puedes adjuntar un máximo de 5 archivos.';
                    break;
                }

                selectedAttachments.push(file);
            }

            syncAttachmentsInput();
            renderAttachmentsList();

            if (validationMessage) {
                showMessage(validationMessage);
            } else {
                messageBox.classList.add('d-none');
            }
        }

        attachmentsInput.addEventListener('change', () => {
            const files = Array.from(attachmentsInput.files);

            addAttachments(files);

            // Permite volver a elegir un archivo después de quitarlo.
            attachmentsInput.value = '';
            syncAttachmentsInput();
        });

        if (dropzone) {
            // Evita que el navegador abra el archivo al soltarlo.
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                dropzone.addEventListener(eventName, event => {
                    event.preventDefault();
                    event.stopPropagation();
                });
            });

            ['dragenter', 'dragover'].forEach(eventName => {
                dropzone.addEventListener(eventName, () => {
                    dropzone.classList.add('is-dragging');
                });
            });

            ['dragleave', 'drop'].forEach(eventName => {
                dropzone.addEventListener(eventName, () => {
                    dropzone.classList.remove('is-dragging');
                });
            });

            dropzone.addEventListener('drop', event => {
                const files = event.dataTransfer
                    ? Array.from(event.dataTransfer.files)
                    : [];

                if (files.length > 0) {
                    addAttachments(files);
                }
            });
        }

        renderAttachmentsList();
    }

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

            if (attachmentsInput) {
                const files = Array.from(attachmentsInput.files);

                if (files.length > MAX_ATTACHMENTS) {
                    throw new Error('Solo puedes adjuntar un máximo de 5 archivos.');
                }

                for (const file of files) {
                    if (file.size > MAX_ATTACHMENT_SIZE) {
                        throw new Error(
                            `El archivo "${file.name}" supera el límite de 10 MB.`
                        );
                    }

                    formData.append('attachments', file);
                }
            }

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