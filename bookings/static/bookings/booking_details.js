document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("#booking-details-form");
    if (!form) return;

    const errorDiv = document.querySelector("#booking-form-error");
    const submitButton = document.querySelector("#submit-booking-details");
    const cancelButton = document.querySelector("#cancel-booking-details");
    const holdTokenInput = document.querySelector("#booking-hold-token");

    let submissionInProgress = false;
    let releaseRequested = false;

    function getCookie(name) {
        const cookies = document.cookie ? document.cookie.split(";") : [];

        for (const cookie of cookies) {
            const value = cookie.trim();

            if (value.startsWith(`${name}=`)) {
                return decodeURIComponent(value.substring(name.length + 1));
            }
        }

        return null;
    }

    async function releaseHold(keepalive = false) {
        if (releaseRequested) return;

        releaseRequested = true;

        const token = holdTokenInput.value;
        if (!token) return;

        try {
            await fetch(form.dataset.releaseUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify({ hold_token: token }),
                keepalive,
            });
        } catch (error) {
            // Si el navegador no consigue enviar la petición,
            // la retención seguirá caducando por sí sola.
        }
    }

    cancelButton.addEventListener("click", async () => {
        cancelButton.disabled = true;
        cancelButton.textContent = "Cancelando…";

        await releaseHold();

        window.location.assign(form.dataset.cancelUrl);
    });

    window.addEventListener("pagehide", () => {
        if (!submissionInProgress && !releaseRequested) {
            // Es un intento de mejor esfuerzo: el navegador puede
            // cerrar la página antes de completar la petición.
            void releaseHold(true);
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        if (submissionInProgress) return;

        errorDiv.hidden = true;
        errorDiv.textContent = "";

        if (!form.reportValidity()) return;

        const formData = new FormData(form);

        const payload = {
            start: form.elements.start.value,
            end: form.elements.end.value,
            guest_first_name: formData.get("guest_first_name").trim(),
            guest_last_name: formData.get("guest_last_name").trim(),
            guest_email: formData.get("guest_email").trim(),
            guest_phone_number: formData.get("guest_phone_number").trim(),
            guest_country: formData.get("guest_country").trim(),
            guest_region: formData.get("guest_region").trim(),
            guest_city: formData.get("guest_city").trim(),
            guest_postal_code: formData.get("guest_postal_code").trim(),
            guest_address: formData.get("guest_address").trim(),
            guest_count: formData.get("guest_count"),
            arrival_time: formData.get("arrival_time"),
            is_for_self: formData.has("is_for_self"),
            is_business_trip: formData.has("is_business_trip"),
            tax_id: formData.get("tax_id").trim(),
            special_requests: formData.get("special_requests").trim(),
            hold_token: holdTokenInput.value,
        };

        submissionInProgress = true;
        submitButton.disabled = true;
        cancelButton.disabled = true;
        submitButton.textContent = "Procesando reserva…";

        try {
            const response = await fetch(form.dataset.createUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                const message = typeof data.error === "string"
                    ? data.error
                    : JSON.stringify(data.error || data);

                throw new Error(
                    message || "No se pudo crear la reserva."
                );
            }

            // La retención ya se ha convertido en una reserva pendiente.
            // No debemos intentar liberarla al salir de esta página.
            releaseRequested = true;

            window.location.assign(data.payment_url);
        } catch (error) {
            submissionInProgress = false;
            cancelButton.disabled = false;

            errorDiv.textContent =
                error.message || "Error al procesar la reserva.";
            errorDiv.hidden = false;

            submitButton.disabled = false;
            submitButton.textContent = "Confirmar reserva";
        }
    });
});