
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('booking-cancellation-form');

    if (!form) return;

    const submitButton = document.getElementById('submit-cancellation');
    const messageBox = document.getElementById('booking-cancellation-message');

    const proposalMode = document.getElementById('mode-proposal');
    const forcedMode = document.getElementById('mode-forced');

    const forcedFields = document.getElementById('forced-cancellation-fields');
    const forceConfirmation = document.getElementById('force-confirmation');

    const attachmentsInput = document.getElementById('booking-attachments');
    const attachmentsList = document.getElementById('booking-attachments-list');

    const MAX_ATTACHMENTS = 5;
    const MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024;

    let selectedAttachments = [];

    function showMessage(text, type = 'danger') {
        messageBox.textContent = text;
        messageBox.className = `alert alert-${type}`;
        messageBox.classList.remove('d-none');
    }

    function updateMode() {
        const isForced = forcedMode ? forcedMode.checked : false;

        if (forcedFields) {
            forcedFields.classList.toggle('d-none', !isForced);
        }

        if (forceConfirmation) {
            forceConfirmation.required = isForced;

            if (!isForced) {
                forceConfirmation.checked = false;
            }
        }

        submitButton.innerHTML = isForced
            ? 'Confirmar cancelación forzada'
            : 'Enviar propuesta de cancelación';
    }

    proposalMode?.addEventListener('change', updateMode);
    forcedMode?.addEventListener('change', updateMode);
    updateMode();

    function syncAttachmentsInput() {
        const dataTransfer = new DataTransfer();

        selectedAttachments.forEach(file => dataTransfer.items.add(file));

        attachmentsInput.files = dataTransfer.files;
    }

    function formatFileSize(bytes) {
        if (bytes < 1024 * 1024) {
            return `${(bytes / 1024).toFixed(0)} KB`;
        }

        return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
    }

    function renderAttachmentsList() {
        if (!attachmentsList) return;

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
            icon.className =
                'bi bi-file-earmark-text booking-selected-file-icon';
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
                const duplicate = selectedAttachments.some(
                    existing =>
                        existing.name === file.name &&
                        existing.size === file.size &&
                        existing.lastModified === file.lastModified
                );

                if (duplicate) continue;

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
            attachmentsInput.value = '';
            syncAttachmentsInput();
        });

        if (dropzone) {
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(name => {
                dropzone.addEventListener(name, event => {
                    event.preventDefault();
                    event.stopPropagation();
                });
            });

            ['dragenter', 'dragover'].forEach(name => {
                dropzone.addEventListener(name, () => {
                    dropzone.classList.add('is-dragging');
                });
            });

            ['dragleave', 'drop'].forEach(name => {
                dropzone.addEventListener(name, () => {
                    dropzone.classList.remove('is-dragging');
                });
            });

            dropzone.addEventListener('drop', event => {
                const files = event.dataTransfer
                    ? Array.from(event.dataTransfer.files)
                    : [];

                if (files.length) addAttachments(files);
            });
        }

        renderAttachmentsList();
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();

        messageBox.classList.add('d-none');

        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        const isForced = forcedMode ? forcedMode.checked : false;

        if (isForced && !forceConfirmation.checked) {
            showMessage(
                'Debes confirmar que deseas forzar la cancelación.'
            );
            return;
        }

        if (isForced && !window.confirm(
            'La reserva se cancelará inmediatamente. ¿Deseas continuar?'
        )) {
            return;
        }

        if (selectedAttachments.length > MAX_ATTACHMENTS) {
            showMessage('Solo puedes adjuntar un máximo de 5 archivos.');
            return;
        }

        for (const file of selectedAttachments) {
            if (file.size > MAX_ATTACHMENT_SIZE) {
                showMessage(
                    `El archivo "${file.name}" supera el límite de 10 MB.`
                );
                return;
            }
        }

        submitButton.disabled = true;
        submitButton.textContent = isForced
            ? 'Cancelando reserva...'
            : 'Enviando propuesta...';

        try {
            const formData = new FormData(form);

            const endpoint = isForced
                ? form.dataset.forceUrl
                : form.dataset.proposalUrl;

            if (!endpoint) {
                throw new Error(
                    'No se ha configurado la URL para esta modalidad de cancelación.'
                );
            }

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': form.querySelector(
                        '[name="csrfmiddlewaretoken"]'
                    ).value,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
                body: formData,
                credentials: 'same-origin',
            });

            const contentType = response.headers.get('content-type') || '';

            if (!contentType.includes('application/json')) {
                throw new Error(
                    `Respuesta inesperada del servidor (HTTP ${response.status}).`
                );
            }

            const data = await response.json();

            if (!response.ok || data.success !== true) {
                const error = data.error || data.message ||
                    'No se pudo procesar la cancelación.';

                throw new Error(
                    Array.isArray(error) ? error.join(' ') : error
                );
            }

            showMessage(
                data.message || 'La operación se ha completado correctamente.',
                'success'
            );

            // Evita enviar la misma operación dos veces.
            form.querySelectorAll('input, textarea, button').forEach(element => {
                element.disabled = true;
            });

        } catch (error) {
            showMessage(
                error.message ||
                'Ha ocurrido un error al procesar la cancelación.'
            );
            submitButton.disabled = false;
            updateMode();
        }
    });
});