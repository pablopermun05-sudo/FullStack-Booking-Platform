let successBooking = false;
let bookingReady = false;

document.addEventListener('DOMContentLoaded', () => {
    const propertyId = document.querySelector('#property-id').value;

    const alertDiv = document.querySelector('#alert-booking-date');
    const buttonDiv = document.querySelector('#booking-button');

    const startDate = document.querySelector('#start-date');
    const endDate = document.querySelector('#end-date');

    function getCookie(name) {
        let cookieValue = null;

        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');

            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();

                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(
                        cookie.substring(name.length + 1)
                    );
                    break;
                }
            }
        }

        return cookieValue;
    }

    function showError(message) {
        bookingReady = false;
        buttonDiv.classList.add('no-display');
        alertDiv.textContent = message;
        alertDiv.classList.remove('no-display');
    }

    const csrftoken = getCookie('csrftoken');

    function confirmBooking(start, end) {
        if (successBooking || !bookingReady) {
            return;
        }

        const url = `/confirm_booking/${propertyId}`;

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({
                start: start,
                end: end
            })
        })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw err;
                    });
                }

                return response.json();
            })
            .then(data => {
                if (data.success) {
                    successBooking = true;
                    window.location.href = "/my_bookings";
                }
            })
            .catch(error => {
                showError(error.error || "Error al procesar la reserva.");
            });
    }

    function attachBookingButton(button) {
        button.addEventListener('click', () => {
            if (!bookingReady) {
                return;
            }

            button.disabled = true;
            button.textContent = "Procesando...";

            confirmBooking(
                startDate.value,
                endDate.value
            );
        });
    }

    function createBookingButton() {
        buttonDiv.classList.remove('no-display');
        buttonDiv.textContent = "";

        const button = document.createElement('button');

        button.textContent = "Confirmar Reserva";
        button.id = 'confirm-booking-button';
        button.className =
            "btn btn-dark w-100 rounded-pill mt-3 mb-3 py-2";

        attachBookingButton(button);

        buttonDiv.appendChild(button);

        return button;
    }

    window.validateBooking = function () {
        bookingReady = false;

        if (startDate.value === "" || endDate.value === "") {
            buttonDiv.classList.add('no-display');
            return;
        }

        buttonDiv.classList.remove('no-display');

        const initialDate = new Date(startDate.value);
        const finalDate = new Date(endDate.value);

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        if (initialDate < today) {
            showError("La fecha de entrada no puede ser anterior al día de hoy.");
            return;
        }

        if (initialDate >= finalDate) {
            showError("La fecha de salida debe ser posterior a la de entrada.");
            return;
        }

        alertDiv.classList.add('no-display');
        
        let button = document.querySelector('#confirm-booking-button');

        if (!button) {
            button = createBookingButton();
        }

        const url = `/booking/${propertyId}/?start=${startDate.value}&end=${endDate.value}`;

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw err;
                    });
                }

                return response.json();
            })
            .then(data => {
                if (data.available) {
                    bookingReady = true;
                } else {
                    showError("Las fechas seleccionadas ya no están disponibles.");
                }
            })
            .catch(error => {
                showError(error.error || "Error inesperado.");
            });
    }

    const initialButton = document.querySelector('#confirm-booking-button');

    if (initialButton) {
        attachBookingButton(initialButton);
    }

    if (startDate.value && endDate.value) {
        window.validateBooking();
    }
});