
(() => {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        const form = document.getElementById("booking-details-form");
        if (!form) return;

        const errorDiv = document.getElementById("booking-form-error");
        const submitButton = document.getElementById("submit-booking-details");
        const cancelButton = document.getElementById("cancel-booking-details");
        const holdTokenInput = document.getElementById("booking-hold-token");

        const submitButtonText = document.getElementById(
            "submit-booking-details-text"
        );
        const cancelButtonText = document.getElementById(
            "cancel-booking-details-text"
        );

        let submissionInProgress = false;
        let releaseRequested = false;
        let releasePromise = null;
        let bookingCreated = false;

        function getCookie(name) {
            const cookies = document.cookie
                ? document.cookie.split(";")
                : [];

            for (const cookie of cookies) {
                const value = cookie.trim();

                if (value.startsWith(`${name}=`)) {
                    return decodeURIComponent(
                        value.substring(name.length + 1)
                    );
                }
            }

            return null;
        }

        function getFormValue(formData, name) {
            return String(formData.get(name) ?? "").trim();
        }

        function setError(message) {
            errorDiv.textContent = message;
            errorDiv.hidden = false;
        }

        function setSubmitText(text) {
            if (submitButtonText) {
                submitButtonText.textContent = text;
            } else {
                submitButton.textContent = text;
            }
        }

        function setCancelText(text) {
            if (cancelButtonText) {
                cancelButtonText.textContent = text;
            } else {
                cancelButton.textContent = text;
            }
        }

        async function releaseHold(keepalive = false) {
            if (releasePromise) return releasePromise;
            if (releaseRequested) return;

            const token = holdTokenInput?.value;
            if (!token) return;

            releaseRequested = true;

            releasePromise = (async () => {
                try {
                    const response = await fetch(form.dataset.releaseUrl, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": getCookie("csrftoken") || ""
                        },
                        body: JSON.stringify({ hold_token: token }),
                        keepalive
                    });

                    if (!response.ok) {
                        console.warn(
                            "No se pudo confirmar la liberación de la retención."
                        );
                    }
                } catch (error) {
                    console.warn(
                        "No se pudo enviar la petición para liberar la retención."
                    );
                }
            })();

            return releasePromise;
        }

        // Cancelación manual.
        cancelButton.addEventListener("click", async () => {
            if (submissionInProgress) return;

            cancelButton.disabled = true;
            setCancelText("Cancelando…");

            await releaseHold();

            window.location.assign(form.dataset.cancelUrl);
        });

        // Intento de liberar la retención si se abandona la página.
        window.addEventListener("pagehide", () => {
            if (!submissionInProgress && !releaseRequested) {
                void releaseHold(true);
            }
        });

        // Envío de los datos.
        form.addEventListener("submit", async event => {
            event.preventDefault();

            if (submissionInProgress) return;

            errorDiv.hidden = true;
            errorDiv.textContent = "";

            if (!form.reportValidity()) return;

            submissionInProgress = true;
            submitButton.disabled = true;
            cancelButton.disabled = true;
            setSubmitText("Procesando reserva…");

            try {
                // Comprueba que el teléfono se ha inicializado correctamente.
                if (
                    !window.bookingPhone?.ready ||
                    typeof window.bookingPhone.sync !== "function"
                ) {
                    throw new Error(
                        "No se ha podido inicializar el teléfono. Recarga la página e inténtalo de nuevo."
                    );
                }

                try {
                    await window.bookingPhone.ready;
                } catch {
                    throw new Error(
                        "No se ha podido preparar el teléfono. Recarga la página e inténtalo de nuevo."
                    );
                }

                // Sincroniza el número internacional antes de leer el formulario.
                window.bookingPhone.sync();

                const phoneHidden = document.getElementById("guest-phone");

                if (!phoneHidden?.value.trim()) {
                    throw new Error(
                        "No se ha podido obtener el teléfono. Comprueba el número e inténtalo de nuevo."
                    );
                }

                const formData = new FormData(form);

                const payload = {
                    start: form.querySelector('[name="start"]').value,
                    end: form.querySelector('[name="end"]').value,

                    guest_first_name: getFormValue(formData, "guest_first_name"),
                    guest_last_name: getFormValue(formData, "guest_last_name"),
                    guest_email: getFormValue(formData, "guest_email"),
                    guest_phone_number: getFormValue(formData, "guest_phone_number"),
                    guest_country: getFormValue(formData, "guest_country"),
                    guest_region: getFormValue(formData, "guest_region"),
                    guest_city: getFormValue(formData, "guest_city"),
                    guest_postal_code: getFormValue(formData, "guest_postal_code"),
                    guest_address: getFormValue(formData, "guest_address"),

                    guest_count: formData.get("guest_count"),
                    arrival_time: formData.get("arrival_time"),

                    is_for_self: formData.has("is_for_self"),
                    is_business_trip: formData.has("is_business_trip"),

                    tax_id: getFormValue(formData, "tax_id"),
                    special_requests: getFormValue(formData, "special_requests"),

                    hold_token: holdTokenInput?.value || ""
                };

                const csrfToken = getCookie("csrftoken");

                const response = await fetch(form.dataset.createUrl, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        ...(csrfToken ? { "X-CSRFToken": csrfToken } : {})
                    },
                    body: JSON.stringify(payload)
                });

                let data;

                try {
                    data = await response.json();
                } catch {
                    throw new Error(
                        "El servidor devolvió una respuesta inesperada. Inténtalo de nuevo."
                    );
                }

                if (!response.ok || !data?.success) {
                    const message = typeof data?.error === "string"
                        ? data.error
                        : "No se pudo crear la reserva. Comprueba los datos e inténtalo de nuevo.";

                    throw new Error(message);
                }

                bookingCreated = true;

                if (typeof data.payment_url !== "string" || !data.payment_url) {
                    throw new Error(
                        "La reserva se ha creado, pero no se recibió la dirección de pago. Contacta con el alojamiento antes de volver a intentarlo."
                    );
                }

                // No liberar la retención: el servidor la ha convertido.
                releaseRequested = true;

                window.location.assign(data.payment_url);
            } catch (error) {
                setError(
                    error instanceof Error
                        ? error.message
                        : "Error al procesar la reserva. Inténtalo de nuevo."
                );

                // Si el servidor ya creó la reserva, no permitimos
                // otro envío que pudiera crear una reserva duplicada.
                if (bookingCreated) {
                    setSubmitText("Reserva procesada");
                    setError(
                        "La reserva se ha creado, pero no se ha podido completar la redirección al pago. No vuelvas a enviar el formulario; contacta con el alojamiento."
                    );
                    return;
                }

                submissionInProgress = false;

                cancelButton.disabled = false;
                submitButton.disabled = false;

                setCancelText("Cancelar y volver");
                setSubmitText("Siguiente paso");
            }
        });

        // Sincronización: reserva para uno mismo o para otra persona.
        const forSelfRadio = document.getElementById("for-self-radio");
        const forOtherRadio = document.getElementById("for-other-radio");
        const isForSelfCheckbox = document.getElementById("is-for-self");

        function syncForSelf() {
            isForSelfCheckbox.checked = forSelfRadio.checked;
        }

        forSelfRadio.addEventListener("change", syncForSelf);
        forOtherRadio.addEventListener("change", syncForSelf);
        syncForSelf();

        // Mostrar y validar el CIF/NIF para viajes de empresa.
        const businessYesRadio = document.getElementById("business-yes-radio");
        const businessNoRadio = document.getElementById("business-no-radio");
        const isBusinessCheckbox = document.getElementById("is-business-trip");
        const taxIdContainer = document.getElementById("tax-id-container");
        const taxIdInput = document.getElementById("tax-id");

        function syncBusinessTrip() {
            const isBusiness = businessYesRadio.checked;

            isBusinessCheckbox.checked = isBusiness;
            taxIdContainer.style.display = isBusiness ? "block" : "none";
            taxIdInput.required = isBusiness;

            if (!isBusiness) {
                taxIdInput.value = "";
            }
        }

        businessYesRadio.addEventListener("change", syncBusinessTrip);
        businessNoRadio.addEventListener("change", syncBusinessTrip);
        syncBusinessTrip();

        // Abrir el selector nativo de hora cuando el navegador lo permita.
        const arrivalInput = document.getElementById("arrival-time");

        if (arrivalInput) {
            arrivalInput.addEventListener("click", function () {
                if (typeof this.showPicker !== "function") return;

                try {
                    this.showPicker();
                } catch {
                    // Se conserva el comportamiento nativo del navegador.
                }
            });
        }
    });
})();