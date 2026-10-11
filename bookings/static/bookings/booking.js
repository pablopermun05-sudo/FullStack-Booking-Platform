
let bookingReady = false;

document.addEventListener("DOMContentLoaded", () => {
    const propertyId = document.querySelector("#property-id").value;
    const alertDiv = document.querySelector("#alert-booking-date");
    const buttonDiv = document.querySelector("#booking-button");
    const startDate = document.querySelector("#start-date");
    const endDate = document.querySelector("#end-date");

    function showError(message) {
        bookingReady = false;
        buttonDiv.classList.add("no-display");
        alertDiv.textContent = message;
        alertDiv.classList.remove("no-display");
    }

    window.clearBookingSelection = function () {
        bookingReady = false;
        startDate.value = "";
        endDate.value = "";
        buttonDiv.classList.add("no-display");
        alertDiv.textContent = "";
        alertDiv.classList.add("no-display");
    };

    function attachBookingButton(button) {
        button.addEventListener("click", async () => {
            if (!bookingReady) return;
            
            button.disabled = true;

            try {
                const response = await fetch(`/booking/${propertyId}/hold`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": getCookie("csrftoken"),
                    },
                    body: JSON.stringify({
                        start: startDate.value,
                        end: endDate.value,
                    }),
                });

                const result = await response.json();

                if (!response.ok || !result.success) {
                    alert(result.error || "No se pudieron retener las fechas.");
                    return;
                }

                const params = new URLSearchParams({
                    initial_date: startDate.value,
                    final_date: endDate.value,
                    hold_token: result.token,
                });

                window.location.href =
                    `/booking/${propertyId}/details?${params.toString()}`;
            } catch (error) {
                alert("Error de conexión al intentar retener las fechas.");
            } finally {
                button.disabled = false;
            }
        });
    }

    function getCookie(name) {
        const cookies = document.cookie ? document.cookie.split(";") : [];

        for (const cookie of cookies) {
            const item = cookie.trim();

            if (item.startsWith(`${name}=`)) {
                return decodeURIComponent(item.substring(name.length + 1));
            }
        }

        return null;
    }

    function createBookingButton() {
        buttonDiv.classList.remove("no-display");
        buttonDiv.textContent = "";

        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Crear reserva";
        button.id = "confirm-booking-button";
        button.className =
            "btn btn-dark w-100 rounded-pill mt-3 mb-3 py-2";

        attachBookingButton(button);
        buttonDiv.appendChild(button);

        return button;
    }

    window.validateBooking = function () {
        bookingReady = false;

        if (!startDate.value || !endDate.value) {
            buttonDiv.classList.add("no-display");
            return;
        }

        buttonDiv.classList.remove("no-display");

        const initialDate = new Date(startDate.value);
        const finalDate = new Date(endDate.value);

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        if (initialDate < today) {
            showError(
                "La fecha de entrada no puede ser anterior al día de hoy."
            );
            return;
        }

        if (initialDate >= finalDate) {
            showError(
                "La fecha de salida debe ser posterior a la de entrada."
            );
            return;
        }

        alertDiv.textContent = "";
        alertDiv.classList.add("no-display");

        let button = document.querySelector("#confirm-booking-button");

        if (!button) {
            button = createBookingButton();
        }

        button.disabled = true;

        const params = new URLSearchParams({
            start: startDate.value,
            end: endDate.value
        });

        fetch(`/booking/${propertyId}/?${params.toString()}`)
            .then(async (response) => {
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.error || "No se pudieron validar las fechas."
                    );
                }

                return data;
            })
            .then((data) => {
                if (data.available) {
                    bookingReady = true;
                } else {
                    showError(
                        "Las fechas seleccionadas ya no están disponibles."
                    );
                }
            })
            .catch((error) => {
                showError(error.message || "Error inesperado.");
            })
            .finally(() => {
                button.disabled = false;
            });
    };

    const initialButton = document.querySelector("#confirm-booking-button");

    if (initialButton) {
        attachBookingButton(initialButton);
    }

    if (startDate.value && endDate.value) {
        window.validateBooking();
    }
});